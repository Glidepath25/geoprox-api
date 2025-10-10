from typing import Optional

from pydantic import BaseModel


class MobileAuthRequest(BaseModel):
    username: str
    password: str


class MobileRefreshRequest(BaseModel):
    refresh_token: str


class MobileAuthResponse(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    token_type: str = "bearer"
    scope: Optional[str] = None


__all__ = [
    "MobileAuthRequest",
    "MobileRefreshRequest",
    "MobileAuthResponse",
]
