import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.utils import get_peer_id

from .config import TEMP_DIR, TEMP_MAX_AGE_HOURS, TEMP_CLEANUP_INTERVAL_SECONDS
from .security import encrypt, decrypt
from . import store


class RelayEngine:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.pending = {}
        self.jobs = {}
        self._import_tasks = {}
        self._reconcile_tasks = {}
        self._relay_locks = {}
        self._handler_installed = False
        self._reconcile_task = None
        self._cleanup_task = None
        self._active_temp_paths = set()
        self._cleanup_stats = {"removed": 0, "last_run": None}

    def credentials(self):
        api_id = store.get_setting("api_id")
        api_hash_enc = store.get_setting("api_hash")
        return (int(api_id), decrypt(api_hash_enc)) if api_id and api_hash_enc else (None, None)

    def save_credentials(self, api_id: int, api_hash: str):
        store.set_setting("api_id", str(api_id))
        store.set_setting("api_hash", encrypt(api_hash.strip()))

    async def request_code(self, phone: str, api_id: int, api_hash: str):
        self.save_credentials(api_id, api_hash)
        login_id = uuid.uuid4().hex
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        self.pending[login_id] = {"client": client, "phone": phone, "phone_code_hash": sent.phone_code_hash}
        return login_id

    async def confirm_code(self, login_id: str, code: str | None, password: str | None):
        pending = self.pending.get(login_id)
        if not pending:
            raise ValueError("This verification attempt expired. Request a new code.")
        client = pending["client"]
        try:
            if password:
                await client.sign_in(password=password)
            else:
                await client.sign_in(
                    phone=pending["phone"],
                    code=(code or "").strip(),
                    phone_code_hash=pending["phone_code_hash"],
                )
        except SessionPasswordNeededError:
            return {"needs_password": True}
        session = client.session.save()
        store.set_setting("telegram_session", encrypt(session))
        self.pending.pop(login_id, None)
        if self.client and self.client is not client:
            await self.client.disconnect()
        self.client = client
        self._handler_installed = False
        await self._install_handlers()
        await self.start_enabled_relays()
        me = await client.get_me()
        return {"needs_password": False, "connected": True, "name": " ".join(filter(None, [me.first_name, me.last_name])), "username": me.username}

    async def restore(self):
        api_id, api_hash = self.credentials()
        session_enc = store.get_setting("telegram_session")
        if not (api_id and api_hash and session_enc):
            return False
        try:
            self.client = TelegramClient(StringSession(decrypt(session_enc)), api_id, api_hash)
            await self.client.connect()
            if not await self.client.is_user_authorized():
                await self.client.disconnect()
                self.client = None
                return False
            await self._install_handlers()
            await self.start_enabled_relays()
            return True
        except Exception:
            self.client = None
            return False

    async def disconnect(self):
        await self.stop_all_history_imports()
        await self.stop_all_reconciles()
        for item in list(self.pending.values()):
            try:
                await item["client"].disconnect()
            except Exception:
                pass
        self.pending.clear()
        if self.client:
            await self.client.disconnect()
        self.client = None
        self._handler_installed = False
        store.set_setting("telegram_session", "")

    async def status(self):
        connected = bool(self.client and self.client.is_connected() and await self.client.is_user_authorized())
        profile = None
        if connected:
            me = await self.client.get_me()
            profile = {"name": " ".join(filter(None, [me.first_name, me.last_name])), "username": me.username, "phone": me.phone}
        return {
            "connected": connected,
            "profile": profile,
            "jobs": self.jobs,
            "storage_cleanup": self._cleanup_stats,
        }

    async def start_maintenance(self):
        await asyncio.to_thread(self.cleanup_temp_files)
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def shutdown(self):
        await self.stop_all_history_imports()
        await self.stop_all_reconciles()
        for task in (self._reconcile_task, self._cleanup_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self.client:
            await self.client.disconnect()

    def cleanup_temp_files(self):
        """Remove abandoned downloads while preserving active transfers and relay records."""
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - (TEMP_MAX_AGE_HOURS * 3600)
        removed = 0
        for path in TEMP_DIR.iterdir():
            try:
                if str(path.resolve()) in self._active_temp_paths or path.stat().st_mtime > cutoff:
                    continue
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                removed += 1
            except (FileNotFoundError, OSError):
                continue
        self._cleanup_stats = {
            "removed": self._cleanup_stats.get("removed", 0) + removed,
            "last_run": int(time.time()),
        }
        return removed

    async def _periodic_cleanup(self):
        while True:
            await asyncio.sleep(TEMP_CLEANUP_INTERVAL_SECONDS)
            await asyncio.to_thread(self.cleanup_temp_files)

    async def check_pair(self, source_link: str, destination_link: str):
        self._require_client()
        source = await self.client.get_entity(source_link.strip())
        destination = await self.client.get_entity(destination_link.strip())
        if getattr(source, "noforwards", False):
            raise ValueError("The source group has Telegram content protection enabled and cannot be copied.")
        return {
            "source": {"id": get_peer_id(source), "title": getattr(source, "title", None) or getattr(source, "username", "Source")},
            "destination": {"id": get_peer_id(destination), "title": getattr(destination, "title", None) or getattr(destination, "username", "Destination")},
        }

    async def start_relay(self, relay_id: int):
        relay = store.get_relay(relay_id)
        if not relay:
            raise ValueError("Relay not found")
        await self.check_pair(relay["source_link"], relay["destination_link"])
        store.set_enabled(relay_id, True)
        self._schedule_reconcile(relay_id)

    async def stop_relay(self, relay_id: int):
        store.set_enabled(relay_id, False)
        await self.stop_reconcile(relay_id)

    async def start_enabled_relays(self):
        if not self.client:
            return
        for relay in store.list_relays():
            if relay["enabled"]:
                self._schedule_reconcile(relay["id"])
        if not self._reconcile_task or self._reconcile_task.done():
            self._reconcile_task = asyncio.create_task(self._periodic_reconcile())

    async def import_history(self, relay_id: int, limit: int = 0):
        if relay_id in self.jobs and self.jobs[relay_id].get("running"):
            raise ValueError("An import is already running for this relay")
        self.jobs[relay_id] = {
            "running": True,
            "processed": 0,
            "delivered": 0,
            "failed": 0,
            "message": "Starting old-post import",
        }
        task = asyncio.create_task(self._import_history_job(relay_id, limit))
        self._import_tasks[relay_id] = task

    async def stop_history_import(self, relay_id: int):
        job = self.jobs.get(relay_id)
        task = self._import_tasks.get(relay_id)
        if not job or not job.get("running") or not task or task.done():
            if job:
                job["running"] = False
                job["message"] = "Old-post import is already stopped"
            return {"stopped": False, "message": "No old-post import is running."}
        job["message"] = "Stopping old-post import…"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return {"stopped": True, "message": "Old-post import stopped."}

    async def stop_all_history_imports(self):
        for relay_id in list(self._import_tasks):
            await self.stop_history_import(relay_id)

    async def new_posts_only(self, relay_id: int):
        relay = store.get_relay(relay_id)
        if not relay:
            raise ValueError("Relay not found")
        await self.stop_history_import(relay_id)
        await self.stop_reconcile(relay_id)
        await self.check_pair(relay["source_link"], relay["destination_link"])
        source = await self.client.get_entity(relay["source_link"])
        latest = await self.client.get_messages(source, limit=1)
        latest_id = int(latest[0].id) if latest else int(relay["last_source_id"] or 0)
        store.set_checkpoint(relay_id, latest_id)
        store.set_enabled(relay_id, True)
        previous = self.jobs.get(relay_id, {})
        self.jobs[relay_id] = {
            "running": False,
            "processed": previous.get("processed", 0),
            "delivered": previous.get("delivered", 0),
            "failed": previous.get("failed", 0),
            "message": "Old posts skipped. Monitoring new posts only.",
        }
        self._schedule_reconcile(relay_id)
        return {"checkpoint": latest_id, "message": "Old posts stopped. New-post monitoring is active."}

    def _schedule_reconcile(self, relay_id: int):
        current = self._reconcile_tasks.get(relay_id)
        if current and not current.done():
            return current
        task = asyncio.create_task(self.reconcile(relay_id))
        self._reconcile_tasks[relay_id] = task
        task.add_done_callback(
            lambda finished, rid=relay_id: self._reconcile_tasks.pop(rid, None)
            if self._reconcile_tasks.get(rid) is finished else None
        )
        return task

    async def stop_reconcile(self, relay_id: int):
        task = self._reconcile_tasks.get(relay_id)
        if not task or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def stop_all_reconciles(self):
        for relay_id in list(self._reconcile_tasks):
            await self.stop_reconcile(relay_id)

    async def _import_history_job(self, relay_id: int, limit: int):
        job = self.jobs[relay_id]
        try:
            relay = store.get_relay(relay_id)
            self._require_client()
            source = await self.client.get_entity(relay["source_link"])
            pending_group = []
            async for message in self.client.iter_messages(source, limit=limit or None, reverse=True):
                if message.action:
                    continue
                if pending_group and message.grouped_id != pending_group[0].grouped_id:
                    result = await self._deliver(relay, pending_group)
                    job["processed"] += len(pending_group)
                    job["delivered" if result else "failed"] += len(pending_group)
                    pending_group = []
                    job["message"] = f"Processed {job['processed']} posts"
                    await asyncio.sleep(0.35)
                if message.grouped_id:
                    pending_group.append(message)
                else:
                    result = await self._deliver(relay, [message])
                    job["processed"] += 1
                    job["delivered" if result else "failed"] += 1
                    job["message"] = f"Processed {job['processed']} posts"
                    await asyncio.sleep(0.35)
            if pending_group:
                result = await self._deliver(relay, pending_group)
                job["processed"] += len(pending_group)
                job["delivered" if result else "failed"] += len(pending_group)
            job["message"] = "Historical import completed"
        except asyncio.CancelledError:
            job["message"] = "Old-post import stopped"
            raise
        except Exception as exc:
            job["message"] = f"Import stopped: {str(exc)[:180]}"
        finally:
            job["running"] = False
            if self._import_tasks.get(relay_id) is asyncio.current_task():
                self._import_tasks.pop(relay_id, None)

    async def reconcile(self, relay_id: int):
        relay = store.get_relay(relay_id)
        if not relay or not relay["enabled"]:
            return
        try:
            self._require_client()
            source = await self.client.get_entity(relay["source_link"])
            min_id = int(relay["last_source_id"] or 0)
            messages = []
            async for message in self.client.iter_messages(source, min_id=min_id, reverse=True):
                if not message.action:
                    messages.append(message)
            i = 0
            while i < len(messages):
                message = messages[i]
                if message.grouped_id:
                    group = [message]; i += 1
                    while i < len(messages) and messages[i].grouped_id == message.grouped_id:
                        group.append(messages[i]); i += 1
                    current = store.get_relay(relay_id)
                    if not current or not current["enabled"]:
                        return
                    if max(item.id for item in group) <= int(current["last_source_id"] or 0):
                        continue
                    await self._deliver(relay, group)
                else:
                    i += 1
                    current = store.get_relay(relay_id)
                    if not current or not current["enabled"]:
                        return
                    if message.id <= int(current["last_source_id"] or 0):
                        continue
                    await self._deliver(relay, [message])
        except Exception as exc:
            store.record_delivery(relay_id, "", 0, "system", "failed", error=f"Reconcile: {str(exc)[:300]}")

    async def _periodic_reconcile(self):
        while self.client and self.client.is_connected():
            await asyncio.sleep(900)
            for relay in store.list_relays():
                if relay["enabled"]:
                    await self._retry_failures(relay)
                    self._schedule_reconcile(relay["id"])

    async def _retry_failures(self, relay):
        try:
            source = await self.client.get_entity(relay["source_link"])
            for item in store.failed_deliveries(relay["id"]):
                current = store.get_relay(relay["id"])
                if not current or not current["enabled"]:
                    return
                if item["source_message_id"] <= int(current["last_source_id"] or 0):
                    continue
                message = await self.client.get_messages(source, ids=item["source_message_id"])
                if message:
                    await self._deliver(relay, [message])
                    await asyncio.sleep(0.35)
        except Exception:
            pass

    async def _install_handlers(self):
        if self._handler_installed or not self.client:
            return

        @self.client.on(events.Album())
        async def album_handler(event):
            await self._route_live(event.chat_id, list(event.messages))

        @self.client.on(events.NewMessage())
        async def message_handler(event):
            if event.message.grouped_id or event.message.action:
                return
            await self._route_live(event.chat_id, [event.message])

        self._handler_installed = True

    async def _route_live(self, chat_id, messages):
        for relay in store.list_relays():
            if not relay["enabled"]:
                continue
            try:
                source = await self.client.get_entity(relay["source_link"])
                if get_peer_id(source) == chat_id:
                    await self._deliver(relay, messages)
            except Exception as exc:
                store.record_delivery(relay["id"], chat_id, messages[0].id, "live", "failed", error=str(exc)[:300])

    async def _deliver(self, relay, messages):
        lock = self._relay_locks.setdefault(relay["id"], asyncio.Lock())
        async with lock:
            return await self._deliver_unlocked(relay, messages)

    async def _deliver_unlocked(self, relay, messages):
        messages = sorted(messages, key=lambda m: m.id)
        fresh = [m for m in messages if not store.delivery_exists(relay["id"], m.id)]
        if not fresh:
            return True
        first = fresh[0]
        source_id = first.chat_id
        try:
            destination = await self.client.get_entity(relay["destination_link"])
            sent_ids = []
            if len(fresh) > 1:
                sent_ids = await self._send_album(destination, fresh, bool(relay["import_media"]))
            else:
                sent_ids = await self._send_one(destination, first, bool(relay["import_media"]))
            for message in fresh:
                store.record_delivery(relay["id"], source_id, message.id, self._kind(message), "delivered", sent_ids)
                store.set_checkpoint(relay["id"], message.id)
            return True
        except FloodWaitError as exc:
            await asyncio.sleep(min(exc.seconds + 1, 300))
            return await self._deliver_unlocked(relay, fresh)
        except Exception as exc:
            for message in fresh:
                store.record_delivery(relay["id"], source_id, message.id, self._kind(message), "failed", error=str(exc)[:500])
            return False

    async def _send_one(self, destination, message, import_media=True):
        text = message.message or ""
        if not message.media or not import_media:
            if not text:
                return []
            sent = await self.client.send_message(destination, text, formatting_entities=message.entities, link_preview=True)
            return [sent.id]
        folder = Path(tempfile.mkdtemp(prefix="relay_", dir=TEMP_DIR))
        self._active_temp_paths.add(str(folder.resolve()))
        try:
            path = await message.download_media(file=str(folder))
            if not path:
                if text:
                    sent = await self.client.send_message(destination, text, formatting_entities=message.entities)
                    return [sent.id]
                return []
            sent = await self.client.send_file(destination, path, caption=text or None, formatting_entities=message.entities,
                voice_note=bool(getattr(message, "voice", None)), video_note=bool(getattr(message, "video_note", None)),
                supports_streaming=bool(getattr(message, "video", None)))
            return [sent.id]
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self._active_temp_paths.discard(str(folder.resolve()))

    async def _send_album(self, destination, messages, import_media=True):
        if not import_media:
            ids = []
            for message in messages:
                ids.extend(await self._send_one(destination, message, False))
            return ids
        folder = Path(tempfile.mkdtemp(prefix="album_", dir=TEMP_DIR))
        self._active_temp_paths.add(str(folder.resolve()))
        try:
            files, captions, entities = [], [], []
            for message in messages:
                path = await message.download_media(file=str(folder))
                if path:
                    files.append(path); captions.append(message.message or ""); entities.append(message.entities or [])
                elif message.message:
                    await self.client.send_message(destination, message.message, formatting_entities=message.entities)
            if not files:
                return []
            sent = await self.client.send_file(destination, files, caption=captions, formatting_entities=entities)
            if not isinstance(sent, list):
                sent = [sent]
            return [m.id for m in sent]
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self._active_temp_paths.discard(str(folder.resolve()))

    def _kind(self, message):
        if getattr(message, "photo", None): return "photo"
        if getattr(message, "video", None): return "video"
        if getattr(message, "voice", None): return "voice"
        if getattr(message, "document", None): return "file"
        return "text"

    def _require_client(self):
        if not self.client or not self.client.is_connected():
            raise ValueError("Connect Telegram first")


engine = RelayEngine()
