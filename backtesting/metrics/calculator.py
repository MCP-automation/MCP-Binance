from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
import math

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    total_return_pct: Decimal
    cagr_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    winning_trades: int
    losing_trades: int
    win_rate_pct: Decimal
    profit_factor: Decimal
    recovery_factor: Decimal
    payoff_ratio: Decimal
    avg_trade_duration_hours: Decimal
    volatility_pct: Decimal
    daily_volatility_pct: Decimal
    best_day_pct: Decimal
    worst_day_pct: Decimal
    consecutive_wins: int
    consecutive_losses: int
    skewness: Decimal
    kurtosis: Decimal


class PerformanceMetricsCalculator:
    def __init__(self, risk_free_rate_pct: Decimal = Decimal("2")):
        self.risk_free_rate_pct = risk_free_rate_pct
        self.risk_free_rate = risk_free_rate_pct / Decimal("100") / Decimal("252")

    def calculate(
        self,
        equity_history: List[tuple[datetime, Decimal]],
        trades: List,
        initial_capital: Decimal,
        final_capital: Decimal,
    ) -> PerformanceMetrics:
        if not equity_history or not trades:
            return self._empty_metrics()

        equity_values = [eq for _, eq in equity_history]
        timestamps = [ts for ts, _ in equity_history]

        total_return_pct = ((final_capital - initial_capital) / initial_capital) * Decimal("100")
        cagr_pct = self._calculate_cagr(
            initial_capital,
            final_capital,
            timestamps[0],
            timestamps[-1],
        )
        max_dd_pct = self._calculate_max_drawdown(equity_values)
        sharpe = self._calculate_sharpe_ratio(equity_values)
        sortino = self._calculate_sortino_ratio(equity_values)
        calmar = self._calculate_calmar_ratio(cagr_pct, max_dd_pct)

        winning_trades = sum(1 for t in trades if t.realized_pnl > 0)
        losing_trades = len(trades) - winning_trades
        win_rate = (Decimal(winning_trades) / Decimal(len(trades)) * Decimal("100")) if trades else Decimal("0")

        avg_win = sum(t.net_pnl for t in trades if t.realized_pnl > 0) / Decimal(winning_trades) if winning_trades > 0 else Decimal("0")
        avg_loss = sum(t.net_pnl for t in trades if t.realized_pnl < 0) / Decimal(losing_trades) if losing_trades > 0 else Decimal("0")

        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else Decimal("0")
        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else Decimal("0")
        total_pnl = sum(t.net_pnl for t in trades)
        recovery_factor = total_pnl / abs(min((t.net_pnl for t in trades), default=Decimal("0"))) if losing_trades > 0 else Decimal("0")

        avg_duration = self._calculate_avg_trade_duration(trades)

        daily_returns = self._calculate_daily_returns(equity_history)
        volatility = self._calculate_volatility(daily_returns)
        daily_vol = self._calculate_daily_volatility(daily_returns)

        best_day = max(daily_returns) if daily_returns else Decimal("0")
        worst_day = min(daily_returns) if daily_returns else Decimal("0")

        consec_wins = self._calculate_consecutive_wins(trades)
        consec_losses = self._calculate_consecutive_losses(trades)

        skew = self._calculate_skewness(daily_returns) if daily_returns else Decimal("0")
        kurt = self._calculate_kurtosis(daily_returns) if daily_returns else Decimal("0")

        return PerformanceMetrics(
            total_return_pct=total_return_pct,
            cagr_pct=cagr_pct,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            recovery_factor=recovery_factor,
            payoff_ratio=payoff_ratio,
            avg_trade_duration_hours=avg_duration,
            volatility_pct=volatility,
            daily_volatility_pct=daily_vol,
            best_day_pct=best_day,
            worst_day_pct=worst_day,
            consecutive_wins=consec_wins,
            consecutive_losses=consec_losses,
            skewness=skew,
            kurtosis=kurt,
        )

    def _empty_metrics(self) -> PerformanceMetrics:
        return PerformanceMetrics(
            total_return_pct=Decimal("0"),
            cagr_pct=Decimal("0"),
            max_drawdown_pct=Decimal("0"),
            sharpe_ratio=Decimal("0"),
            sortino_ratio=Decimal("0"),
            calmar_ratio=Decimal("0"),
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=Decimal("0"),
            profit_factor=Decimal("0"),
            recovery_factor=Decimal("0"),
            payoff_ratio=Decimal("0"),
            avg_trade_duration_hours=Decimal("0"),
            volatility_pct=Decimal("0"),
            daily_volatility_pct=Decimal("0"),
            best_day_pct=Decimal("0"),
            worst_day_pct=Decimal("0"),
            consecutive_wins=0,
            consecutive_losses=0,
            skewness=Decimal("0"),
            kurtosis=Decimal("0"),
        )

    def _calculate_cagr(
        self,
        initial: Decimal,
        final: Decimal,
        start_time: datetime,
        end_time: datetime,
    ) -> Decimal:
        years = (end_time - start_time).days / Decimal("365.25")
        if years <= 0 or initial <= 0:
            return Decimal("0")

        cagr = ((final / initial) ** (Decimal("1") / years) - Decimal("1")) * Decimal("100")
        return max(cagr, Decimal("-100"))

    def _calculate_max_drawdown(self, equity_values: List[Decimal]) -> Decimal:
        if not equity_values or len(equity_values) < 1:
            return Decimal("0")

        peak = equity_values[0]
        max_dd = Decimal("0")

        for equity in equity_values[1:]:
            if equity < peak:
                dd = ((peak - equity) / peak) * Decimal("100")
                max_dd = max(max_dd, dd)
            else:
                peak = equity

        return max_dd

    def _calculate_sharpe_ratio(self, equity_values: List[Decimal]) -> Decimal:
        daily_returns = self._calculate_daily_returns([(i, eq) for i, eq in enumerate(equity_values)])
        if not daily_returns or len(daily_returns) < 2:
            return Decimal("0")

        avg_return = sum(daily_returns) / Decimal(len(daily_returns))
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / Decimal(len(daily_returns))
        std_dev = Decimal(str(math.sqrt(float(variance)))) if variance > 0 else Decimal("0")

        if std_dev == 0:
            return Decimal("0")

        sharpe = ((avg_return - self.risk_free_rate) / std_dev) * Decimal(str(math.sqrt(252)))
        return sharpe

    def _calculate_sortino_ratio(self, equity_values: List[Decimal]) -> Decimal:
        daily_returns = self._calculate_daily_returns([(i, eq) for i, eq in enumerate(equity_values)])
        if not daily_returns or len(daily_returns) < 2:
            return Decimal("0")

        avg_return = sum(daily_returns) / Decimal(len(daily_returns))
        downside_returns = [r - self.risk_free_rate for r in daily_returns if r < self.risk_free_rate]

        if not downside_returns:
            return Decimal("0")

        downside_variance = sum(r ** 2 for r in downside_returns) / Decimal(len(downside_returns))
        downside_std = Decimal(str(math.sqrt(float(downside_variance)))) if downside_variance > 0 else Decimal("0")

        if downside_std == 0:
            return Decimal("0")

        sortino = ((avg_return - self.risk_free_rate) / downside_std) * Decimal(str(math.sqrt(252)))
        return sortino

    def _calculate_calmar_ratio(self, cagr: Decimal, max_dd: Decimal) -> Decimal:
        if max_dd == 0:
            return Decimal("0")
        return cagr / max_dd

    def _calculate_daily_returns(self, equity_history: List[tuple]) -> List[Decimal]:
        if len(equity_history) < 2:
            return []

        daily_returns = []
        for i in range(1, len(equity_history)):
            prev_equity = equity_history[i - 1][1]
            curr_equity = equity_history[i][1]

            if prev_equity > 0:
                daily_return = ((curr_equity - prev_equity) / prev_equity) * Decimal("100")
                daily_returns.append(daily_return)

        return daily_returns

    def _calculate_volatility(self, daily_returns: List[Decimal]) -> Decimal:
        if not daily_returns or len(daily_returns) < 2:
            return Decimal("0")

        avg_return = sum(daily_returns) / Decimal(len(daily_returns))
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / Decimal(len(daily_returns))
        std_dev = Decimal(str(math.sqrt(float(variance)))) if variance > 0 else Decimal("0")

        annual_volatility = std_dev * Decimal(str(math.sqrt(252)))
        return annual_volatility

    def _calculate_daily_volatility(self, daily_returns: List[Decimal]) -> Decimal:
        if not daily_returns or len(daily_returns) < 2:
            return Decimal("0")

        avg_return = sum(daily_returns) / Decimal(len(daily_returns))
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / Decimal(len(daily_returns))
        std_dev = Decimal(str(math.sqrt(float(variance)))) if variance > 0 else Decimal("0")

        return std_dev

    def _calculate_avg_trade_duration(self, trades) -> Decimal:
        if not trades:
            return Decimal("0")
        durations = []
        for trade in trades:
            try:
                if isinstance(trade, dict):
                    entry_time = trade.get("entry_time")
                    exit_time = trade.get("exit_time")
                else:
                    entry_time = getattr(trade, "entry_time", None)
                    exit_time = getattr(trade, "exit_time", None)
                if entry_time and exit_time:
                    d = (exit_time - entry_time).total_seconds() / 3600
                    durations.append(d)
            except Exception:
                continue
        if not durations:
            return Decimal("0")
        return Decimal(str(round(sum(durations) / len(durations), 2)))

    def _calculate_consecutive_wins(self, trades: List) -> int:
        if not trades:
            return 0

        max_wins = 0
        current_wins = 0

        for trade in trades:
            if trade.realized_pnl > 0:
                current_wins += 1
                max_wins = max(max_wins, current_wins)
            else:
                current_wins = 0

        return max_wins

    def _calculate_consecutive_losses(self, trades: List) -> int:
        if not trades:
            return 0

        max_losses = 0
        current_losses = 0

        for trade in trades:
            if trade.realized_pnl < 0:
                current_losses += 1
                max_losses = max(max_losses, current_losses)
            else:
                current_losses = 0

        return max_losses

    def _calculate_skewness(self, daily_returns: List[Decimal]) -> Decimal:
        if not daily_returns or len(daily_returns) < 3:
            return Decimal("0")

        n = Decimal(len(daily_returns))
        mean = sum(daily_returns) / n
        variance = sum((r - mean) ** 2 for r in daily_returns) / n
        std_dev = Decimal(str(math.sqrt(float(variance)))) if variance > 0 else Decimal("1")

        m3 = sum((r - mean) ** 3 for r in daily_returns) / n
        skew = m3 / (std_dev ** 3) if std_dev != 0 else Decimal("0")

        return skew

    def _calculate_kurtosis(self, daily_returns: List[Decimal]) -> Decimal:
        if not daily_returns or len(daily_returns) < 4:
            return Decimal("0")

        n = Decimal(len(daily_returns))
        mean = sum(daily_returns) / n
        variance = sum((r - mean) ** 2 for r in daily_returns) / n
        std_dev = Decimal(str(math.sqrt(float(variance)))) if variance > 0 else Decimal("1")

        m4 = sum((r - mean) ** 4 for r in daily_returns) / n
        kurt = (m4 / (std_dev ** 4) if std_dev != 0 else Decimal("0")) - Decimal("3")

        return kurt
