"""Durable, owner-scoped report jobs on the application's existing database."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from geoprox import history_store

# A crashed request can be retried on any instance after this lease expires.
# Normal report rendering takes seconds; ten minutes allows tile-service delays.
LEASE_SECONDS = 600


def init_db() -> None:
    with history_store._get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_report_jobs (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                history_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                lease_until BIGINT NOT NULL DEFAULT 0,
                claim_token TEXT,
                created_at BIGINT NOT NULL
            )
        """)


def create_job(*, job_id: str, username: str, history_id: int, result: dict, context: dict) -> None:
    with history_store._get_conn() as conn:
        conn.execute("""
            INSERT INTO search_report_jobs
                (id, username, history_id, status, result_json, context_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (job_id, username, history_id, "pending", json.dumps(result), json.dumps(context), int(time.time())))


def get_job(job_id: str, username: str) -> Optional[Dict[str, Any]]:
    with history_store._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM search_report_jobs WHERE id = ? AND username = ?", (job_id, username)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data.pop("result_json"))
    data["context"] = json.loads(data.pop("context_json"))
    return data


def claim_job(job_id: str, username: str) -> Optional[str]:
    token, now = uuid4().hex, int(time.time())
    with history_store._get_conn() as conn:
        row = conn.execute("""
            UPDATE search_report_jobs SET status = 'processing', lease_until = ?, claim_token = ?
            WHERE id = ? AND username = ? AND
                (status IN ('pending', 'error') OR (status = 'processing' AND lease_until <= ?))
            RETURNING id
        """, (now + LEASE_SECONDS, token, job_id, username, now)).fetchone()
    return token if row else None


def finish_job(job_id: str, username: str, token: str, *, result: dict, status: str) -> bool:
    with history_store._get_conn() as conn:
        row = conn.execute("""
            UPDATE search_report_jobs SET status = ?, result_json = ?, lease_until = 0, claim_token = NULL
            WHERE id = ? AND username = ? AND claim_token = ?
            RETURNING history_id
        """, (status, json.dumps(result), job_id, username, token)).fetchone()
        if row and status == "ready":
            # Publish the completed result and its history links atomically.
            history_store.update_search_result(
                search_id=row["history_id"], username=username, result=result, connection=conn,
            )
    return bool(row)


init_db()
