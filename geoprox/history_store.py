from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "search_history.db"




def _month_bounds(reference: Optional[datetime] = None) -> Tuple[str, str]:
    if reference is None:
        reference = datetime.utcnow()
    start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return _to_iso(start), _to_iso(end)


def _to_iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds") + "Z"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                location TEXT NOT NULL,
                radius_m INTEGER NOT NULL,
                outcome TEXT,
                permit TEXT,
                pdf_path TEXT,
                map_path TEXT,
                result_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_search_history_username_timestamp ON search_history(username, timestamp)")
        conn.commit()


def record_search(
    *,
    username: str,
    timestamp: str,
    location: str,
    radius_m: int,
    outcome: Optional[str],
    permit: Optional[str],
    pdf_path: Optional[str],
    map_path: Optional[str],
    result: Optional[Dict[str, Any]] = None,
) -> None:
    payload = json.dumps(result or {}, ensure_ascii=False)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO search_history (username, timestamp, location, radius_m, outcome, permit, pdf_path, map_path, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                timestamp,
                location,
                int(radius_m),
                outcome,
                permit,
                pdf_path,
                map_path,
                payload,
            ),
        )
        conn.commit()


def get_history(username: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
    query = "SELECT username, timestamp, location, radius_m, outcome, permit, pdf_path, map_path FROM search_history WHERE username = ? ORDER BY timestamp DESC"
    if limit is not None:
        query += " LIMIT ?"
        params: Iterable[Any] = (username, limit)
    else:
        params = (username,)
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_user_monthly_search_counts(reference: Optional[datetime] = None) -> Dict[str, int]:
    start, end = _month_bounds(reference)
    with _get_conn() as conn:
        rows = conn.execute("SELECT username, COUNT(*) AS total FROM search_history WHERE timestamp >= ? AND timestamp < ? GROUP BY username", (start, end)).fetchall()
    return {row['username']: int(row['total']) for row in rows}



def get_monthly_search_count(username: str, reference: Optional[datetime] = None) -> int:
    start, end = _month_bounds(reference)
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM search_history WHERE username = ? AND timestamp >= ? AND timestamp < ?", (username, start, end)).fetchone()
    return int(row['total']) if row else 0


def get_user_search_counts() -> Dict[str, int]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT username, COUNT(*) AS total FROM search_history GROUP BY username").fetchall()
    return {row['username']: int(row['total']) for row in rows}


init_db()

