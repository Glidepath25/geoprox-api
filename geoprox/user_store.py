from __future__ import annotations

import hmac
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


PBKDF_ITERATIONS = 120_000

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "users.db"
LEGACY_USERS_DIR = Path(__file__).resolve().parents[1] / "users"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def _hash_password(password: str, *, salt: bytes) -> bytes:
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITERATIONS)


def hash_password_hex(password: str, *, salt: bytes) -> str:
    return _hash_password(password, salt=salt).hex()


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                email TEXT,
                company TEXT,
                company_number TEXT,
                phone TEXT,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")


init_db()


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["name"],
        "email": row["email"],
        "company": row["company"],
        "company_number": row["company_number"],
        "phone": row["phone"],
        "salt": row["salt"],
        "password_hash": row["password_hash"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def list_users(*, include_disabled: bool = True) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        if include_disabled:
            rows = conn.execute("SELECT * FROM users ORDER BY is_active DESC, username ASC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM users WHERE is_active = 1 ORDER BY username ASC").fetchall()
    return [_row_to_dict(row) for row in rows]


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def create_user(
    *,
    username: str,
    password: str,
    name: str,
    email: str = "",
    company: str = "",
    company_number: str = "",
    phone: str = "",
    is_admin: bool = False,
    is_active: bool = True,
) -> Dict[str, Any]:
    salt = secrets.token_bytes(16)
    password_hash = hash_password_hex(password, salt=salt)
    now = _now()
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, name, email, company, company_number, phone, salt, password_hash, is_admin, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                name,
                email,
                company,
                company_number,
                phone,
                salt.hex(),
                password_hash,
                int(is_admin),
                int(is_active),
                now,
                now,
            ),
        )
        user_id = cursor.lastrowid
    return get_user_by_id(user_id)  # type: ignore[return-value]


def update_user(user_id: int, **fields: Any) -> None:
    allowed = {
        "name",
        "email",
        "company",
        "company_number",
        "phone",
        "is_admin",
        "is_active",
    }
    updates = {k: (int(v) if k in {"is_admin", "is_active"} else v) for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    values: List[Any] = list(updates.values())
    values.append(user_id)
    with _get_conn() as conn:
        conn.execute(f"UPDATE users SET {columns} WHERE id = ?", values)


def set_password(user_id: int, password: str) -> None:
    salt = secrets.token_bytes(16)
    password_hash = hash_password_hex(password, salt=salt)
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE users SET salt = ?, password_hash = ?, updated_at = ? WHERE id = ?",
            (salt.hex(), password_hash, now, user_id),
        )


def verify_credentials(username: str, password: str, *, include_disabled: bool = False) -> Optional[Dict[str, Any]]:
    user = get_user_by_username(username)
    if not user:
        return None
    if not user["is_active"] and not include_disabled:
        return None
    try:
        salt = bytes.fromhex(user["salt"])
        expected = bytes.fromhex(user["password_hash"])
    except ValueError:
        return None
    candidate = _hash_password(password, salt=salt)
    if not hmac.compare_digest(candidate, expected):
        return None
    return user


def disable_user(user_id: int) -> None:
    update_user(user_id, is_active=False)


def enable_user(user_id: int) -> None:
    update_user(user_id, is_active=True)


# ---------------------------------------------------------------------------
# Legacy import
# ---------------------------------------------------------------------------


def import_legacy_users() -> None:
    existing = list_users(include_disabled=True)
    if existing:
        return
    if not LEGACY_USERS_DIR.exists():
        return
    json_files = sorted(LEGACY_USERS_DIR.glob("*.json"))
    if not json_files:
        return
    import json

    now = _now()
    admin_assigned = False
    with _get_conn() as conn:
        for path in json_files:
            try:
                data = json.loads(path.read_text())
                username = data.get("username")
                salt = data.get("salt")
                pw_hash = data.get("hash")
                if not username or not salt or not pw_hash:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (username, name, email, company, company_number, phone, salt, password_hash, is_admin, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, '', '', '', ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        username,
                        username,
                        "",
                        salt,
                        pw_hash,
                        1 if not admin_assigned else 0,
                        now,
                        now,
                    ),
                )
                admin_assigned = True
            except Exception:
                continue


import_legacy_users()


__all__ = [
    "create_user",
    "disable_user",
    "enable_user",
    "get_user_by_id",
    "get_user_by_username",
    "hash_password_hex",
    "init_db",
    "list_users",
    "set_password",
    "update_user",
    "verify_credentials",
]
