"""Small SQLite-compatible persistence bridge backed by Supabase REST.

The application already has a large set of SQLite queries.  This bridge keeps
those queries intact while making Supabase the durable source of truth.  Each
request works on an in-memory SQLite snapshot and commits the complete set of
tables back to Supabase.  The app runs as a single web worker, which keeps this
simple and avoids partial writes across related records.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import requests


TABLES = (
    "users",
    "codes",
    "gifts",
    "user_gifts",
    "gift_upgrades",
    "upgrade_photos",
    "upgrade_models",
    "user_gift_upgrades",
    "marketplace",
    "auctions",
    "auction_bids",
)

DELETE_ORDER = tuple(reversed(TABLES))

LOCAL_SCHEMA = {
    "users": """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE, username TEXT, first_name TEXT,
            stars INTEGER DEFAULT 0, is_premium INTEGER DEFAULT 0,
            stars_spent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "codes": """
        CREATE TABLE IF NOT EXISTS codes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT, code TEXT UNIQUE, used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "gifts": """
        CREATE TABLE IF NOT EXISTS gifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, price INTEGER DEFAULT 0,
            description TEXT, emoji TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            image TEXT DEFAULT NULL, in_shop INTEGER DEFAULT 1,
            quantity INTEGER DEFAULT NULL, sold INTEGER DEFAULT 0
        )
    """,
    "user_gifts": """
        CREATE TABLE IF NOT EXISTS user_gifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, gift_id INTEGER,
            obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "gift_upgrades": """
        CREATE TABLE IF NOT EXISTS gift_upgrades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_id INTEGER NOT NULL, name TEXT NOT NULL,
            number_min INTEGER DEFAULT 1, number_max INTEGER DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            counter INTEGER DEFAULT 0
        )
    """,
    "upgrade_photos": """
        CREATE TABLE IF NOT EXISTS upgrade_photos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upgrade_id INTEGER NOT NULL, filename TEXT NOT NULL
        )
    """,
    "upgrade_models": """
        CREATE TABLE IF NOT EXISTS upgrade_models(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upgrade_id INTEGER NOT NULL, name TEXT NOT NULL
        )
    """,
    "user_gift_upgrades": """
        CREATE TABLE IF NOT EXISTS user_gift_upgrades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_gift_id INTEGER NOT NULL, upgrade_id INTEGER NOT NULL,
            rarity TEXT, rarity_color TEXT, number INTEGER,
            photo_filename TEXT, model_name TEXT,
            bg_id INTEGER,
            upgraded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "marketplace": """
        CREATE TABLE IF NOT EXISTS marketplace(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_gift_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "auctions": """
        CREATE TABLE IF NOT EXISTS auctions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_gift_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            start_price INTEGER NOT NULL,
            current_price INTEGER NOT NULL,
            current_bidder_id INTEGER DEFAULT NULL,
            end_time TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """,
    "auction_bids": """
        CREATE TABLE IF NOT EXISTS auction_bids(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id INTEGER NOT NULL,
            bidder_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            bid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
}

_sync_lock = threading.RLock()
_CACHE_TTL_SECONDS = 300.0
_AUTH_CACHE_TTL_SECONDS = 2.0
_remote_cache: dict[str, list[dict[str, Any]]] | None = None
_remote_table_at: dict[str, float] = {}


class SupabaseConnection:
    """Expose the small sqlite3.Connection surface used by app.py."""

    def __init__(
        self,
        local_db_path: str,
        refresh_tables: set[str] | None = None,
    ):
        _sync_lock.acquire()
        self._lock_held = True
        self._closed = False
        self._base_url = os.environ["SUPABASE_URL"].rstrip("/")
        self._key = os.environ["SUPABASE_KEY"]
        self._http = requests.Session()
        self._headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        self._local_db_path = local_db_path
        self._conn = sqlite3.connect(":memory:", timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._synced_snapshot: dict[str, list[dict[str, Any]]] = {
            table: [] for table in TABLES
        }
        try:
            self._create_local_schema()
            self._hydrate(refresh_tables)
        except Exception:
            self._conn.close()
            self._closed = True
            self._lock_held = False
            _sync_lock.release()
            raise

    def _create_local_schema(self) -> None:
        for sql in LOCAL_SCHEMA.values():
            self._conn.execute(sql)
        self._conn.commit()

    def _request(self, method: str, table: str, **kwargs: Any) -> requests.Response:
        response = self._http.request(
            method,
            f"{self._base_url}/rest/v1/{table}",
            headers=self._headers,
            timeout=20,
            **kwargs,
        )
        if not response.ok:
            detail = response.text[:300].replace("\n", " ")
            raise RuntimeError(
                f"Supabase {method} {table} failed ({response.status_code}): {detail}"
            )
        return response

    def _fetch_table(self, table: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        page_size = 1000
        while True:
            response = self._request(
                "GET",
                table,
                params={"select": "*", "limit": page_size, "offset": offset},
            )
            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError(f"Supabase returned an invalid response for {table}")
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size

    def _hydrate(self, refresh_tables: set[str] | None = None) -> None:
        global _remote_cache, _remote_table_at

        now = time.monotonic()
        if _remote_cache is None:
            tables_to_fetch = set(TABLES)
        else:
            tables_to_fetch = set(refresh_tables or ())
            tables_to_fetch.update(
                table
                for table in TABLES
                if now - _remote_table_at.get(table, 0.0)
                >= (
                    _AUTH_CACHE_TTL_SECONDS
                    if refresh_tables and table in refresh_tables
                    else _CACHE_TTL_SECONDS
                )
            )

        if tables_to_fetch:
            with ThreadPoolExecutor(max_workers=len(tables_to_fetch)) as executor:
                pages = executor.map(self._fetch_table, tables_to_fetch)
                fresh = dict(zip(tables_to_fetch, pages))

            if _remote_cache is None:
                _remote_cache = {table: [] for table in TABLES}
            for table, rows in fresh.items():
                _remote_cache[table] = rows
                _remote_table_at[table] = now

        if _remote_cache is not None and any(_remote_cache.values()):
            self._insert_rows(_remote_cache)
            self._conn.commit()
            self._synced_snapshot = self._snapshot()
            return

        # First run: preserve the existing SQLite catalog and balances, then
        # publish it on the first commit after init_db() creates its schema.
        if not os.path.exists(self._local_db_path):
            return
        source = sqlite3.connect(self._local_db_path)
        source.row_factory = sqlite3.Row
        try:
            local_rows: dict[str, list[dict[str, Any]]] = {}
            for table in TABLES:
                try:
                    local_rows[table] = [
                        dict(row)
                        for row in source.execute(f"SELECT * FROM {table}").fetchall()
                    ]
                except sqlite3.OperationalError:
                    local_rows[table] = []
            if any(local_rows.values()):
                self._insert_rows(local_rows)
                self._conn.commit()
        finally:
            source.close()

    def _insert_rows(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        for table in TABLES:
            for row in tables.get(table, []):
                row = {
                    column: self._sqlite_value(value)
                    for column, value in row.items()
                }
                columns = list(row)
                placeholders = ", ".join("?" for _ in columns)
                names = ", ".join(f'"{column}"' for column in columns)
                self._conn.execute(
                    f'INSERT OR REPLACE INTO "{table}" ({names}) VALUES ({placeholders})',
                    [row[column] for column in columns],
                )

    @staticmethod
    def _sqlite_value(value: Any) -> Any:
        if isinstance(value, str) and "T" in value and len(value) >= 19:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                pass
        return value

    def cursor(self) -> sqlite3.Cursor:
        return self._conn.cursor()

    def commit(self) -> None:
        global _remote_cache, _remote_table_at

        self._conn.commit()
        snapshot = self._snapshot()
        changed_tables = {
            table
            for table in TABLES
            if snapshot[table] != self._synced_snapshot[table]
        }
        if not changed_tables:
            return
        with _sync_lock:
            self._publish(snapshot, changed_tables)
        self._synced_snapshot = snapshot
        _remote_cache = {
            table: [dict(row) for row in rows]
            for table, rows in snapshot.items()
        }
        committed_at = time.monotonic()
        for table in changed_tables:
            _remote_table_at[table] = committed_at

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._conn.close()
        self._http.close()
        self._closed = True
        if self._lock_held:
            self._lock_held = False
            _sync_lock.release()

    def _snapshot(self) -> dict[str, list[dict[str, Any]]]:
        snapshot: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            snapshot[table] = [
                dict(row)
                for row in self._conn.execute(
                    f'SELECT * FROM "{table}" ORDER BY id'
                ).fetchall()
            ]
        return snapshot

    def _publish(
        self, snapshot: dict[str, list[dict[str, Any]]], changed_tables: set[str]
    ) -> None:
        for table in TABLES:
            if table not in changed_tables:
                continue
            rows = snapshot[table]
            for start in range(0, len(rows), 500):
                chunk = rows[start : start + 500]
                response = self._http.post(
                    f"{self._base_url}/rest/v1/{table}",
                    headers={
                        **self._headers,
                        "Prefer": "return=minimal,resolution=merge-duplicates",
                    },
                    params={"on_conflict": "id"},
                    json=chunk,
                    timeout=20,
                )
                if not response.ok:
                    detail = response.text[:300].replace("\n", " ")
                    raise RuntimeError(
                        f"Supabase UPSERT {table} failed "
                        f"({response.status_code}): {detail}"
                    )

        # Upsert first, then remove rows deleted locally.  This avoids leaving
        # the remote table empty if a later request fails halfway through.
        for table in DELETE_ORDER:
            if table not in changed_tables:
                continue
            ids = [str(row["id"]) for row in snapshot[table]]
            filter_value = (
                f"not.in.({','.join(ids)})" if ids else "not.is.null"
            )
            response = self._http.delete(
                f"{self._base_url}/rest/v1/{table}",
                headers={**self._headers, "Prefer": "return=minimal"},
                params={"id": filter_value},
                timeout=20,
            )
            if not response.ok:
                detail = response.text[:300].replace("\n", " ")
                raise RuntimeError(
                    f"Supabase DELETE {table} failed ({response.status_code}): {detail}"
                )
