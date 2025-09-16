from __future__ import annotations

import base64
import hashlib
import json
import secrets
from pathlib import Path
from typing import Dict, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

USERS_DIR = Path(__file__).resolve().parents[1] / "users"
DEFAULT_REALM = "GeoProx"
PBKDF_ITERATIONS = 120_000


def _hash_password(password: str, *, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITERATIONS)


def hash_password_hex(password: str, *, salt: bytes) -> str:
    return _hash_password(password, salt=salt).hex()


def create_user_record(username: str, password: str, *, salt: Optional[bytes] = None) -> Dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    return {
        "username": username,
        "salt": salt.hex(),
        "hash": hash_password_hex(password, salt=salt),
    }


def load_users(directory: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    directory = directory or USERS_DIR
    users: Dict[str, Dict[str, str]] = {}
    if not directory.exists():
        return users
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            username = data.get("username")
            salt = data.get("salt")
            pw_hash = data.get("hash")
            if username and salt and pw_hash:
                users[username] = {"salt": salt, "hash": pw_hash}
        except Exception:
            continue
    return users


def verify_user(users: Dict[str, Dict[str, str]], username: str, password: str) -> bool:
    info = users.get(username)
    if not info:
        return False
    try:
        salt = bytes.fromhex(info["salt"])
        expected = bytes.fromhex(info["hash"])
    except ValueError:
        return False
    candidate = _hash_password(password, salt=salt)
    return hashlib.compare_digest(candidate, expected)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, users: Dict[str, Dict[str, str]], realm: str = DEFAULT_REALM):
        super().__init__(app)
        self.users = users
        self.realm = realm

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/healthz"):
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        username = password = None
        if auth_header.lower().startswith("basic "):
            encoded = auth_header.split(" ", 1)[1]
            try:
                decoded = base64.b64decode(encoded).decode("utf-8")
                username, password = decoded.split(":", 1)
            except Exception:
                username = password = None
        if not username or not password or not verify_user(self.users, username, password):
            return self._unauthorized_response()
        request.state.user = username
        return await call_next(request)

    def _unauthorized_response(self) -> Response:
        response = Response(status_code=401)
        response.headers["WWW-Authenticate"] = f'Basic realm="{self.realm}"'
        return response


__all__ = [
    "load_users",
    "verify_user",
    "BasicAuthMiddleware",
    "USERS_DIR",
    "create_user_record",
    "hash_password_hex",
]