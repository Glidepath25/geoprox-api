from __future__ import annotations

"""Package initialisation tweaks used across the API."""

import hashlib
from typing import Any


def _patch_md5_usedforsecurity() -> None:
    """Allow dependencies to pass the usedforsecurity kwarg on md5."""
    try:
        hashlib.md5(b"test", usedforsecurity=False)  # type: ignore[call-arg]
        return  # Runtime already accepts the flag
    except TypeError:
        pass
    except Exception:
        return

    original_md5 = hashlib.md5

    def md5_compat(*args: Any, **kwargs: Any):
        kwargs.pop("usedforsecurity", None)
        return original_md5(*args, **kwargs)

    hashlib.md5 = md5_compat  # type: ignore[assignment]

    try:
        from starlette import _compat
    except Exception:
        return

    def md5_hexdigest(data: bytes, *, usedforsecurity: bool = True) -> str:
        return hashlib.md5(data).hexdigest()

    _compat.md5_hexdigest = md5_hexdigest  # type: ignore[assignment]


_patch_md5_usedforsecurity()