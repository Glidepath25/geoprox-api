from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

from geoprox.db import USE_POSTGRES, get_postgres_conn
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import boto3
except Exception:
    boto3 = None

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "search_history.db"





_S3_BUCKET = os.environ.get("GEOPROX_BUCKET", "").strip()
_S3_CLIENT = None


def _get_s3_client():
    global _S3_CLIENT
    if not _S3_BUCKET or boto3 is None:
        return None
    if _S3_CLIENT is None:
        try:
            _S3_CLIENT = boto3.client("s3")
        except Exception:
            _S3_CLIENT = None
    return _S3_CLIENT


def _normalize_artifact(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    trimmed = str(value).strip()
    if not trimmed:
        return None
    lowered = trimmed.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return trimmed
    if trimmed.startswith("/"):
        return trimmed
    name = Path(trimmed).name
    return f"/artifacts/{name}"


def _signed_url(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    client = _get_s3_client()
    if not client:
        return None
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": _S3_BUCKET, "Key": key},
            ExpiresIn=86400,
        )
    except Exception:
        return None


def _resolve_links(data: Dict[str, Any], artifacts: Dict[str, Any]) -> None:
    pdf_link = _signed_url(artifacts.get("pdf_key"))
    if not pdf_link:
        pdf_link = artifacts.get("pdf_url") or artifacts.get("pdf_download_url")
    if not pdf_link:
        pdf_link = data.get("pdf_path")
    data["pdf_path"] = _normalize_artifact(pdf_link)

    map_link = _signed_url(artifacts.get("map_key"))
    if not map_link:
        map_link = (
            artifacts.get("map_url")
            or artifacts.get("map_embed_url")
            or artifacts.get("map_html_url")
        )
    if not map_link:
        map_link = data.get("map_path")
    data["map_path"] = _normalize_artifact(map_link)

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


def init_db() -> None:
    if USE_POSTGRES:
        with _get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_history (
                    id SERIAL PRIMARY KEY,
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_history_username_timestamp ON search_history(username, timestamp)"
            )
        return

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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_history_username_timestamp ON search_history(username, timestamp)"
        )
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



def delete_history(username: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM search_history WHERE username = ?", (username,))


def get_history(username: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
    query = (
        "SELECT username, timestamp, location, radius_m, outcome, permit, pdf_path, map_path, result_json "
        "FROM search_history WHERE username = ? ORDER BY timestamp DESC"
    )
    if limit is not None:
        query += " LIMIT ?"
        params: Iterable[Any] = (username, limit)
    else:
        params = (username,)
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        payload = data.pop("result_json", None)
        artifacts: Dict[str, Any] = {}
        if payload:
            try:
                parsed = json.loads(payload)
                artifacts = parsed.get("artifacts") or {}
            except json.JSONDecodeError:
                artifacts = {}
        _resolve_links(data, artifacts)
        items.append(data)
    return items


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

