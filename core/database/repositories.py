from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from .pool import DatabaseConnectionPool
from .repository import BaseRepository, new_id, utcnow_iso, serialize_json_field


class SessionRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "sessions"

    async def create(self, trading_mode: str, mcp_version: str, metadata: dict | None = None) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO sessions (id, trading_mode, mcp_version, metadata)
               VALUES (?, ?, ?, ?)""",
            (record_id, trading_mode, mcp_version, json.dumps(metadata or {})),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, session_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )

    async def close_session(self, session_id: str) -> None:
        await self._pool.execute_write(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (utcnow_iso(), session_id),
        )

    async def get_latest(self) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
        )


class StrategyRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "strategies"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO strategies (id, version, name, description, timeframe, market_type,
               indicators, entry_conditions, exit_conditions, stop_loss_pct, take_profit_pct,
               trailing_stop_pct, raw_config, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data.get("version", 1),
                data["name"],
                data.get("description", ""),
                data["timeframe"],
                data["market_type"],
                json.dumps(data.get("indicators", [])),
                json.dumps(data.get("entry_conditions", [])),
                json.dumps(data.get("exit_conditions", [])),
                data.get("stop_loss_pct"),
                data.get("take_profit_pct"),
                data.get("trailing_stop_pct"),
                json.dumps(data.get("raw_config", {})),
                int(data.get("is_active", False)),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, strategy_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
        )

    async def get_active(self) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM strategies WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
        )

    async def set_active(self, strategy_id: str) -> None:
        await self._pool.execute_in_transaction([
            ("UPDATE strategies SET is_active = 0", ()),
            ("UPDATE strategies SET is_active = 1, updated_at = ? WHERE id = ?",
             (utcnow_iso(), strategy_id)),
        ])

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM strategies ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def get_by_name(self, name: str) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM strategies WHERE name = ? ORDER BY version DESC", (name,)
        )

    async def create_new_version(self, base_id: str, updates: dict) -> dict:
        base = await self.get_by_id(base_id)
        if base is None:
            raise ValueError(f"Strategy {base_id} not found.")
        latest_versions = await self.get_by_name(base["name"])
        next_version = max(r["version"] for r in latest_versions) + 1 if latest_versions else 1
        merged = dict(base)
        merged.update(updates)
        merged["version"] = next_version
        merged.pop("id", None)
        merged.pop("created_at", None)
        merged.pop("updated_at", None)
        return await self.create(merged)


class OrderRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "orders"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO orders (id, client_order_id, exchange_order_id, session_id, strategy_id,
               symbol, market_type, side, order_type, status, price, stop_price, quantity,
               filled_quantity, avg_fill_price, commission, commission_asset, is_paper,
               time_in_force, reduce_only, close_position, raw_exchange_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data.get("client_order_id"),
                data.get("exchange_order_id"),
                data.get("session_id"),
                data.get("strategy_id"),
                data["symbol"],
                data["market_type"],
                data["side"],
                data["order_type"],
                data.get("status", "pending"),
                data.get("price"),
                data.get("stop_price"),
                data["quantity"],
                data.get("filled_quantity", 0.0),
                data.get("avg_fill_price"),
                data.get("commission", 0.0),
                data.get("commission_asset"),
                int(data.get("is_paper", False)),
                data.get("time_in_force", "GTC"),
                int(data.get("reduce_only", False)),
                int(data.get("close_position", False)),
                json.dumps(data.get("raw_exchange_data", {})),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, order_id: str) -> dict | None:
        return await self._pool.fetch_one("SELECT * FROM orders WHERE id = ?", (order_id,))

    async def get_by_client_id(self, client_order_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
        )

    async def update_status(self, order_id: str, status: str, **extra_fields) -> None:
        updates = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, utcnow_iso()]
        for field, value in extra_fields.items():
            updates.append(f"{field} = ?")
            values.append(value)
        if status in ("filled", "partially_filled"):
            updates.append("filled_at = ?")
            values.append(utcnow_iso())
        values.append(order_id)
        await self._pool.execute_write(
            f"UPDATE orders SET {', '.join(updates)} WHERE id = ?", tuple(values)
        )

    async def get_open_orders(self, symbol: str | None = None, is_paper: bool | None = None) -> list[dict]:
        clauses = ["status IN ('pending', 'partially_filled', 'new')"]
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if is_paper is not None:
            clauses.append("is_paper = ?")
            params.append(int(is_paper))
        sql = f"SELECT * FROM orders WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        return await self._pool.execute(sql, tuple(params))

    async def get_by_session(self, session_id: str, limit: int = 200) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM orders WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )


class PositionRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "positions"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO positions (id, session_id, strategy_id, symbol, market_type, side,
               entry_price, current_price, quantity, leverage, unrealized_pnl, realized_pnl,
               stop_loss_price, take_profit_price, trailing_stop_pct, is_paper, is_open,
               entry_order_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data.get("session_id"),
                data.get("strategy_id"),
                data["symbol"],
                data["market_type"],
                data["side"],
                data["entry_price"],
                data.get("current_price", data["entry_price"]),
                data["quantity"],
                data.get("leverage", 1.0),
                data.get("unrealized_pnl", 0.0),
                data.get("realized_pnl", 0.0),
                data.get("stop_loss_price"),
                data.get("take_profit_price"),
                data.get("trailing_stop_pct"),
                int(data.get("is_paper", False)),
                1,
                data.get("entry_order_id"),
                json.dumps(data.get("metadata", {})),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, position_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        )

    async def get_open_positions(self, is_paper: bool | None = None) -> list[dict]:
        params: list[Any] = [1]
        sql = "SELECT * FROM positions WHERE is_open = ?"
        if is_paper is not None:
            sql += " AND is_paper = ?"
            params.append(int(is_paper))
        sql += " ORDER BY opened_at DESC"
        return await self._pool.execute(sql, tuple(params))

    async def update_pnl(self, position_id: str, current_price: float, unrealized_pnl: float) -> None:
        await self._pool.execute_write(
            "UPDATE positions SET current_price = ?, unrealized_pnl = ? WHERE id = ?",
            (current_price, unrealized_pnl, position_id),
        )

    async def close_position(self, position_id: str, exit_order_id: str, realized_pnl: float) -> None:
        now = utcnow_iso()
        pos = await self.get_by_id(position_id)
        if pos is None:
            return
        opened_at = datetime.fromisoformat(pos["opened_at"])
        duration = (datetime.now(timezone.utc) - opened_at.replace(tzinfo=timezone.utc)).total_seconds()
        await self._pool.execute_write(
            """UPDATE positions SET is_open = 0, realized_pnl = ?, unrealized_pnl = 0.0,
               exit_order_id = ?, closed_at = ?, duration_seconds = ? WHERE id = ?""",
            (realized_pnl, exit_order_id, now, duration, position_id),
        )

    async def count_open(self, is_paper: bool | None = None) -> int:
        params: list[Any] = [1]
        sql = "SELECT COUNT(*) as cnt FROM positions WHERE is_open = ?"
        if is_paper is not None:
            sql += " AND is_paper = ?"
            params.append(int(is_paper))
        row = await self._pool.fetch_one(sql, tuple(params))
        return int(row["cnt"]) if row else 0


class TradeRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "trades"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO trades (id, position_id, session_id, strategy_id, symbol, market_type,
               side, entry_price, exit_price, quantity, leverage, gross_pnl, commission, net_pnl,
               pnl_pct, duration_seconds, is_paper, entry_reason, exit_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data["position_id"],
                data.get("session_id"),
                data.get("strategy_id"),
                data["symbol"],
                data["market_type"],
                data["side"],
                data["entry_price"],
                data["exit_price"],
                data["quantity"],
                data.get("leverage", 1.0),
                data["gross_pnl"],
                data.get("commission", 0.0),
                data["net_pnl"],
                data["pnl_pct"],
                data["duration_seconds"],
                int(data.get("is_paper", False)),
                data.get("entry_reason", ""),
                data.get("exit_reason", ""),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, trade_id: str) -> dict | None:
        return await self._pool.fetch_one("SELECT * FROM trades WHERE id = ?", (trade_id,))

    async def get_by_session(self, session_id: str, limit: int = 500, offset: int = 0) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM trades WHERE session_id = ? ORDER BY closed_at DESC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        )

    async def get_performance_summary(self, session_id: str, is_paper: bool | None = None) -> dict:
        params: list[Any] = [session_id]
        where = "session_id = ?"
        if is_paper is not None:
            where += " AND is_paper = ?"
            params.append(int(is_paper))
        row = await self._pool.fetch_one(
            f"""SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                SUM(net_pnl) as total_net_pnl,
                AVG(net_pnl) as avg_net_pnl,
                SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) as gross_profit,
                SUM(CASE WHEN net_pnl < 0 THEN ABS(net_pnl) ELSE 0 END) as gross_loss,
                AVG(duration_seconds) as avg_duration_seconds,
                MAX(net_pnl) as best_trade,
                MIN(net_pnl) as worst_trade
            FROM trades WHERE {where}""",
            tuple(params),
        )
        return dict(row) if row else {}


class RiskEventRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "risk_events"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO risk_events (id, session_id, event_type, severity, symbol,
               description, trigger_value, threshold_value, action_taken)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data.get("session_id"),
                data["event_type"],
                data["severity"],
                data.get("symbol"),
                data["description"],
                data.get("trigger_value"),
                data.get("threshold_value"),
                data.get("action_taken", ""),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, event_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM risk_events WHERE id = ?", (event_id,)
        )

    async def get_unresolved(self, session_id: str) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM risk_events WHERE session_id = ? AND resolved = 0 ORDER BY created_at DESC",
            (session_id,),
        )

    async def resolve(self, event_id: str) -> None:
        await self._pool.execute_write(
            "UPDATE risk_events SET resolved = 1, resolved_at = ? WHERE id = ?",
            (utcnow_iso(), event_id),
        )


class NotificationRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "notifications"

    async def create(self, data: dict) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO notifications (id, channel, event_type, payload, message, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data["channel"],
                data["event_type"],
                json.dumps(data.get("payload", {})),
                data["message"],
                "pending",
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, notification_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        )

    async def get_pending(self, limit: int = 50) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM notifications WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )

    async def mark_sent(self, notification_id: str) -> None:
        await self._pool.execute_write(
            "UPDATE notifications SET status = 'sent', sent_at = ? WHERE id = ?",
            (utcnow_iso(), notification_id),
        )

    async def mark_failed(self, notification_id: str, error_message: str, attempts: int) -> None:
        status = "failed" if attempts >= 3 else "pending"
        await self._pool.execute_write(
            "UPDATE notifications SET status = ?, error_message = ?, attempts = ? WHERE id = ?",
            (status, error_message, attempts, notification_id),
        )


class BacktestRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "backtests"

    async def create(self, data: dict) -> dict:
        record_id = data.get("id") or new_id()
        await self._pool.execute_write(
            """INSERT INTO backtests (id, strategy_id, symbols, timeframe, start_date, end_date,
               initial_capital, final_capital, total_pnl, total_pnl_pct, status, error_message,
               equity_curve, per_symbol_stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                data["strategy_id"],
                data.get("symbols", "[]"),
                data["timeframe"],
                data["start_date"],
                data["end_date"],
                data["initial_capital"],
                data.get("final_capital"),
                data.get("total_pnl"),
                data.get("total_pnl_pct"),
                data.get("status", "pending"),
                data.get("error_message"),
                data.get("equity_curve", "[]"),
                data.get("per_symbol_stats", "{}"),
            ),
        )
        return await self.get_by_id(record_id)

    async def get_by_id(self, backtest_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM backtests WHERE id = ?", (backtest_id,)
        )

    async def list_by_strategy(self, strategy_id: str, limit: int = 20) -> list[dict]:
        return await self._pool.execute(
            "SELECT * FROM backtests WHERE strategy_id = ? ORDER BY created_at DESC LIMIT ?",
            (strategy_id, limit),
        )


class PaperPortfolioRepository(BaseRepository):
    @property
    def table_name(self) -> str:
        return "paper_portfolios"

    async def create(self, session_id: str, initial_balance: float) -> dict:
        record_id = new_id()
        await self._pool.execute_write(
            """INSERT INTO paper_portfolios (id, session_id, balance_usdt, initial_balance, peak_balance)
               VALUES (?, ?, ?, ?, ?)""",
            (record_id, session_id, initial_balance, initial_balance, initial_balance),
        )
        return await self.get_by_session(session_id)

    async def get_by_session(self, session_id: str) -> dict | None:
        return await self._pool.fetch_one(
            "SELECT * FROM paper_portfolios WHERE session_id = ?", (session_id,)
        )

    async def update(self, session_id: str, balance_usdt: float, realized_pnl: float,
                     unrealized_pnl: float) -> None:
        current = await self.get_by_session(session_id)
        if current is None:
            return
        new_peak = max(current["peak_balance"], balance_usdt)
        max_dd = max(current["max_drawdown"], (new_peak - balance_usdt) / new_peak * 100 if new_peak > 0 else 0.0)
        total_pnl = balance_usdt + unrealized_pnl - current["initial_balance"]
        await self._pool.execute_write(
            """UPDATE paper_portfolios SET balance_usdt = ?, realized_pnl = ?, unrealized_pnl = ?,
               total_pnl = ?, peak_balance = ?, max_drawdown = ?, updated_at = ?
               WHERE session_id = ?""",
            (balance_usdt, realized_pnl, unrealized_pnl, total_pnl, new_peak, max_dd,
             utcnow_iso(), session_id),
        )
