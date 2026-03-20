from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from ..config.schema import DatabaseConfig
from .schema import ALL_DDL_STATEMENTS, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    pass


class DatabaseConnectionPool:
    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(
            maxsize=config.connection_pool_size
        )
        self._all_connections: list[aiosqlite.Connection] = []
        self._initialized = False

    async def initialize(self) -> None:
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self._config.connection_pool_size):
            conn = await aiosqlite.connect(
                self._config.path, timeout=self._config.query_timeout_seconds
            )
            conn.row_factory = aiosqlite.Row
            await self._configure_connection(conn)
            await self._pool.put(conn)
            self._all_connections.append(conn)
        await self._run_migrations()
        self._initialized = True
        logger.info("Database pool initialized with %d connections.", self._config.connection_pool_size)

    async def _configure_connection(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.commit()

    async def _run_migrations(self) -> None:
        async with self.acquire() as conn:
            for statement in ALL_DDL_STATEMENTS:
                await conn.execute(statement)
            await conn.commit()
            current = await self._get_schema_version(conn)
            if current < SCHEMA_VERSION:
                await conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations (version, description) VALUES (?, ?)",
                    (SCHEMA_VERSION, "initial schema"),
                )
                await conn.commit()
                logger.info("Schema migrated to version %d.", SCHEMA_VERSION)

    async def _get_schema_version(self, conn: aiosqlite.Connection) -> int:
        cursor = await conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        )
        row = await cursor.fetchone()
        if row is None or row["v"] is None:
            return 0
        return int(row["v"])

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self._initialized and self._pool.empty():
            raise DatabaseError("Pool not initialized. Call initialize() first.")
        conn = await asyncio.wait_for(
            self._pool.get(), timeout=self._config.query_timeout_seconds
        )
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self.acquire() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        async with self.acquire() as conn:
            cursor = await conn.execute(sql, params)
            await conn.commit()
            return cursor.lastrowid or 0

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        async with self.acquire() as conn:
            await conn.executemany(sql, params_list)
            await conn.commit()

    async def execute_in_transaction(self, operations: list[tuple[str, tuple]]) -> None:
        async with self.acquire() as conn:
            try:
                for sql, params in operations:
                    await conn.execute(sql, params)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close(self) -> None:
        for conn in self._all_connections:
            try:
                await conn.close()
            except Exception as exc:
                logger.warning("Error closing DB connection: %s", exc)
        logger.info("Database pool closed.")
