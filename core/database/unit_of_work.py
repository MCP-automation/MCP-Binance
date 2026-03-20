from __future__ import annotations
from .pool import DatabaseConnectionPool
from .repositories import (
    SessionRepository,
    StrategyRepository,
    OrderRepository,
    PositionRepository,
    TradeRepository,
    RiskEventRepository,
    NotificationRepository,
    PaperPortfolioRepository,
    BacktestRepository,
)


class UnitOfWork:
    def __init__(self, pool: DatabaseConnectionPool) -> None:
        self.sessions = SessionRepository(pool)
        self.strategies = StrategyRepository(pool)
        self.orders = OrderRepository(pool)
        self.positions = PositionRepository(pool)
        self.trades = TradeRepository(pool)
        self.risk_events = RiskEventRepository(pool)
        self.notifications = NotificationRepository(pool)
        self.paper_portfolios = PaperPortfolioRepository(pool)
        self.backtests = BacktestRepository(pool)
        self._pool = pool

    async def __aenter__(self) -> "UnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            pass
        return None

    async def commit(self) -> None:
        """No-op: repositories use auto-commit via execute_write."""
        pass

    async def raw_execute(self, sql: str, params: tuple = ()) -> list[dict]:
        return await self._pool.execute(sql, params)

    async def raw_write(self, sql: str, params: tuple = ()) -> int:
        return await self._pool.execute_write(sql, params)
