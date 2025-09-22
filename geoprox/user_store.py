from __future__ import annotations

import hmac
import secrets
import sqlite3
from contextlib import contextmanager
import logging
log = logging.getLogger("uvicorn.error")

from geoprox.db import USE_POSTGRES, get_postgres_conn
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


PBKDF_ITERATIONS = 120_000

LICENSE_TIERS: Dict[str, Dict[str, Optional[int]]] = {
    "free_trial": {"label": "Free Trial", "monthly_limit": 10},
    "basic": {"label": "Basic", "monthly_limit": 100},
    "standard": {"label": "Standard", "monthly_limit": 200},
    "pro": {"label": "Pro", "monthly_limit": None},
}
DEFAULT_LICENSE_TIER = "basic"

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "users.db"
LEGACY_USERS_DIR = Path(__file__).resolve().parents[1] / "users"


@contextmanager
def _sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_conn():
    if USE_POSTGRES:
        return get_postgres_conn()
    return _sqlite_conn()


def _log_conn_details(conn: Any, where: str) -> None:
    row = conn.execute(
        '''
        SELECT
            current_database() AS db,
            current_user AS usr,
            pg_is_in_recovery() AS on_replica,
            current_setting('transaction_read_only', true) AS tx_ro,
            inet_server_addr()::text AS server_ip,
            inet_server_port() AS server_port
        '''
    ).fetchone()
    if not row:
        log.warning("DB[%s] connection details unavailable", where)
        return
    log.warning(
        "DB[%s] db=%s usr=%s replica=%s ro=%s addr=%s:%s",
        where,
        row.get("db"),
        row.get("usr"),
        row.get("on_replica"),
        row.get("tx_ro"),
        row.get("server_ip"),
        row.get("server_port"),
    )


def _debug_conn(where: str = "", conn: Optional[Any] = None) -> None:
    if not USE_POSTGRES:
        return
    try:
        if conn is None:
            with _get_conn() as inspect_conn:
                _log_conn_details(inspect_conn, where)
        else:
            _log_conn_details(conn, where)
    except Exception:
        log.exception("debug conn failed at %s", where)


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Licensing helpers
# ---------------------------------------------------------------------------



def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)

def normalize_license_tier(tier: Optional[str]) -> str:
    if not tier:
        return DEFAULT_LICENSE_TIER
    key = str(tier).strip().lower()
    if key not in LICENSE_TIERS:
        raise ValueError(f"Unknown license tier '{tier}'")
    return key


def get_license_monthly_limit(tier: str) -> Optional[int]:
    key = normalize_license_tier(tier)
    return LICENSE_TIERS[key]["monthly_limit"]


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def _hash_password(password: str, *, salt: bytes) -> bytes:
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ITERATIONS)


def hash_password_hex(password: str, *, salt: bytes) -> str:
    return _hash_password(password, salt=salt).hex()


# ---------------------------------------------------------------------------
# Database initialisation and migrations
# ---------------------------------------------------------------------------


def init_db() -> None:
    if USE_POSTGRES:
        with _get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    company_number TEXT,
                    phone TEXT,
                    email TEXT,
                    notes TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    email TEXT,
                    company TEXT,
                    company_number TEXT,
                    phone TEXT,
                    company_id INTEGER REFERENCES companies(id),
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    license_tier TEXT NOT NULL DEFAULT 'basic',
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    require_password_change BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id)")
        return

    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                company_number TEXT,
                phone TEXT,
                email TEXT,
                notes TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name)")

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
                company_id INTEGER,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                license_tier TEXT NOT NULL DEFAULT 'basic',
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                require_password_change INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(company_id) REFERENCES companies(id)
            )
            """
        )
        _ensure_additional_user_columns(conn)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id)")

        _migrate_company_assignments(conn)



def _ensure_additional_user_columns(conn: sqlite3.Connection) -> None:
    if USE_POSTGRES:
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "company_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN company_id INTEGER")
    if "require_password_change" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN require_password_change INTEGER NOT NULL DEFAULT 0")
    if "license_tier" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN license_tier TEXT NOT NULL DEFAULT 'basic'")


def _ensure_company(
    conn: sqlite3.Connection,
    *,
    name: str,
    company_number: str = "",
    phone: str = "",
    email: str = "",
) -> Optional[int]:
    cleaned = name.strip()
    if not cleaned:
        return None
    existing = conn.execute(
        "SELECT id, company_number, phone, email FROM companies WHERE lower(name) = lower(?)",
        (cleaned,),
    ).fetchone()
    now = _now()
    if existing:
        updates: Dict[str, Any] = {}
        if company_number and not (existing["company_number"] or "").strip():
            updates["company_number"] = company_number
        if phone and not (existing["phone"] or "").strip():
            updates["phone"] = phone
        if email and not (existing["email"] or "").strip():
            updates["email"] = email
        if updates:
            updates["updated_at"] = now
            columns = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE companies SET {columns} WHERE id = ?",
                [*updates.values(), existing["id"]],
            )
        return existing["id"]
    cursor = conn.execute(
        """
        INSERT INTO companies (name, company_number, phone, email, notes, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, '', 1, ?, ?)
        """,
        (cleaned, company_number.strip(), phone.strip(), email.strip(), now, now),
    )
    return cursor.lastrowid


def _migrate_company_assignments(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, company, company_number, phone, company_id FROM users").fetchall()
    cache: Dict[str, int] = {}
    for row in rows:
        if row["company_id"]:
            continue
        name = (row["company"] or "").strip()
        if not name:
            continue
        if name not in cache:
            cache[name] = _ensure_company(
                conn,
                name=name,
                company_number=row["company_number"] or "",
                phone=row["phone"] or "",
            ) or 0
        company_id = cache.get(name) or 0
        if not company_id:
            continue
        conn.execute(
            "UPDATE users SET company_id = ?, updated_at = ? WHERE id = ?",
            (company_id, _now(), row["id"]),
        )


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
        "company_id": row["company_id"],
        "license_tier": row["license_tier"] if "license_tier" in row.keys() else DEFAULT_LICENSE_TIER,
        "salt": row["salt"],
        "password_hash": row["password_hash"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "require_password_change": bool(row["require_password_change"]) if "require_password_change" in row.keys() else False,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _company_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "company_number": row["company_number"],
        "phone": row["phone"],
        "email": row["email"],
        "notes": row["notes"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Company operations
# ---------------------------------------------------------------------------


def list_companies(*, include_inactive: bool = False) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        if include_inactive:
            rows = conn.execute("SELECT * FROM companies ORDER BY is_active DESC, name ASC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM companies WHERE is_active = ? ORDER BY name ASC", (True,)).fetchall()
    return [_company_row_to_dict(row) for row in rows]


def get_company_by_id(company_id: int) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return _company_row_to_dict(row) if row else None


def get_company_by_name(name: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE lower(name) = lower(?)",
            (name.strip(),),
        ).fetchone()
    return _company_row_to_dict(row) if row else None


def create_company(
    *,
    name: str,
    company_number: str = "",
    phone: str = "",
    email: str = "",
    notes: str = "",
    is_active: bool = True,
) -> Dict[str, Any]:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Company name is required")
    now = _now()
    sql = """
        INSERT INTO companies (name, company_number, phone, email, notes, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        cleaned,
        company_number.strip(),
        phone.strip(),
        email.strip(),
        notes.strip(),
        _coerce_bool(is_active),
        now,
        now,
    )
    if USE_POSTGRES:
        sql += " RETURNING id, name, company_number, phone, email, notes, is_active, created_at, updated_at"
        with _get_conn() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            db_name = conn.execute("SELECT current_database()").fetchone()["current_database"]
            log.info("create_company current_database=%s", db_name)
        if not row:
            raise RuntimeError("Failed to create company record")
        return _company_row_to_dict(row)
    with _get_conn() as conn:
        cursor = conn.execute(sql, params)
        company_id = cursor.lastrowid
    record = None
    try:
        company_id_int = int(company_id)
    except (TypeError, ValueError):
        company_id_int = None
    if company_id_int is not None:
        record = get_company_by_id(company_id_int)
        log.info("create_company lookup by id(%s) -> %s", company_id_int, record)
    if not record:
        record = get_company_by_name(cleaned)
        log.info("create_company lookup by name(%s) -> %s", cleaned, record)
    if not record:
        raise RuntimeError("Failed to create company record")
    return record

def update_company(company_id: int, **fields: Any) -> None:
    allowed = {"name", "company_number", "phone", "email", "notes", "is_active"}
    updates = {k: (_coerce_bool(v) if k == "is_active" else v) for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    values: List[Any] = list(updates.values())
    values.append(company_id)
    with _get_conn() as conn:
        conn.execute(f"UPDATE companies SET {columns} WHERE id = ?", values)


# ---------------------------------------------------------------------------
# User CRUD operations
# ---------------------------------------------------------------------------


def list_users(*, include_disabled: bool = True, company_id: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM users"
    params: List[Any] = []
    filters: List[str] = []
    if not include_disabled:
        filters.append("is_active = ?")
        params.append(True)
    if company_id is not None:
        filters.append("company_id = ?")
        params.append(company_id)
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " ORDER BY is_active DESC, username ASC"
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        _debug_conn("get_user_by_username", conn)
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _resolve_company(company_id: Optional[int], company_name: str) -> Dict[str, Any]:
    if company_id is None and not company_name.strip():
        return {"id": None, "name": ""}
    if company_id is not None:
        company = get_company_by_id(company_id)
        if not company:
            raise ValueError("Company not found")
        return company
    company = get_company_by_name(company_name)
    if company:
        return company
    return create_company(name=company_name)


def create_user(
    *,
    username: str,
    password: str,
    name: str,
    email: str = "",
    company: str = "",
    company_number: str = "",
    phone: str = "",
    company_id: Optional[int] = None,
    is_admin: bool = False,
    is_active: bool = True,
    require_password_change: bool = True,
    license_tier: str = DEFAULT_LICENSE_TIER,
) -> Dict[str, Any]:
    resolved_company = _resolve_company(company_id, company)
    salt = secrets.token_bytes(16)
    password_hash = hash_password_hex(password, salt=salt)
    now = _now()
    normalized_tier = normalize_license_tier(license_tier)
    sql = """
        INSERT INTO users (username, name, email, company, company_number, phone, company_id, salt, password_hash, is_admin, is_active, require_password_change, license_tier, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        username,
        name,
        email,
        resolved_company["name"] if resolved_company["id"] else company,
        company_number,
        phone,
        resolved_company["id"],
        salt.hex(),
        password_hash,
        _coerce_bool(is_admin),
        _coerce_bool(is_active),
        _coerce_bool(require_password_change),
        normalized_tier,
        now,
        now,
    )
    if USE_POSTGRES:
        sql += " RETURNING id, username, name, email, company, company_number, phone, company_id, license_tier, salt, password_hash, is_admin, is_active, require_password_change, created_at, updated_at"
        with _get_conn() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            _debug_conn("create_user", conn)
        if not row:
            raise RuntimeError("Failed to create user record")
        return _row_to_dict(row)
    with _get_conn() as conn:
        cursor = conn.execute(sql, params)
        user_id = cursor.lastrowid
    record = None
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        user_id_int = None
    if user_id_int is not None:
        record = get_user_by_id(user_id_int)
        log.info("create_user lookup by id(%s) -> %s", user_id_int, record)
    if not record:
        record = get_user_by_username(username)
        log.info("create_user lookup by username(%s) -> %s", username, record)
    if not record:
        raise RuntimeError("Failed to create user record")
    return record

def update_user(user_id: int, **fields: Any) -> None:
    allowed = {
        "name",
        "email",
        "company",
        "company_number",
        "phone",
        "company_id",
        "is_admin",
        "is_active",
        "require_password_change",
        "license_tier",
    }
    updates: Dict[str, Any] = {}
    company_update_requested = any(key in fields for key in ("company", "company_id"))
    if company_update_requested:
        company_id = fields.get("company_id")
        company_name = fields.get("company", "")
        if company_id is None and not company_name:
            updates["company_id"] = None
            updates["company"] = ""
        else:
            resolved = _resolve_company(company_id if company_id is not None else None, company_name)
            updates["company_id"] = resolved["id"]
            updates["company"] = resolved["name"]
    for key, value in fields.items():
        if key not in allowed or key in {"company", "company_id"}:
            continue
        if key == "license_tier":
            if value is None:
                continue
            updates[key] = normalize_license_tier(value)
        elif key in {"is_admin", "is_active", "require_password_change"}:
            updates[key] = _coerce_bool(value)
        else:
            updates[key] = value
    if not updates:
        return
    updates["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    values: List[Any] = list(updates.values())
    values.append(user_id)
    with _get_conn() as conn:
        conn.execute(f"UPDATE users SET {columns} WHERE id = ?", values)


def set_password(user_id: int, password: str, *, require_change: Optional[bool] = None) -> None:
    salt = secrets.token_bytes(16)
    password_hash = hash_password_hex(password, salt=salt)
    now = _now()
    columns = ["salt = ?", "password_hash = ?", "updated_at = ?"]
    values: List[Any] = [salt.hex(), password_hash, now]
    if require_change is not None:
        columns.append("require_password_change = ?")
        values.append(_coerce_bool(require_change))
    values.append(user_id)
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(columns)} WHERE id = ?",
            values,
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
                sql = """
                    INSERT INTO users (username, name, email, company, company_number, phone, company_id, salt, password_hash, is_admin, is_active, require_password_change, license_tier, created_at, updated_at)
                    VALUES (?, ?, ?, '', '', '', NULL, ?, ?, ?, 1, 0, ?, ?, ?)
                """
                if USE_POSTGRES:
                    sql += " ON CONFLICT (username) DO NOTHING"
                conn.execute(
                    sql,
                    (
                        username,
                        username,
                        "",
                        salt,
                        pw_hash,
                        1 if not admin_assigned else 0,
                        DEFAULT_LICENSE_TIER,
                        now,
                        now,
                    ),
                )
                admin_assigned = True
            except Exception:
                continue


init_db()

import_legacy_users()


__all__ = [
    "DEFAULT_LICENSE_TIER",
    "LICENSE_TIERS",
    "get_license_monthly_limit",
    "normalize_license_tier",
    "create_company",
    "create_user",
    "disable_user",
    "enable_user",
    "get_company_by_id",
    "get_company_by_name",
    "get_user_by_id",
    "get_user_by_username",
    "hash_password_hex",
    "init_db",
    "list_companies",
    "list_users",
    "set_password",
    "update_company",
    "update_user",
    "verify_credentials",
]




