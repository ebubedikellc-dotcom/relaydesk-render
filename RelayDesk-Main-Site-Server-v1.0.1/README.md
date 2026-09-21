# RelayDesk Complete v1.0.0

RelayDesk is the self-hosted Telegram group relay server. It imports visible historical posts from a public source group and then copies future posts into a destination group continuously. The owner control panel is supplied as a separate ZIP file.

## What is included

- One-time Telegram sign-in using API ID, API Hash, phone and verification code
- Encrypted Telegram session and API Hash storage
- Old/source group and new/destination group link fields
- Group reachability check before saving
- Full-history import or limited test import
- Text, photos, videos, voice notes, documents and album handling
- Posts are sent as ordinary new destination posts; no “imported” label is added
- 24/7 live listener
- SQLite checkpoints, delivery records and duplicate prevention
- Automatic resume after server restart
- 15-minute missed-post reconciliation
- Flood-wait handling and failed-delivery records
- Password-protected API used by the separate control panel
- Docker deployment and persistent data volume

## Telegram requirements

1. Create an API ID and API Hash at https://my.telegram.org using the new Telegram account.
2. The new account must be able to see the public source group.
3. The new account must be a member of the destination group and allowed to post.
4. The application does not require the old phone for a public source group.
5. Telegram content protection is respected and never bypassed.

## Quick VPS installation

Install Docker and the Compose plugin, unzip the package, enter its directory and run:

```bash
chmod +x setup.sh backup.sh
./setup.sh
```

The server API opens at:

```text
http://YOUR_SERVER_IP:8080
```

The setup script prints the API/control-panel username and generated password. Save them immediately. Upload the separate Control Panel ZIP and set its config.js address to this server.

## First use

1. Open the control panel.
2. Enter your Telegram API ID, API Hash and new-account phone number.
3. Enter the code Telegram sends. Enter the Telegram two-step password only if requested.
4. Paste the old/source public group link.
5. Paste the new/destination group link.
6. Press **Check both links**, then **Save connection**.
7. Import 10 test posts first.
8. Confirm the result in the destination group.
9. Press **Import all history**.
10. Press **Start relay** for continuous delivery.

## Important behavior

- Imported historical posts keep their source order but receive their new destination posting time. Telegram does not permit backdating.
- The public destination sees normal posts. “Historical import” appears only in the private control-panel status.
- Editing or deleting an old source post is not automatically copied in v1.0.0.
- The first full import may take a long time because Telegram rate limits must be respected.
- Keep the `.env` file and Docker volume private. They contain access secrets and the encrypted Telegram session.

## Common commands

```bash
docker compose ps
docker compose logs -f --tail=200
docker compose restart
docker compose down
docker compose up -d --build
```

## Updating the control-panel password

Edit `ADMIN_PASSWORD` in `.env`, then run:

```bash
docker compose up -d --force-recreate
```

## Backup

Run:

```bash
./backup.sh
```

The backup contains the database and encrypted session data. Store it securely.

## Production security

Do not expose the control panel over plain HTTP on the public internet. Put it behind HTTPS using Nginx, Caddy or Cloudflare and restrict access to the owner. An Nginx configuration example is included.
