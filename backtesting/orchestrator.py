from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
import uuid
import json

from backtesting.data.fetcher import HistoricalDataFetcher
from backtesting.engine.simulator import (
    EventDrivenBacktestEngine,
    BacktestSignal,
    BacktestSignalType,
)
from backtesting.metrics.calculator import PerformanceMetricsCalculator
from backtesting.strategies.loader import StrategyConfig, StrategyExecutor, BacktestConfig

logger = logging.getLogger(__name__)


class BacktestResult:
    def __init__(
        self,
        backtest_id: str,
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
    ):
        self.backtest_id = backtest_id
        self.strategy_config = strategy_config
        self.backtest_config = backtest_config
        self.start_time = datetime.utcnow()
        self.end_time: Optional[datetime] = None
        self.status = "RUNNING"
        self.error_message: Optional[str] = None

        self.engine: Optional[EventDrivenBacktestEngine] = None
        self.metrics: Optional[dict] = None
        self.trades: List = []
        self.equity_curve: Optional[dict] = None
        self.per_symbol_stats: dict = {}

    def to_dict(self) -> dict:
        return {
            "backtest_id": self.backtest_id,
            "strategy_name": self.strategy_config.name,
            "strategy_version": self.strategy_config.version,
            "start_date": self.backtest_config.start_date.isoformat(),
            "end_date": self.backtest_config.end_date.isoformat(),
            "initial_capital": float(self.backtest_config.initial_capital),
            "final_equity": float(self.engine.current_equity) if self.engine else 0,
            "status": self.status,
            "error_message": self.error_message,
            "metrics": self.metrics,
            "trades_count": len(self.trades),
            "per_symbol_stats": self.per_symbol_stats,
        }


class BacktestRunner:
    def __init__(
        self,
        exchange_manager,
        uow,
    ):
        self.exchange = exchange_manager
        self.uow = uow
        self.data_fetcher = HistoricalDataFetcher(exchange_manager)
        self.metrics_calculator = PerformanceMetricsCalculator()

    async def run_backtest(
        self,
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
    ) -> BacktestResult:
        backtest_id = str(uuid.uuid4())
        result = BacktestResult(backtest_id, strategy_config, backtest_config)

        try:
            logger.info(
                "Starting backtest: %s | Strategy: %s | Period: %s to %s",
                backtest_id,
                strategy_config.name,
                backtest_config.start_date,
                backtest_config.end_date,
            )

            symbol_data = await self._fetch_all_data(strategy_config, backtest_config)

            if not symbol_data or not any(symbol_data.values()):
                result.status = "FAILED"
                result.error_message = "No data available for backtest period"
                result.end_time = datetime.utcnow()
                return result

            engine = EventDrivenBacktestEngine(
                initial_capital=backtest_config.initial_capital,
                commission_pct=backtest_config.commission_pct,
                slippage_pct=backtest_config.slippage_pct,
                max_positions=strategy_config.max_positions,
            )
            result.engine = engine

            executor = StrategyExecutor(strategy_config)

            all_candles = self._merge_candles(symbol_data)

            for candle in all_candles:
                symbol_candles_dict = {
                    s: [c for c in candles if c.symbol == s] for s, candles in symbol_data.items()
                }

                equity_updated = False

                entry_signals = executor.evaluate_entry(symbol_candles_dict)
                for symbol, price, qty in entry_signals:
                    signal = BacktestSignal(
                        timestamp=candle.timestamp,
                        symbol=symbol,
                        signal_type=BacktestSignalType.BUY,
                        price=price,
                        quantity=qty,
                        metadata={
                            "stop_loss": strategy_config.stop_loss_pct,
                            "take_profit": strategy_config.take_profit_pct,
                        },
                    )
                    engine.process_bar(candle, signal, update_equity=False)

                exit_symbols = executor.evaluate_exit(symbol_candles_dict)
                for symbol in exit_symbols:
                    if symbol in engine.open_positions:
                        position = engine.open_positions[symbol]
                        signal = BacktestSignal(
                            timestamp=candle.timestamp,
                            symbol=symbol,
                            signal_type=BacktestSignalType.SELL,
                            price=candle.close,
                            quantity=position.entry_quantity,
                            metadata={"reason": "SIGNAL"},
                        )
                        engine.process_bar(candle, signal, update_equity=True)
                        equity_updated = True
                    else:
                        engine.process_bar(candle, update_equity=True)
                        equity_updated = True

                if not equity_updated:
                    engine.process_bar(candle, update_equity=True)

            result.trades = engine.get_closed_trades()

            equity_curve = engine.get_equity_curve()
            result.equity_curve = {
                "timestamps": [t.isoformat() for t in equity_curve.timestamps],
                "equity_values": [float(e) for e in equity_curve.equity_values],
                "daily_returns": [float(r) for r in equity_curve.daily_returns],
            }

            performance_metrics = self.metrics_calculator.calculate(
                equity_history=engine.equity_history,
                trades=result.trades,
                initial_capital=backtest_config.initial_capital,
                final_capital=engine.current_equity,
            )

            result.metrics = {
                "total_return_pct": float(performance_metrics.total_return_pct),
                "cagr_pct": float(performance_metrics.cagr_pct),
                "max_drawdown_pct": float(performance_metrics.max_drawdown_pct),
                "sharpe_ratio": float(performance_metrics.sharpe_ratio),
                "sortino_ratio": float(performance_metrics.sortino_ratio),
                "calmar_ratio": float(performance_metrics.calmar_ratio),
                "winning_trades": performance_metrics.winning_trades,
                "losing_trades": performance_metrics.losing_trades,
                "win_rate_pct": float(performance_metrics.win_rate_pct),
                "profit_factor": float(performance_metrics.profit_factor),
                "recovery_factor": float(performance_metrics.recovery_factor),
                "payoff_ratio": float(performance_metrics.payoff_ratio),
                "avg_trade_duration_hours": float(performance_metrics.avg_trade_duration_hours),
                "volatility_pct": float(performance_metrics.volatility_pct),
                "daily_volatility_pct": float(performance_metrics.daily_volatility_pct),
                "best_day_pct": float(performance_metrics.best_day_pct),
                "worst_day_pct": float(performance_metrics.worst_day_pct),
                "consecutive_wins": performance_metrics.consecutive_wins,
                "consecutive_losses": performance_metrics.consecutive_losses,
                "skewness": float(performance_metrics.skewness),
                "kurtosis": float(performance_metrics.kurtosis),
            }

            result.per_symbol_stats = self._calculate_per_symbol_stats(result.trades)

            result.status = "COMPLETED"

            await self._persist_backtest_result(result)

            logger.info(
                "Backtest completed: %s | Return: %.2f%% | Trades: %d | Sharpe: %.2f",
                backtest_id,
                performance_metrics.total_return_pct,
                len(result.trades),
                performance_metrics.sharpe_ratio,
            )

        except Exception as e:
            result.status = "FAILED"
            result.error_message = str(e)[:500]
            logger.error("Backtest failed: %s | Error: %s", backtest_id, str(e)[:200])

        finally:
            result.end_time = datetime.utcnow()

        return result

    async def _fetch_all_data(
        self,
        strategy: StrategyConfig,
        config: BacktestConfig,
    ) -> dict:
        from exchange.types import MarketType
        import exchange_client

        symbol_data = {}
        failed_symbols = []

        raw_market_type = config.strategy_config.market_type
        if isinstance(raw_market_type, str):
            try:
                market_type_enum = MarketType[raw_market_type.upper()]
            except KeyError:
                logger.error("Invalid market type: %s", raw_market_type)
                return {}
        else:
            market_type_enum = raw_market_type

        # Use exchange_client (CCXT) for data fetching - more reliable than direct HTTP
        timeframe_map = {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "2h": "2h",
            "4h": "4h",
            "6h": "6h",
            "8h": "8h",
            "12h": "12h",
            "1d": "1d",
            "1w": "1w",
            "1M": "1M",
        }

        ccxt_timeframe = timeframe_map.get(strategy.timeframe, strategy.timeframe)

        # Convert start/end dates to timestamp for CCXT
        start_ms = int(config.start_date.timestamp() * 1000) if config.start_date else None

        for symbol in strategy.symbols:
            try:
                # Use exchange_client which uses CCXT - more reliable
                candles = await exchange_client.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=ccxt_timeframe,
                    limit=1500,
                    since=start_ms,
                )

                if candles and len(candles) >= 10:
                    # Convert to OHLCV format
                    from exchange.types import OHLCV

                    ohlcv_data = []
                    for c in candles:
                        ts = c.get("timestamp", datetime.utcnow())
                        # Handle string timestamps from exchange_client
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

                        ohlcv_data.append(
                            OHLCV(
                                symbol=symbol,
                                timestamp=ts,
                                open=Decimal(str(c.get("open", 0))),
                                high=Decimal(str(c.get("high", 0))),
                                low=Decimal(str(c.get("low", 0))),
                                close=Decimal(str(c.get("close", 0))),
                                volume=Decimal(str(c.get("volume", 0))),
                            )
                        )

                    symbol_data[symbol] = ohlcv_data
                    logger.info(
                        "Fetched data for %s | Candles: %d",
                        symbol,
                        len(ohlcv_data),
                    )
                else:
                    logger.warning(
                        "Insufficient data for %s: %d candles",
                        symbol,
                        len(candles) if candles else 0,
                    )
                    failed_symbols.append(symbol)

            except Exception as e:
                logger.error("Error fetching data for %s: %s", symbol, str(e)[:100])
                failed_symbols.append(symbol)

        if failed_symbols:
            logger.warning("Failed to fetch data for symbols: %s", ", ".join(failed_symbols))

        if not symbol_data:
            logger.error("No data could be fetched for any symbol in the strategy")

        return symbol_data

    def _merge_candles(self, symbol_data: dict) -> list:
        all_candles = []

        for symbol, candles in symbol_data.items():
            all_candles.extend(candles)

        all_candles = sorted(all_candles, key=lambda c: c.timestamp)
        return all_candles

    def _calculate_per_symbol_stats(self, trades: list) -> dict:
        stats = {}

        for trade in trades:
            symbol = trade.symbol
            if symbol not in stats:
                stats[symbol] = {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": Decimal("0"),
                    "avg_pnl": Decimal("0"),
                }

            stats[symbol]["total_trades"] += 1
            if trade.realized_pnl > 0:
                stats[symbol]["winning_trades"] += 1
            else:
                stats[symbol]["losing_trades"] += 1
            stats[symbol]["total_pnl"] += trade.net_pnl

        for symbol in stats:
            total = stats[symbol]["total_trades"]
            stats[symbol]["avg_pnl"] = float(stats[symbol]["total_pnl"] / total) if total > 0 else 0
            stats[symbol]["total_pnl"] = float(stats[symbol]["total_pnl"])

        return stats

    async def _persist_backtest_result(self, result: BacktestResult) -> None:
        try:
            async with self.uow as uow:
                await uow.backtests.create(
                    {
                        "id": result.backtest_id,
                        "strategy_id": result.strategy_config.strategy_id,
                        "symbols": json.dumps(result.strategy_config.symbols),
                        "timeframe": result.strategy_config.timeframe,
                        "start_date": result.backtest_config.start_date.isoformat(),
                        "end_date": result.backtest_config.end_date.isoformat(),
                        "initial_capital": float(result.backtest_config.initial_capital),
                        "final_capital": float(result.engine.current_equity)
                        if result.engine
                        else 0,
                        "total_pnl": float(sum(t.net_pnl for t in result.trades)),
                        "total_pnl_pct": float(result.metrics["total_return_pct"])
                        if result.metrics
                        else 0,
                        "status": result.status,
                        "error_message": result.error_message,
                        "equity_curve": json.dumps(result.equity_curve),
                        "per_symbol_stats": json.dumps(result.per_symbol_stats),
                    }
                )
                await uow.commit()
        except Exception as e:
            logger.error("Error persisting backtest result: %s", str(e)[:100])
