import os
from pathlib import Path

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/data/relaydesk.db"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "/data/tmp"))
TEMP_MAX_AGE_HOURS = max(1, int(os.getenv("TEMP_MAX_AGE_HOURS", "24")))
TEMP_CLEANUP_INTERVAL_SECONDS = max(300, int(os.getenv("TEMP_CLEANUP_INTERVAL_SECONDS", "3600")))
DELIVERY_LOG_RETENTION_DAYS = max(7, int(os.getenv("DELIVERY_LOG_RETENTION_DAYS", "30")))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
FERNET_KEY = os.getenv("FERNET_KEY", "")

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD is required")
if not FERNET_KEY:
    raise RuntimeError("FERNET_KEY is required")
