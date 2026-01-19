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

USER_TYPES: Dict[str, str] = {
    "desktop": "Desktop user",
    "site": "Site user",
}
DEFAULT_USER_TYPE = "desktop"

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
# User type helpers
# ---------------------------------------------------------------------------



def normalize_user_type(user_type: Optional[str]) -> str:
    if not user_type:
        return DEFAULT_USER_TYPE
    key = str(user_type).strip().lower()
    if key not in USER_TYPES:
        raise ValueError(f"Unknown user type '{user_type}'")
    return key


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
                    is_company_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    require_password_change BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id)")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_company_admin BOOLEAN NOT NULL DEFAULT FALSE")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_type TEXT NOT NULL DEFAULT 'desktop'")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token TEXT")
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
                is_company_admin INTEGER NOT NULL DEFAULT 0,
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
    if "is_company_admin" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_company_admin INTEGER NOT NULL DEFAULT 0")
    if "user_type" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN user_type TEXT NOT NULL DEFAULT 'desktop'")
    if "session_token" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN session_token TEXT")


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
        "user_type": row["user_type"] if "user_type" in row.keys() else DEFAULT_USER_TYPE,
        "license_tier": row["license_tier"] if "license_tier" in row.keys() else DEFAULT_LICENSE_TIER,
        "salt": row["salt"],
        "password_hash": row["password_hash"],
        "is_admin": bool(row["is_admin"]),
        "is_company_admin": bool(row["is_company_admin"]) if "is_company_admin" in row.keys() else False,
        "is_active": bool(row["is_active"]),
        "require_password_change": bool(row["require_password_change"]) if "require_password_change" in row.keys() else False,
        "session_token": row["session_token"] if "session_token" in row.keys() else None,
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


def count_users_for_company(
    company_name: str,
    *,
    license_tier: Optional[str] = None,
    include_inactive: bool = True,
) -> int:
    """
    Count users linked to a company by name (case-insensitive).
    Optionally filter by license tier and active status.
    """
    cleaned = (company_name or "").strip()
    if not cleaned:
        return 0
    company_filters: List[str] = []
    params: List[Any] = []
    existing_company = get_company_by_name(cleaned)
    if existing_company and existing_company.get("id") is not None:
        company_filters.append("company_id = ?")
        params.append(existing_company["id"])
    company_filters.append("lower(company) = lower(?)")
    params.append(cleaned)
    conditions = [f"({' OR '.join(company_filters)})"]
    if license_tier:
        normalized_tier = normalize_license_tier(license_tier)
        conditions.append("license_tier = ?")
        params.append(normalized_tier)
    if not include_inactive:
        conditions.append("is_active = ?")
        params.append(True)
    where_clause = " AND ".join(conditions)
    sql = f"SELECT COUNT(*) AS total FROM users WHERE {where_clause}"
    with _get_conn() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return int(row["total"]) if row and row.get("total") is not None else 0


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
        if row is None:
            log.warning("debug get_user_by_username(%s) -> None", username)
        else:
            try:
                raw = dict(row)
            except Exception:
                raw = row
            log.warning("debug get_user_by_username(%s) raw=%s", username, raw)
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
    user_type: str = DEFAULT_USER_TYPE,
    is_admin: bool = False,
    is_company_admin: bool = False,
    is_active: bool = True,
    require_password_change: bool = True,
    license_tier: str = DEFAULT_LICENSE_TIER,
) -> Dict[str, Any]:
    resolved_company = _resolve_company(company_id, company)
    salt = secrets.token_bytes(16)
    password_hash = hash_password_hex(password, salt=salt)
    now = _now()
    normalized_tier = normalize_license_tier(license_tier)
    normalized_user_type = normalize_user_type(user_type)
    sql = """
        INSERT INTO users (username, name, email, company, company_number, phone, company_id, salt, password_hash, is_admin, is_company_admin, is_active, require_password_change, license_tier, user_type, session_token, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        _coerce_bool(is_company_admin),
        _coerce_bool(is_active),
        _coerce_bool(require_password_change),
        normalized_tier,
        normalized_user_type,
        None,
        now,
        now,
    )
    if USE_POSTGRES:
        sql += " RETURNING id, username, name, email, company, company_number, phone, company_id, license_tier, user_type, session_token, salt, password_hash, is_admin, is_company_admin, is_active, require_password_change, created_at, updated_at"
        created_row: Optional[Dict[str, Any]] = None
        with _get_conn() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            _debug_conn("create_user", conn)
            if row:
                try:
                    snapshot = conn.execute("SELECT id, username, is_active, company_id, created_at, updated_at FROM users WHERE username = ?", (username,)).fetchone()
                    snapshot_data = dict(snapshot) if snapshot else None
                    log.warning("debug create_user immediate username=%s -> %s", username, snapshot_data)
                except Exception:
                    log.exception("debug create_user immediate lookup failed for %s", username)
                created_row = _row_to_dict(row)
        if not created_row:
            raise RuntimeError("Failed to create user record")
        try:
            persisted = get_user_by_username(username)
            log.warning("debug create_user post_commit username=%s -> %s", username, persisted)
        except Exception:
            log.exception("debug create_user post-commit lookup failed for %s", username)
        return created_row
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



def delete_user(user_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def delete_company(company_id: int) -> None:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users WHERE company_id = ?", (company_id,)).fetchone()
        if row and int(row["total"]) > 0:
            raise ValueError("Cannot delete company with existing users. Remove or move users first.")
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))


def update_user(user_id: int, **fields: Any) -> None:
    allowed = {
        "name",
        "email",
        "company",
        "company_number",
        "phone",
        "company_id",
        "user_type",
        "is_admin",
        "is_company_admin",
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
        elif key == "user_type":
            if value is None:
                continue
            updates[key] = normalize_user_type(value)
        elif key in {"is_admin", "is_company_admin", "is_active", "require_password_change"}:
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


def set_session_token(user_id: int, token: Optional[str] = None) -> str:
    value = token or secrets.token_urlsafe(32)
    now = _now()
    with _get_conn() as conn:
        conn.execute("UPDATE users SET session_token = ?, updated_at = ? WHERE id = ?", (value, now, user_id))
    return value


def clear_session_token(username: str, *, expected_token: Optional[str] = None) -> None:
    now = _now()
    with _get_conn() as conn:
        if expected_token is None:
            conn.execute("UPDATE users SET session_token = NULL, updated_at = ? WHERE username = ?", (now, username))
        else:
            conn.execute("UPDATE users SET session_token = NULL, updated_at = ? WHERE username = ? AND session_token = ?", (now, username, expected_token))



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
                    INSERT INTO users (username, name, email, company, company_number, phone, company_id, salt, password_hash, is_admin, is_company_admin, is_active, require_password_change, license_tier, created_at, updated_at)
                    VALUES (?, ?, ?, '', '', '', NULL, ?, ?, ?, 0, 1, 0, ?, ?, ?)
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
    "DEFAULT_USER_TYPE",
    "USER_TYPES",
    "get_license_monthly_limit",
    "normalize_license_tier",
    "normalize_user_type",
    "count_users_for_company",
    "create_company",
    "create_user",
    "delete_user",
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
    "set_session_token",
    "clear_session_token",
    "update_company",
    "update_user",
    "verify_credentials",
    "delete_company",
]
