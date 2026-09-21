#!/usr/bin/env sh
set -eu
if [ ! -f .env ]; then
  ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  FERNET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")"
  sed "s|CHANGE_THIS_STRONG_PASSWORD|$ADMIN_PASSWORD|; s|GENERATE_WITH_SETUP_SCRIPT|$FERNET_KEY|" .env.example > .env
  chmod 600 .env
  echo "Control-panel username: admin"
  echo "Control-panel password: $ADMIN_PASSWORD"
  echo "Save this password now. It is also stored in .env."
fi
docker compose up -d --build
echo "RelayDesk is running at http://YOUR_SERVER_IP:8080"

