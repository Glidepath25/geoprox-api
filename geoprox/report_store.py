from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from geoprox.db import USE_POSTGRES, get_postgres_conn

log = logging.getLogger("uvicorn.error")

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "unidentified_reports.db"


@contextmanager
def _sqlite_conn():
    conn = sqlite3.connect(str(_DB_PATH))
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


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def init_db() -> None:
    if USE_POSTGRES:
        with _get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS unidentified_reports (
                    id SERIAL PRIMARY KEY,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    address TEXT,
                    notes TEXT,
                    submitted_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    verified_by TEXT,
                    verified_at TIMESTAMPTZ,
                    search_category TEXT
                )
                """
            )
        _ensure_columns()
        return

    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS unidentified_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                address TEXT,
                notes TEXT,
                submitted_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                verified_by TEXT,
                verified_at TEXT,
                search_category TEXT
            )
            """
        )
    _ensure_columns()


def _ensure_columns() -> None:
    """
    Ensure schema upgrades are applied for older databases.
    """
    if USE_POSTGRES:
        with _get_conn() as conn:
            try:
                conn.execute(
                    "ALTER TABLE unidentified_reports ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE"
                )
                conn.execute(
                    "ALTER TABLE unidentified_reports ADD COLUMN IF NOT EXISTS verified_by TEXT"
                )
                conn.execute(
                    "ALTER TABLE unidentified_reports ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ"
                )
                conn.execute(
                    "ALTER TABLE unidentified_reports ADD COLUMN IF NOT EXISTS search_category TEXT"
                )
            except Exception:
                log.exception("Failed to ensure unidentified_reports columns (postgres)")
        return

    with _get_conn() as conn:
        try:
            existing_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(unidentified_reports)").fetchall()
                if isinstance(row, sqlite3.Row)
            }
        except Exception:
            log.exception("Unable to inspect unidentified_reports schema (sqlite)")
            existing_cols = set()
        column_defs = {
            "is_verified": "INTEGER NOT NULL DEFAULT 0",
            "verified_by": "TEXT",
            "verified_at": "TEXT",
            "search_category": "TEXT",
        }
        for column, definition in column_defs.items():
            if column in existing_cols:
                continue
            try:
                conn.execute(f"ALTER TABLE unidentified_reports ADD COLUMN {column} {definition}")
            except Exception:
                log.exception("Failed to add column %s to unidentified_reports (sqlite)", column)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    data = dict(row)
    return {
        "id": data.get("id"),
        "category": data.get("category", ""),
        "name": data.get("name", ""),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "address": data.get("address", ""),
        "notes": data.get("notes", ""),
        "submitted_by": data.get("submitted_by", ""),
        "created_at": data.get("created_at"),
        "is_verified": bool(data.get("is_verified")) if data.get("is_verified") is not None else False,
        "verified_by": data.get("verified_by") or "",
        "verified_at": data.get("verified_at"),
        "search_category": data.get("search_category"),
    }


def create_report(
    *,
    category: str,
    name: str,
    latitude: Optional[float],
    longitude: Optional[float],
    address: str,
    notes: str,
    submitted_by: str,
) -> Dict[str, Any]:
    created_at = _now()
    if USE_POSTGRES:
        with _get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO unidentified_reports
                    (category, name, latitude, longitude, address, notes, submitted_by, created_at, is_verified, verified_by, verified_at, search_category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, category, name, latitude, longitude, address, notes, submitted_by, created_at, is_verified, verified_by, verified_at, search_category
                """,
                (
                    category,
                    name,
                    latitude,
                    longitude,
                    address,
                    notes,
                    submitted_by,
                    created_at,
                    False,
                    None,
                    None,
                    None,
                ),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else {}

    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO unidentified_reports
                (category, name, latitude, longitude, address, notes, submitted_by, created_at, is_verified, verified_by, verified_at, search_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                name,
                latitude,
                longitude,
                address,
                notes,
                submitted_by,
                created_at,
                0,
                None,
                None,
                None,
            ),
        )
        report_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at,
                   is_verified, verified_by, verified_at, search_category
            FROM unidentified_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
        return _row_to_dict(row) if row else {}


def list_reports(*, limit: Optional[int] = None, only_verified: bool = False) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        if USE_POSTGRES:
            sql = (
                "SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at, "
                "is_verified, verified_by, verified_at, search_category "
                "FROM unidentified_reports"
            )
            params: Iterable[Any] = ()
            conditions: List[str] = []
            if only_verified:
                conditions.append("is_verified = TRUE")
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY created_at DESC"
            if limit is not None:
                sql += " LIMIT %s"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = (
                "SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at, "
                "is_verified, verified_by, verified_at, search_category "
                "FROM unidentified_reports"
            )
            params: Iterable[Any] = ()
            conditions: List[str] = []
            if only_verified:
                conditions.append("is_verified = 1")
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY datetime(created_at) DESC"
            if limit is not None:
                sql += " LIMIT ?"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_verified_reports(*, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return list_reports(limit=limit, only_verified=True)


def get_report(report_id: int) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at,
                   is_verified, verified_by, verified_at, search_category
            FROM unidentified_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def verify_report(
    report_id: int,
    *,
    verified_by: str,
    search_category: str,
) -> Optional[Dict[str, Any]]:
    verified_at = _now()
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE unidentified_reports
            SET is_verified = ?, verified_by = ?, verified_at = ?, search_category = ?
            WHERE id = ?
            """,
            (
                True,
                verified_by,
                verified_at,
                search_category,
                report_id,
            ),
        )
        row = conn.execute(
            """
            SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at,
                   is_verified, verified_by, verified_at, search_category
            FROM unidentified_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


init_db()

__all__ = [
    "create_report",
    "get_report",
    "list_reports",
    "list_verified_reports",
    "verify_report",
    "init_db",
]
