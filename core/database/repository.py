from __future__ import annotations
import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from .pool import DatabaseConnectionPool

T = TypeVar("T")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_json_field(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value)


def deserialize_json_field(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class BaseRepository(ABC, Generic[T]):
    def __init__(self, pool: DatabaseConnectionPool) -> None:
        self._pool = pool

    @property
    @abstractmethod
    def table_name(self) -> str:
        ...

    async def exists(self, record_id: str) -> bool:
        row = await self._pool.fetch_one(
            f"SELECT 1 FROM {self.table_name} WHERE id = ?", (record_id,)
        )
        return row is not None

    async def delete(self, record_id: str) -> None:
        await self._pool.execute_write(
            f"DELETE FROM {self.table_name} WHERE id = ?", (record_id,)
        )

    async def count(self, where_clause: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) as cnt FROM {self.table_name}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        row = await self._pool.fetch_one(sql, params)
        return int(row["cnt"]) if row else 0
