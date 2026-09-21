# RelayDesk on Render

This repository deploys two separate Render services from one Blueprint:

- `relaydesk-ebubedike-api`: the paid Docker web service that runs the Telegram relay continuously.
- `relaydesk-ebubedike-control`: the free static owner control panel.

The API service includes a 1 GB persistent disk mounted at `/data`. This keeps the SQLite database, encrypted Telegram session, relay settings, and delivery history across restarts and deploys.

## Initial deployment

1. In Render, create a new Blueprint from this repository.
2. When Render asks for `ADMIN_PASSWORD`, enter a strong private password and save it securely. The username is `admin`.
3. Review the monthly price before applying the Blueprint. The static control panel is free; the API compute plan and persistent disk are paid.
4. Wait until both services report a successful deploy.
5. Open `https://relaydesk-ebubedike-control.onrender.com`.
6. Enter username `admin` and the password chosen during deployment.
7. Connect Telegram, test-import a small number of posts, then start the relay.

## Important

- Never commit passwords, Telegram codes, API hashes, session strings, or `.env` files.
- Do not remove the persistent disk unless you intentionally want to lose the stored Telegram session and relay history.
- The Telegram account must be allowed to view the source and post in the destination.
- Relay only content you own or are authorized to republish. Telegram content protection is respected.
