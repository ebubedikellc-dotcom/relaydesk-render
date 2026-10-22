import asyncio
import secrets
from base64 import b64decode
from contextlib import asynccontextmanager
import os
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import ADMIN_USERNAME, ADMIN_PASSWORD
from . import store
from .telegram_service import engine
from .post_format import format_post
from .link_filter import without_links

@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    await engine.start_maintenance()
    await engine.restore()
    yield
    await engine.shutdown()


app = FastAPI(title="RelayDesk", version="1.3.0", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CONTROL_PANEL_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def admin_gate(request: Request, call_next):
    # Let CORS preflight requests reach CORSMiddleware without Basic Auth.
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    valid = False
    if auth.lower().startswith("basic "):
        try:
            user, password = b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)
            valid = secrets.compare_digest(user, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)
        except Exception:
            valid = False
    if not valid:
        return JSONResponse({"detail": "Authentication required"}, 401, headers={"WWW-Authenticate": 'Basic realm="RelayDesk"'})
    return await call_next(request)


class RequestCode(BaseModel):
    api_id: int
    api_hash: str = Field(min_length=20)
    phone: str = Field(min_length=7)


class ConfirmCode(BaseModel):
    login_id: str
    code: str | None = None
    password: str | None = None


class RelayInput(BaseModel):
    id: int | None = None
    name: str = "My relay"
    source_link: str
    destination_link: str
    import_media: bool = True


class PairInput(BaseModel):
    source_link: str
    destination_link: str


class ImportInput(BaseModel):
    limit: int = Field(default=0, ge=0, le=1000000)


class OwnerMessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class PostFormatInput(BaseModel):
    enabled: bool = True
    default_sport: Literal["football", "table_tennis", "basketball", "tennis", "betting"] = "football"
    source_timezone: str = Field(default="Africa/Lagos", max_length=80)
    stake_high: bool = True
    promo_platform: Literal["Stake", "SportyBet", "Bet9ja", "BetKing", "Betway", "1xBet"] = "Stake"
    promo_code: str = Field(default="", max_length=50, pattern=r"^[A-Za-z0-9_-]*$")
    crash_promo_code: str = Field(default="", max_length=50, pattern=r"^[A-Za-z0-9_-]*$")


class PostPreviewInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    posted_at: datetime | None = None
    settings: PostFormatInput | None = None


def validated_format(body):
    try:
        ZoneInfo(body.source_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Choose a valid source timezone, such as Africa/Lagos.")
    for code in (body.promo_code, body.crash_promo_code):
        if code.upper() in {"YOURCODE", "PROMOCODE", "PLACEHOLDER"}:
            raise HTTPException(422, "Enter your real promo code or leave it blank.")
    return body.model_dump()


@app.get("/api/post-format")
async def get_post_format():
    return {"settings": store.post_format_settings()}


@app.put("/api/post-format")
async def save_post_format(body: PostFormatInput):
    settings = validated_format(body)
    store.save_post_format_settings(settings)
    return {"ok": True, "settings": settings, "message": "Post format saved. New deliveries use these settings."}


@app.post("/api/post-format/preview")
async def preview_post_format(body: PostPreviewInput):
    settings = validated_format(body.settings) if body.settings else store.post_format_settings()
    if body.posted_at and body.posted_at.utcoffset() is None:
        raise HTTPException(422, "The original posting time must include its timezone.")
    result = format_post(body.text, settings, body.posted_at)
    preview = result.preview()
    if result.action == "unchanged":
        preview["plain_text"] = without_links(body.text)[0]
    return preview


@app.post("/api/relays/{relay_id}/message")
async def send_owner_message(relay_id: int, body: OwnerMessageInput):
    try:
        message_id = await engine.send_owner_message(relay_id, body.text)
        return {"ok": True, "message_id": message_id, "message": "Message sent to your destination group."}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.get("/health")
async def health():
    return {"ok": True, "version": "1.3.0", "post_format": "category-cards"}


@app.get("/api/status")
async def status():
    telegram = await engine.status()
    return {"telegram": telegram, "relays": store.list_relays(), "stats": store.stats()}


@app.post("/api/auth/request-code")
async def request_code(body: RequestCode):
    try:
        login_id = await engine.request_code(body.phone.strip(), body.api_id, body.api_hash.strip())
        return {"ok": True, "login_id": login_id, "message": "Telegram sent the verification code."}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/auth/confirm")
async def confirm_code(body: ConfirmCode):
    try:
        return await engine.confirm_code(body.login_id, body.code, body.password)
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/auth/disconnect")
async def disconnect():
    await engine.disconnect()
    return {"ok": True}


@app.post("/api/groups/check")
async def check_groups(body: PairInput):
    try:
        return await engine.check_pair(body.source_link, body.destination_link)
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/relays")
async def save_relay(body: RelayInput):
    try:
        await engine.check_pair(body.source_link, body.destination_link)
        relay_id = store.save_relay(body.model_dump())
        return {"ok": True, "id": relay_id, "relay": store.get_relay(relay_id)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/relays/{relay_id}/start")
async def start_relay(relay_id: int):
    try:
        await engine.start_relay(relay_id)
        return {"ok": True, "message": "Relay started. New posts will be delivered automatically."}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/relays/{relay_id}/stop")
async def stop_relay(relay_id: int):
    await engine.stop_relay(relay_id)
    return {"ok": True, "message": "Relay stopped."}


@app.post("/api/relays/{relay_id}/import")
async def import_history(relay_id: int, body: ImportInput):
    try:
        await engine.import_history(relay_id, body.limit)
        return {"ok": True, "message": "Historical import started in the background."}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/relays/{relay_id}/import/stop")
async def stop_history_import(relay_id: int):
    try:
        result = await engine.stop_history_import(relay_id)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/relays/{relay_id}/new-only")
async def new_posts_only(relay_id: int):
    try:
        result = await engine.new_posts_only(relay_id)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/activity")
async def activity(limit: int = 100):
    return {"items": store.recent_deliveries(max(1, min(limit, 500)))}


@app.get("/")
async def index():
    return {"name": "RelayDesk Telegram Relay Server", "status": "online", "control_panel": "Install the separate RelayDesk Control Panel package."}
