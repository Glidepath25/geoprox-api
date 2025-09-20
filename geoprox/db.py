from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

APP_ENV = (os.environ.get("APP_ENV") or os.environ.get("GEOPROX_ENV") or "development").strip().lower()
ALLOW_SQLITE = os.environ.get("ALLOW_SQLITE", "").strip().lower() in {"1", "true", "yes"}

if not os.environ.get("DB_HOST") and APP_ENV in {"production", "staging"} and not ALLOW_SQLITE:
    raise RuntimeError(
        "DB_HOST is required when APP_ENV is set to production or staging. "
        "Set DB_HOST/DB_* secrets or explicitly opt into SQLite with ALLOW_SQLITE=1 for temporary use."
    )

USE_POSTGRES = bool(os.environ.get("DB_HOST"))

if USE_POSTGRES:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor

    _required = ["DB_HOST", "DB_USER", "DB_PASSWORD"]
    _missing = [name for name in _required if not os.environ.get(name)]
    if _missing:
        missing = ', '.join(sorted(_missing))
        raise RuntimeError(f'PostgreSQL backend enabled but missing environment variables: {missing}')

    _CONFIG = {
        "host": os.environ["DB_HOST"],
        "dbname": os.environ.get("DB_NAME", "geoprox"),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "port": int(os.environ.get("DB_PORT", "5432")),
        "sslmode": os.environ.get("DB_SSLMODE", "require"),
    }
    _POOL = pool.SimpleConnectionPool(1, int(os.environ.get("DB_POOL_MAX", "10")), **_CONFIG)

    def adapt_sql(sql: str) -> str:
        cleaned = sql.strip().rstrip(";")
        return cleaned.replace("?", "%s")

    class PostgresCursor:
        def __init__(self, cursor: "psycopg2.extensions.cursor", prefetched: Optional[dict] = None) -> None:
            self._cursor = cursor
            self._prefetched = prefetched
            self.lastrowid = None
            if prefetched and "id" in prefetched:
                self.lastrowid = prefetched["id"]

        def fetchone(self):
            if self._prefetched is not None:
                row = self._prefetched
                self._prefetched = None
                return row
            return self._cursor.fetchone()

        def fetchall(self):
            rows = []
            if self._prefetched is not None:
                rows.append(self._prefetched)
                self._prefetched = None
            rows.extend(self._cursor.fetchall())
            return rows

        def close(self) -> None:
            self._cursor.close()

    class PostgresConnection:
        def __init__(self, raw_conn: "psycopg2.extensions.connection") -> None:
            self._raw = raw_conn
            self._returned = False

        def __enter__(self) -> "PostgresConnection":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            try:
                if exc_type:
                    self._raw.rollback()
                else:
                    self._raw.commit()
            finally:
                self.close()

        def close(self) -> None:
            if not self._returned:
                _POOL.putconn(self._raw)
                self._returned = True

        def execute(self, sql: str, params: tuple = ()):  # type: ignore[override]
            sql_text = adapt_sql(sql)
            sql_upper = sql_text.lstrip().upper()
            add_returning = sql_upper.startswith("INSERT") and "RETURNING" not in sql_upper and "ON CONFLICT" not in sql_upper
            if add_returning:
                sql_text = f"{sql_text} RETURNING id"
            cursor = self._raw.cursor(cursor_factory=RealDictCursor)
            cursor.execute(sql_text, params)
            prefetched = None
            if add_returning:
                prefetched = cursor.fetchone() or {}
            return PostgresCursor(cursor, prefetched)

        def cursor(self):
            return self._raw.cursor(cursor_factory=RealDictCursor)

        def commit(self) -> None:
            self._raw.commit()

        def rollback(self) -> None:
            self._raw.rollback()

    @contextmanager
    def get_postgres_conn() -> Iterator[PostgresConnection]:
        raw = _POOL.getconn()
        conn = PostgresConnection(raw)
        try:
            yield conn
        finally:
            conn.close()
else:
    def adapt_sql(sql: str) -> str:
        return sql

    @contextmanager
    def get_postgres_conn():  # type: ignore
        raise RuntimeError("PostgreSQL connection requested but DB_HOST is not set")
