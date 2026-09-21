import secrets
from base64 import b64decode
from fastapi import HTTPException, Request, status
from cryptography.fernet import Fernet
from .config import ADMIN_USERNAME, ADMIN_PASSWORD, FERNET_KEY

_fernet = Fernet(FERNET_KEY.encode())

def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def decrypt(value: str | None) -> str | None:
    return _fernet.decrypt(value.encode()).decode() if value else None

def require_admin(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        _reject()
    try:
        user, password = b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)
    except Exception:
        _reject()
    if not (secrets.compare_digest(user, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)):
        _reject()

def _reject() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": 'Basic realm="RelayDesk"'},
    )
