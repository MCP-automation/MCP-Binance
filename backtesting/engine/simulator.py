from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Callable, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid

from exchange.types import OrderSide, OHLCV

logger = logging.getLogger(__name__)


class BacktestSignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    RESIZE = "RESIZE"


@dataclass
class BacktestSignal:
    timestamp: datetime
    symbol: str
    signal_type: BacktestSignalType
    price: Decimal
    quantity: Decimal
    metadata: dict = field(default_factory=dict)


@dataclass
class SimulatedTrade:
    trade_id: str
    symbol: str
    entry_time: datetime
    entry_price: Decimal
    entry_quantity: Decimal
    exit_time: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    exit_quantity: Decimal = Decimal("0")
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    realized_pnl: Decimal = Decimal("0")
    realized_pnl_pct: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    max_profit_pct: Decimal = Decimal("0")
    duration_minutes: int = 0
    bars_held: int = 0
    exit_reason: Optional[str] = None
    slippage: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    metadata: dict = field(default_factory=dict)


@dataclass
class BacktestEquityCurve:
    timestamps: List[datetime]
    equity_values: List[Decimal]
    daily_returns: List[Decimal]


class EventDrivenBacktestEngine:
    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000"),
        commission_pct: Decimal = Decimal("0.1"),
        slippage_pct: Decimal = Decimal("0.05"),
        max_positions: int = 10,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.max_positions = max_positions

        self.current_equity = initial_capital
        self.peak_equity = initial_capital
        self.open_positions: Dict[str, SimulatedTrade] = {}
        self.closed_trades: List[SimulatedTrade] = []
        self.equity_history: List[tuple[datetime, Decimal]] = []
        self.daily_equity: Dict[str, Decimal] = {}

    def process_bar(
        self,
        candle: OHLCV,
        signal: Optional[BacktestSignal] = None,
        update_equity: bool = True,
    ) -> Optional[SimulatedTrade]:
        result_trade = None

        if signal:
            if signal.signal_type == BacktestSignalType.BUY:
                result_trade = self._enter_long(candle, signal)
            elif signal.signal_type == BacktestSignalType.SELL:
                result_trade = self._exit_position(candle, signal)
            elif signal.signal_type == BacktestSignalType.CLOSE:
                result_trade = self._close_all_positions(candle, signal)

        self._update_open_positions(candle)

        if update_equity:
            self._update_equity_from_positions(candle)

        return result_trade

    def _enter_long(self, candle: OHLCV, signal: BacktestSignal) -> Optional[SimulatedTrade]:
        if len(self.open_positions) >= self.max_positions:
            logger.warning("Max positions reached, skipping entry signal")
            return None

        slippage = signal.price * self.slippage_pct / Decimal("100")
        entry_price = signal.price + slippage

        commission = (entry_price * signal.quantity) * self.commission_pct / Decimal("100")
        cost = (entry_price * signal.quantity) + commission

        if cost > self.current_equity:
            logger.warning(
                "Insufficient equity for entry: %s | Required: %.2f | Available: %.2f",
                signal.symbol,
                cost,
                self.current_equity,
            )
            return None

        trade = SimulatedTrade(
            trade_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            entry_time=candle.timestamp,
            entry_price=entry_price,
            entry_quantity=signal.quantity,
            stop_loss=signal.metadata.get("stop_loss"),
            take_profit=signal.metadata.get("take_profit"),
            slippage=slippage * signal.quantity,
            commission=commission,
        )

        self.open_positions[signal.symbol] = trade
        self.current_equity -= cost

        logger.info(
            "Entry: %s | Price: %.2f | Qty: %.4f | Equity: %.2f",
            signal.symbol,
            entry_price,
            signal.quantity,
            self.current_equity,
        )

        return trade

    def _exit_position(self, candle: OHLCV, signal: BacktestSignal) -> Optional[SimulatedTrade]:
        if signal.symbol not in self.open_positions:
            return None

        trade = self.open_positions[signal.symbol]

        slippage = signal.price * self.slippage_pct / Decimal("100")
        exit_price = signal.price - slippage

        commission = (exit_price * signal.quantity) * self.commission_pct / Decimal("100")
        proceeds = (exit_price * signal.quantity) - commission

        realized_pnl = proceeds - (trade.entry_price * signal.quantity)
        realized_pnl_pct = (realized_pnl / (trade.entry_price * signal.quantity)) * Decimal("100")

        trade.exit_time = candle.timestamp
        trade.exit_price = exit_price
        trade.exit_quantity = signal.quantity
        trade.realized_pnl = realized_pnl
        trade.realized_pnl_pct = realized_pnl_pct
        trade.duration_minutes = int((candle.timestamp - trade.entry_time).total_seconds() / 60)
        trade.exit_reason = signal.metadata.get("reason", "SIGNAL")
        trade.slippage += slippage * signal.quantity
        trade.commission += commission
        trade.net_pnl = realized_pnl - trade.slippage

        self.current_equity += proceeds
        self.peak_equity = max(self.peak_equity, self.current_equity)

        del self.open_positions[signal.symbol]
        self.closed_trades.append(trade)

        logger.info(
            "Exit: %s | Price: %.2f | P&L: %.2f (%.2f%%) | Equity: %.2f",
            signal.symbol,
            exit_price,
            realized_pnl,
            realized_pnl_pct,
            self.current_equity,
        )

        return trade

    def _close_all_positions(self, candle: OHLCV, signal: BacktestSignal) -> Optional[SimulatedTrade]:
        last_trade = None
        for symbol in list(self.open_positions.keys()):
            last_trade = self._exit_position(
                candle,
                BacktestSignal(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    signal_type=BacktestSignalType.SELL,
                    price=candle.close,
                    quantity=self.open_positions[symbol].entry_quantity,
                    metadata={"reason": "CLOSE_ALL"},
                ),
            )
        return last_trade

    def _update_open_positions(self, candle: OHLCV) -> None:
        if candle.symbol not in self.open_positions:
            return

        trade = self.open_positions[candle.symbol]
        trade.bars_held += 1

        current_price = candle.close
        unrealized_pnl = (current_price - trade.entry_price) * trade.entry_quantity
        unrealized_pnl_pct = (unrealized_pnl / (trade.entry_price * trade.entry_quantity)) * Decimal("100")

        trade.max_profit_pct = max(trade.max_profit_pct, unrealized_pnl_pct)
        trade.max_drawdown_pct = min(trade.max_drawdown_pct, unrealized_pnl_pct)

        if trade.stop_loss and current_price <= trade.stop_loss:
            exit_signal = BacktestSignal(
                timestamp=candle.timestamp,
                symbol=candle.symbol,
                signal_type=BacktestSignalType.SELL,
                price=trade.stop_loss,
                quantity=trade.entry_quantity,
                metadata={"reason": "STOP_LOSS"},
            )
            self._exit_position(candle, exit_signal)

        elif trade.take_profit and current_price >= trade.take_profit:
            exit_signal = BacktestSignal(
                timestamp=candle.timestamp,
                symbol=candle.symbol,
                signal_type=BacktestSignalType.SELL,
                price=trade.take_profit,
                quantity=trade.entry_quantity,
                metadata={"reason": "TAKE_PROFIT"},
            )
            self._exit_position(candle, exit_signal)

    def _update_equity_from_positions(self, candle: OHLCV) -> None:
        unrealized_pnl = Decimal("0")

        for symbol, trade in self.open_positions.items():
            if symbol == candle.symbol:
                price = candle.close
            else:
                price = trade.entry_price

            position_pnl = (price - trade.entry_price) * trade.entry_quantity
            unrealized_pnl += position_pnl

        self.current_equity = self.initial_capital + unrealized_pnl + sum(t.net_pnl for t in self.closed_trades)
        self.peak_equity = max(self.peak_equity, self.current_equity)

        date_key = candle.timestamp.date().isoformat()
        self.daily_equity[date_key] = self.current_equity
        self.equity_history.append((candle.timestamp, self.current_equity))

    def get_equity_curve(self) -> BacktestEquityCurve:
        if not self.equity_history:
            return BacktestEquityCurve([], [], [])

        timestamps = [t[0] for t in self.equity_history]
        equity_values = [t[1] for t in self.equity_history]

        daily_returns = []
        previous_close = self.initial_capital

        for date_key in sorted(self.daily_equity.keys()):
            daily_equity = self.daily_equity[date_key]
            daily_return = ((daily_equity - previous_close) / previous_close) * Decimal("100")
            daily_returns.append(daily_return)
            previous_close = daily_equity

        return BacktestEquityCurve(
            timestamps=timestamps,
            equity_values=equity_values,
            daily_returns=daily_returns,
        )

    def get_closed_trades(self) -> List[SimulatedTrade]:
        return self.closed_trades.copy()

    def get_open_positions(self) -> Dict[str, SimulatedTrade]:
        return self.open_positions.copy()

    def get_summary(self) -> dict:
        equity_curve = self.get_equity_curve()
        total_return = ((self.current_equity - self.initial_capital) / self.initial_capital) * Decimal("100")
        drawdown = ((self.peak_equity - self.current_equity) / self.peak_equity) * Decimal("100")

        closed_count = len(self.closed_trades)
        winning_trades = sum(1 for t in self.closed_trades if t.realized_pnl > 0)
        losing_trades = closed_count - winning_trades

        total_pnl = sum(t.net_pnl for t in self.closed_trades)

        return {
            "initial_capital": float(self.initial_capital),
            "final_equity": float(self.current_equity),
            "total_return_pct": float(total_return),
            "peak_equity": float(self.peak_equity),
            "current_drawdown_pct": float(drawdown),
            "total_trades": closed_count,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": float((winning_trades / closed_count * Decimal("100")) if closed_count > 0 else Decimal("0")),
            "total_pnl": float(total_pnl),
            "avg_pnl_per_trade": float(total_pnl / closed_count if closed_count > 0 else Decimal("0")),
            "avg_winning_trade": float(sum(t.net_pnl for t in self.closed_trades if t.realized_pnl > 0) / winning_trades if winning_trades > 0 else Decimal("0")),
            "avg_losing_trade": float(sum(t.net_pnl for t in self.closed_trades if t.realized_pnl < 0) / losing_trades if losing_trades > 0 else Decimal("0")),
            "largest_win": float(max((t.net_pnl for t in self.closed_trades), default=Decimal("0"))),
            "largest_loss": float(min((t.net_pnl for t in self.closed_trades), default=Decimal("0"))),
            "profit_factor": float(sum(t.net_pnl for t in self.closed_trades if t.realized_pnl > 0) / abs(sum(t.net_pnl for t in self.closed_trades if t.realized_pnl < 0)) if losing_trades > 0 else Decimal("0")),
            "open_positions": len(self.open_positions),
            "total_commission": float(sum(t.commission for t in self.closed_trades)),
            "total_slippage": float(sum(t.slippage for t in self.closed_trades)),
        }
