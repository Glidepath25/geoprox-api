from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from geoprox.db import USE_POSTGRES, get_postgres_conn

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
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
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
                created_at TEXT NOT NULL
            )
            """
        )


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
                    (category, name, latitude, longitude, address, notes, submitted_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, category, name, latitude, longitude, address, notes, submitted_by, created_at
                """,
                (category, name, latitude, longitude, address, notes, submitted_by, created_at),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else {}

    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO unidentified_reports
                (category, name, latitude, longitude, address, notes, submitted_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (category, name, latitude, longitude, address, notes, submitted_by, created_at),
        )
        report_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at FROM unidentified_reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        return _row_to_dict(row) if row else {}


def list_reports(*, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        if USE_POSTGRES:
            sql = "SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at FROM unidentified_reports ORDER BY created_at DESC"
            params: Iterable[Any] = ()
            if limit is not None:
                sql += " LIMIT %s"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = "SELECT id, category, name, latitude, longitude, address, notes, submitted_by, created_at FROM unidentified_reports ORDER BY datetime(created_at) DESC"
            params = ()
            if limit is not None:
                sql += " LIMIT ?"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


init_db()

__all__ = ["create_report", "list_reports", "init_db"]
