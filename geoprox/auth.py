from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import Dict, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from geoprox import user_store
from geoprox.user_store import hash_password_hex

USERS_DIR = Path(__file__).resolve().parents[1] / "users"
DEFAULT_REALM = "GeoProx"
PBKDF_ITERATIONS = 120_000


def create_user_record(username: str, password: str, *, salt: Optional[bytes] = None) -> Dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    return {
        "username": username,
        "salt": salt.hex(),
        "hash": hash_password_hex(password, salt=salt),
    }


def load_users(directory: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Return active users in a format compatible with legacy callers."""
    users: Dict[str, Dict[str, str]] = {}
    for record in user_store.list_users(include_disabled=False):
        users[record["username"]] = {"salt": record["salt"], "hash": record["password_hash"]}
    return users


def verify_user(users: Dict[str, Dict[str, str]], username: str, password: str) -> bool:
    """Compatibility wrapper. ``users`` argument is ignored."""
    return user_store.verify_credentials(username, password) is not None


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Legacy Basic auth middleware using the new user store."""

    def __init__(self, app, realm: str = DEFAULT_REALM):
        super().__init__(app)
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
        if not username or not password or user_store.verify_credentials(username, password) is None:
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
    "PBKDF_ITERATIONS",
]
