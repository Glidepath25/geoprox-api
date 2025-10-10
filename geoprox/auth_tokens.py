from __future__ import annotations

import os
import time
from typing import Dict, Optional, Tuple

import jwt


ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
DEFAULT_ACCESS_TTL = int(os.environ.get("JWT_ACCESS_TTL", "3600"))
DEFAULT_REFRESH_TTL = int(os.environ.get("JWT_REFRESH_TTL", str(60 * 60 * 24 * 30)))


class TokenError(Exception):
    """Raised when a JWT token cannot be validated."""


def _now() -> int:
    return int(time.time())


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    fallback = os.environ.get("SESSION_SECRET")
    if fallback:
        return fallback
    return "dev-secret-key"


def _encode(payload: Dict[str, object]) -> str:
    token = jwt.encode(payload, _secret(), algorithm=ALGORITHM)
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def _decode(token: str) -> Dict[str, object]:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def create_access_token(
    *,
    username: str,
    session_token: str,
    scope: Optional[str] = None,
    ttl: Optional[int] = None,
) -> Tuple[str, int]:
    lifetime = ttl or DEFAULT_ACCESS_TTL
    issued_at = _now()
    payload: Dict[str, object] = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + lifetime,
        "stk": session_token,
        "typ": "access",
    }
    if scope:
        payload["scope"] = scope
    return _encode(payload), payload["exp"]


def create_refresh_token(
    *,
    username: str,
    session_token: str,
    scope: Optional[str] = None,
    ttl: Optional[int] = None,
) -> Tuple[str, int]:
    lifetime = ttl or DEFAULT_REFRESH_TTL
    issued_at = _now()
    payload: Dict[str, object] = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + lifetime,
        "stk": session_token,
        "typ": "refresh",
    }
    if scope:
        payload["scope"] = scope
    return _encode(payload), payload["exp"]


def decode_access_token(token: str) -> Dict[str, object]:
    payload = _decode(token)
    token_type = payload.get("typ")
    if token_type not in (None, "access"):
        raise TokenError("Invalid token type for access token")
    return payload


def decode_refresh_token(token: str) -> Dict[str, object]:
    payload = _decode(token)
    if payload.get("typ") != "refresh":
        raise TokenError("Invalid token type for refresh token")
    return payload
