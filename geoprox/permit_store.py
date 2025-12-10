from __future__ import annotations



import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(permit_records)")}
        if 'sample_status' not in cols:
            conn.execute("ALTER TABLE permit_records ADD COLUMN sample_status TEXT DEFAULT 'Not required'")
        if 'sample_outcome' not in cols:
            conn.execute("ALTER TABLE permit_records ADD COLUMN sample_outcome TEXT")
        if 'sample_notes' not in cols:
            conn.execute("ALTER TABLE permit_records ADD COLUMN sample_notes TEXT")
        if 'sample_payload' not in cols:
            conn.execute("ALTER TABLE permit_records ADD COLUMN sample_payload TEXT")
        conn.execute("UPDATE permit_records SET sample_status = COALESCE(sample_status, 'Not required')")
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

def _normalize_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
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
                    sample_status TEXT NOT NULL DEFAULT 'Not required',
                    sample_outcome TEXT,
                    sample_notes TEXT,
                    sample_payload JSONB,
                    search_result JSONB,
                    UNIQUE (username, permit_ref)
                )
                """
            )
            conn.execute("ALTER TABLE permit_records ADD COLUMN IF NOT EXISTS sample_status TEXT NOT NULL DEFAULT 'Not required'")
            conn.execute("ALTER TABLE permit_records ADD COLUMN IF NOT EXISTS sample_outcome TEXT")
            conn.execute("ALTER TABLE permit_records ADD COLUMN IF NOT EXISTS sample_notes TEXT")
            conn.execute("ALTER TABLE permit_records ADD COLUMN IF NOT EXISTS sample_payload JSONB")
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
                sample_status TEXT NOT NULL DEFAULT 'Not required',
                sample_outcome TEXT,
                sample_notes TEXT,
                sample_payload TEXT,
                search_result TEXT,
                UNIQUE (username, permit_ref)
            )
            """
        )
        conn.commit()


def _row_to_record(row: Any) -> Dict[str, Any]:
    data = dict(row)
    for key in ("desktop_summary", "site_payload", "sample_payload", "search_result"):
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
        "sample": {
            "status": data.get("sample_status"),
            "outcome": data.get("sample_outcome"),
            "notes": data.get("sample_notes"),
            "payload": data.get("sample_payload"),
        },
        "search_result": data.get("search_result"),
    }



def get_permit(
    username: str,
    permit_ref: str,
    *,
    owner_username: Optional[str] = None,
    allowed_usernames: Optional[Iterable[str]] = None,
) -> Optional[Dict[str, Any]]:
    candidates: List[str] = []

    if owner_username:
        candidates = [owner_username]
    elif allowed_usernames is not None:
        seen: Set[str] = set()
        unique: List[str] = []
        for value in allowed_usernames:
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        candidates = unique
    else:
        candidates = [username]

    if not candidates:
        return None

    if USE_POSTGRES:
        placeholders = ", ".join(["%s"] * len(candidates))
        sql = f'''
            SELECT *
            FROM permit_records
            WHERE permit_ref = %s AND username IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
        '''
    else:
        placeholders = ", ".join(["?"] * len(candidates))
        sql = f'''
            SELECT *
            FROM permit_records
            WHERE permit_ref = ? AND username IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
        '''

    params: List[Any] = [permit_ref, *candidates]

    with _get_conn() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
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
                    sample_status,
                    sample_outcome,
                    sample_notes,
                    sample_payload,
                    search_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    "Not required",
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
    allowed_usernames: Optional[Iterable[str]] = None,
) -> Optional[Dict[str, Any]]:
    existing = get_permit(username, permit_ref, allowed_usernames=allowed_usernames)
    if not existing:
        return None

    merged_payload: Dict[str, Any] = {}
    existing_payload = existing.get("site", {}).get("payload")
    if isinstance(existing_payload, dict):
        merged_payload = dict(existing_payload)
    if isinstance(payload, dict):
        merged_payload.update(payload)

    payload_json = json.dumps(merged_payload, ensure_ascii=False) if merged_payload else None
    now = _now()
    owner_username = existing.get("username") or username

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
                owner_username,
                permit_ref,
            ),
        )
    return get_permit(username, permit_ref, allowed_usernames=allowed_usernames)





def update_sample_assessment(
    *,
    username: str,
    permit_ref: str,
    status: str,
    outcome: Optional[str],
    notes: Optional[str],
    payload: Optional[Dict[str, Any]],
    allowed_usernames: Optional[Iterable[str]] = None,
) -> Optional[Dict[str, Any]]:
    existing = get_permit(username, permit_ref, allowed_usernames=allowed_usernames)
    if not existing:
        return None

    merged_payload: Dict[str, Any] = {}
    existing_payload = existing.get("sample", {}).get("payload")
    if isinstance(existing_payload, dict):
        merged_payload = dict(existing_payload)
    if isinstance(payload, dict):
        merged_payload.update(payload)

    payload_json = json.dumps(merged_payload, ensure_ascii=False) if merged_payload else None
    now = _now()
    owner_username = existing.get("username") or username

    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE permit_records
            SET updated_at = ?,
                sample_status = ?,
                sample_outcome = ?,
                sample_notes = ?,
                sample_payload = ?
            WHERE username = ? AND permit_ref = ?
            """,
            (
                now,
                status,
                outcome,
                notes,
                payload_json,
                owner_username,
                permit_ref,
            ),
        )
    return get_permit(username, permit_ref, allowed_usernames=allowed_usernames)



def search_permits(
    username: str,
    query: str = "",
    limit: int = 20,
    *,
    visible_usernames: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    limit = max(1, int(limit or 20))

    scope: List[str] = []
    seen: Set[str] = set()

    def _add_user(value: Optional[str]) -> None:
        if not value:
            return
        if value in seen:
            return
        seen.add(value)
        scope.append(value)

    _add_user(username)
    if visible_usernames is not None:
        for value in visible_usernames:
            _add_user(value)

    if not scope:
        return []

    pattern = f"%{query}%"
    pattern_lower = f"%{query.lower()}%" if query else "%"

    with _get_conn() as conn:
        if USE_POSTGRES:
            user_placeholders = ", ".join(["%s"] * len(scope))
            sql = f'''
                SELECT username, permit_ref, created_at, updated_at, desktop_status, desktop_outcome, site_status, site_outcome, site_payload, sample_status, sample_outcome, sample_payload
                FROM permit_records
                WHERE username IN ({user_placeholders})
            '''
            params: List[Any] = list(scope)
            if query:
                sql += " AND permit_ref ILIKE %s"
                params.append(pattern)
            sql += " ORDER BY updated_at DESC LIMIT %s"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
        else:
            user_placeholders = ", ".join(["?"] * len(scope))
            sql = f'''
                SELECT username, permit_ref, created_at, updated_at, desktop_status, desktop_outcome, site_status, site_outcome, site_payload, sample_status, sample_outcome, sample_payload
                FROM permit_records
                WHERE username IN ({user_placeholders})
            '''
            params: List[Any] = list(scope)
            if query:
                sql += " AND LOWER(permit_ref) LIKE ?"
                params.append(pattern_lower)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()

    def _parse_site_payload(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {}

    def _parse_sample_payload(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {}

    def _parse_outcome_parts(outcome_text: Any) -> Tuple[Optional[str], Optional[str]]:
        if not isinstance(outcome_text, str):
            return None, None
        bituminous: Optional[str] = None
        sub_base: Optional[str] = None
        for segment in outcome_text.split("|"):
            part = segment.strip()
            lowered = part.lower()
            if lowered.startswith("bituminous") and ":" in part:
                bituminous = part.split(":", 1)[1].strip() or None
            if lowered.startswith("sub-base") and ":" in part:
                sub_base = part.split(":", 1)[1].strip() or None
        return bituminous, sub_base

    results: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        payload = _parse_site_payload(record.get("site_payload"))
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        form = payload.get("form") if isinstance(payload.get("form"), dict) else {}
        sample_payload = _parse_sample_payload(record.get("sample_payload"))
        sample_form = sample_payload.get("form") if isinstance(sample_payload.get("form"), dict) else {}
        sample_summary = sample_payload.get("summary") if isinstance(sample_payload.get("summary"), dict) else {}

        site_bituminous = (summary.get("bituminous") or form.get("result_bituminous") or "").strip() or None
        site_sub_base = (summary.get("sub_base") or form.get("result_sub_base") or "").strip() or None

        if not site_bituminous or not site_sub_base:
            parsed_bituminous, parsed_sub_base = _parse_outcome_parts(record.get("site_outcome"))
            site_bituminous = site_bituminous or parsed_bituminous
            site_sub_base = site_sub_base or parsed_sub_base

        site_date = form.get("assessment_date") if isinstance(form.get("assessment_date"), str) else None
        if site_date:
            site_date = site_date.strip() or None
        if not site_date and record.get("site_status") and record.get("site_status") != "Not started":
            site_date = _normalize_timestamp(record.get("updated_at"))

        sample_date = None
        if isinstance(sample_form.get("sampling_date"), str):
            sample_date = sample_form.get("sampling_date").strip() or None
        if not sample_date and sample_summary.get("reported_at"):
            sample_date = str(sample_summary.get("reported_at"))
        if not sample_date and isinstance(record.get("sample_status"), str) and record.get("sample_status").lower() == "complete":
            sample_date = _normalize_timestamp(record.get("updated_at"))

        owner_username = record.get("username")

        result_item = {
            "permit_ref": record.get("permit_ref"),
            "owner_username": owner_username,
            "username": owner_username,
            "created_at": _normalize_timestamp(record.get("created_at")),
            "updated_at": _normalize_timestamp(record.get("updated_at")),
            "desktop_status": record.get("desktop_status"),
            "desktop_outcome": record.get("desktop_outcome"),
            "desktop_date": _normalize_timestamp(record.get("created_at")),
            "site_status": record.get("site_status"),
            "site_outcome": record.get("site_outcome"),
            "site_bituminous": site_bituminous,
            "site_sub_base": site_sub_base,
            "site_date": site_date,
            "sample_status": record.get("sample_status"),
            "sample_outcome": record.get("sample_outcome"),
            "sample_date": sample_date,
        }
        results.append(result_item)
    return results


init_db()

__all__ = ["get_permit", "save_permit", "update_site_assessment", "update_sample_assessment", "search_permits"]


def count_completed_sites_between(start_iso: str, end_iso: str) -> int:
    if USE_POSTGRES:
        sql = """
            SELECT COUNT(*) AS total
            FROM permit_records
            WHERE site_status = 'Completed' AND updated_at >= %s AND updated_at < %s
        """
    else:
        sql = """
            SELECT COUNT(*) AS total
            FROM permit_records
            WHERE site_status = 'Completed' AND updated_at >= ? AND updated_at < ?
        """
    with _get_conn() as conn:
        row = conn.execute(sql, (start_iso, end_iso)).fetchone()
    return int(row["total"]) if row else 0

