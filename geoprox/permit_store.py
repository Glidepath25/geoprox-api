from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from geoprox.db import USE_POSTGRES, get_postgres_conn

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "permit_records.db"


@contextmanager
def _sqlite_conn():
    conn = sqlite3.connect(_DB_PATH)
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


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def init_db() -> None:
    if USE_POSTGRES:
        with _get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS permit_records (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    permit_ref TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    location_display TEXT,
                    location_lat DOUBLE PRECISION,
                    location_lon DOUBLE PRECISION,
                    radius_m INTEGER,
                    desktop_status TEXT NOT NULL,
                    desktop_outcome TEXT,
                    desktop_summary JSONB,
                    site_status TEXT NOT NULL,
                    site_outcome TEXT,
                    site_notes TEXT,
                    site_payload JSONB,
                    search_result JSONB,
                    UNIQUE (username, permit_ref)
                )
                """
            )
        return

    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS permit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                permit_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                location_display TEXT,
                location_lat REAL,
                location_lon REAL,
                radius_m INTEGER,
                desktop_status TEXT NOT NULL,
                desktop_outcome TEXT,
                desktop_summary TEXT,
                site_status TEXT NOT NULL,
                site_outcome TEXT,
                site_notes TEXT,
                site_payload TEXT,
                search_result TEXT,
                UNIQUE (username, permit_ref)
            )
            """
        )
        conn.commit()


def _row_to_record(row: Any) -> Dict[str, Any]:
    data = dict(row)
    for key in ("desktop_summary", "site_payload", "search_result"):
        value = data.get(key)
        if value and isinstance(value, str):
            try:
                data[key] = json.loads(value)
            except json.JSONDecodeError:
                data[key] = None
    return {
        "id": data.get("id"),
        "permit_ref": data.get("permit_ref"),
        "username": data.get("username"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "location": {
            "display": data.get("location_display"),
            "lat": data.get("location_lat"),
            "lon": data.get("location_lon"),
            "radius_m": data.get("radius_m"),
        },
        "desktop": {
            "status": data.get("desktop_status"),
            "outcome": data.get("desktop_outcome"),
            "summary": data.get("desktop_summary"),
        },
        "site": {
            "status": data.get("site_status"),
            "outcome": data.get("site_outcome"),
            "notes": data.get("site_notes"),
            "payload": data.get("site_payload"),
        },
        "search_result": data.get("search_result"),
    }


def get_permit(username: str, permit_ref: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM permit_records WHERE username = ? AND permit_ref = ?",
            (username, permit_ref),
        ).fetchone()
    if not row:
        return None
    return _row_to_record(row)


def save_permit(
    *,
    username: str,
    permit_ref: str,
    search_result: Dict[str, Any],
) -> Dict[str, Any]:
    summary = search_result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    center_display = summary.get("center")
    coords = summary.get("center_coords")
    if not isinstance(coords, dict):
        coords = {}
    location_lat = _safe_float(coords.get("lat"))
    location_lon = _safe_float(coords.get("lon"))
    radius_source = summary.get("radius")
    if radius_source is None:
        radius_source = search_result.get("radius_m")
    radius_m = _safe_int(radius_source)
    outcome = summary.get("outcome")

    now = _now()
    result_json = json.dumps(search_result, ensure_ascii=False)
    summary_json = json.dumps(summary, ensure_ascii=False) if summary else None

    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM permit_records WHERE username = ? AND permit_ref = ?",
            (username, permit_ref),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE permit_records
                SET updated_at = ?,
                    location_display = ?,
                    location_lat = ?,
                    location_lon = ?,
                    radius_m = ?,
                    desktop_status = ?,
                    desktop_outcome = ?,
                    desktop_summary = ?,
                    search_result = ?
                WHERE id = ?
                """,
                (
                    now,
                    center_display,
                    location_lat,
                    location_lon,
                    radius_m,
                    "Completed",
                    outcome,
                    summary_json,
                    result_json,
                    existing["id"] if isinstance(existing, sqlite3.Row) else existing["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO permit_records (
                    username,
                    permit_ref,
                    created_at,
                    updated_at,
                    location_display,
                    location_lat,
                    location_lon,
                    radius_m,
                    desktop_status,
                    desktop_outcome,
                    desktop_summary,
                    site_status,
                    site_outcome,
                    site_notes,
                    site_payload,
                    search_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    permit_ref,
                    now,
                    now,
                    center_display,
                    location_lat,
                    location_lon,
                    radius_m,
                    "Completed",
                    outcome,
                    summary_json,
                    "Not started",
                    None,
                    None,
                    None,
                    result_json,
                ),
            )
    return get_permit(username, permit_ref) or {}


def update_site_assessment(
    *,
    username: str,
    permit_ref: str,
    status: str,
    outcome: Optional[str],
    notes: Optional[str],
    payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    existing = get_permit(username, permit_ref)
    if not existing:
        return None

    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    now = _now()

    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE permit_records
            SET updated_at = ?,
                site_status = ?,
                site_outcome = ?,
                site_notes = ?,
                site_payload = ?
            WHERE username = ? AND permit_ref = ?
            """,
            (
                now,
                status,
                outcome,
                notes,
                payload_json,
                username,
                permit_ref,
            ),
        )
    return get_permit(username, permit_ref)


init_db()

__all__ = [
    "get_permit",
    "save_permit",
    "update_site_assessment",
]

