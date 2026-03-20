from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, Any, Dict, Callable
from dataclasses import dataclass, field
import uuid
import json

from exchange.types import OHLCV

logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    strategy_id: str
    name: str
    version: int
    description: str
    timeframe: str
    market_type: str
    symbols: list[str]
    entry_condition: str
    exit_condition: str
    stop_loss_pct: Optional[Decimal] = None
    take_profit_pct: Optional[Decimal] = None
    trailing_stop_pct: Optional[Decimal] = None
    position_size_pct: Decimal = Decimal("2")
    max_positions: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BacktestConfig:
    strategy_config: StrategyConfig
    initial_capital: Decimal
    start_date: datetime
    end_date: datetime
    commission_pct: Decimal = Decimal("0.1")
    slippage_pct: Decimal = Decimal("0.05")
    reinvest_profits: bool = False
    max_drawdown_limit_pct: Optional[Decimal] = None
    daily_loss_limit_pct: Optional[Decimal] = None


class StrategyConfigBuilder:
    def __init__(self):
        self.strategy_id = str(uuid.uuid4())
        self.name = ""
        self.version = 1
        self.description = ""
        self.timeframe = "1h"
        self.market_type = "USDM_FUTURES"
        self.symbols = []
        self.entry_condition = ""
        self.exit_condition = ""
        self.stop_loss_pct: Optional[Decimal] = None
        self.take_profit_pct: Optional[Decimal] = None
        self.trailing_stop_pct: Optional[Decimal] = None
        self.position_size_pct = Decimal("2")
        self.max_positions = 10
        self.metadata: Dict[str, Any] = {}

    def set_name(self, name: str) -> StrategyConfigBuilder:
        self.name = name
        return self

    def set_description(self, description: str) -> StrategyConfigBuilder:
        self.description = description
        return self

    def set_timeframe(self, timeframe: str) -> StrategyConfigBuilder:
        self.timeframe = timeframe
        return self

    def set_market_type(self, market_type: str) -> StrategyConfigBuilder:
        self.market_type = market_type
        return self

    def set_symbols(self, symbols: list[str]) -> StrategyConfigBuilder:
        self.symbols = symbols
        return self

    def set_entry_condition(self, condition: str) -> StrategyConfigBuilder:
        self.entry_condition = condition
        return self

    def set_exit_condition(self, condition: str) -> StrategyConfigBuilder:
        self.exit_condition = condition
        return self

    def set_stop_loss(self, pct: Decimal) -> StrategyConfigBuilder:
        self.stop_loss_pct = pct
        return self

    def set_take_profit(self, pct: Decimal) -> StrategyConfigBuilder:
        self.take_profit_pct = pct
        return self

    def set_trailing_stop(self, pct: Decimal) -> StrategyConfigBuilder:
        self.trailing_stop_pct = pct
        return self

    def set_position_size(self, pct: Decimal) -> StrategyConfigBuilder:
        self.position_size_pct = pct
        return self

    def set_max_positions(self, max_pos: int) -> StrategyConfigBuilder:
        self.max_positions = max_pos
        return self

    def add_metadata(self, key: str, value: Any) -> StrategyConfigBuilder:
        self.metadata[key] = value
        return self

    def build(self) -> StrategyConfig:
        if not self.name:
            raise ValueError("Strategy name is required")
        if not self.entry_condition:
            raise ValueError("Entry condition is required")
        if not self.exit_condition:
            raise ValueError("Exit condition is required")
        if not self.symbols:
            raise ValueError("At least one symbol is required")

        return StrategyConfig(
            strategy_id=self.strategy_id,
            name=self.name,
            version=self.version,
            description=self.description,
            timeframe=self.timeframe,
            market_type=self.market_type,
            symbols=self.symbols,
            entry_condition=self.entry_condition,
            exit_condition=self.exit_condition,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            trailing_stop_pct=self.trailing_stop_pct,
            position_size_pct=self.position_size_pct,
            max_positions=self.max_positions,
            metadata=self.metadata,
        )


class StrategyExecutor:
    def __init__(self, strategy_config: StrategyConfig):
        self.config = strategy_config
        self.last_candle: Dict[str, OHLCV] = {}

    def evaluate_entry(self, candles: Dict[str, list[OHLCV]]) -> list[tuple[str, Decimal, Decimal]]:
        signals = []

        for symbol, symbol_candles in candles.items():
            if not symbol_candles:
                continue

            self.last_candle[symbol] = symbol_candles[-1]

            entry_signal = self._evaluate_condition(
                self.config.entry_condition,
                symbol_candles,
                symbol,
            )

            if entry_signal:
                current_price = symbol_candles[-1].close
                qty = self._calculate_position_size(current_price)
                signals.append((symbol, current_price, qty))
                logger.info(
                    "Entry signal: %s | Price: %.2f | Qty: %.4f", symbol, current_price, qty
                )

        return signals

    def evaluate_exit(self, candles: Dict[str, list[OHLCV]]) -> list[str]:
        symbols_to_exit = []

        for symbol, symbol_candles in candles.items():
            if not symbol_candles:
                continue

            exit_signal = self._evaluate_condition(
                self.config.exit_condition,
                symbol_candles,
                symbol,
            )

            if exit_signal:
                symbols_to_exit.append(symbol)
                logger.info("Exit signal: %s | Price: %.2f", symbol, symbol_candles[-1].close)

        return symbols_to_exit

    def _evaluate_condition(
        self,
        condition: str,
        candles: list[OHLCV],
        symbol: str,
    ) -> bool:
        if not candles or len(candles) < 2:
            return False

        current = candles[-1]
        previous = candles[-2]

        context = {
            "symbol": symbol,
            "open": float(current.open),
            "high": float(current.high),
            "low": float(current.low),
            "close": float(current.close),
            "volume": float(current.volume),
            "price": float(current.close),
            "current_open": float(current.open),
            "current_high": float(current.high),
            "current_low": float(current.low),
            "current_close": float(current.close),
            "current_volume": float(current.volume),
            "previous_open": float(previous.open),
            "previous_high": float(previous.high),
            "previous_low": float(previous.low),
            "previous_close": float(previous.close),
            "previous_volume": float(previous.volume),
        }

        if len(candles) >= 10:
            sma_10 = sum(c.close for c in candles[-10:]) / 10
            context["sma_10"] = float(sma_10)

        if len(candles) >= 20:
            sma_20 = sum(c.close for c in candles[-20:]) / 20
            context["sma_20"] = float(sma_20)

        def ema(period: int) -> float:
            if len(candles) < period:
                return float(current.close)
            prices = [float(c.close) for c in candles[-period:]]
            k = 2.0 / (period + 1)
            result = prices[0]
            for p in prices[1:]:
                result = p * k + result * (1 - k)
            return result

        def sma(period: int) -> float:
            if len(candles) < period:
                return float(current.close)
            return float(sum(c.close for c in candles[-period:]) / period)

        context["ema"] = ema
        context["sma"] = sma

        try:
            result = eval(condition, {"__builtins__": {}}, context)
            return bool(result)
        except Exception as e:
            logger.error("Error evaluating condition for %s: %s", symbol, str(e)[:100])
            return False

    def _calculate_position_size(self, current_price: Decimal) -> Decimal:
        position_qty = (
            (Decimal("10000") * self.config.position_size_pct / Decimal("100")) / current_price
        ).quantize(Decimal("0.0001"))
        return position_qty


class StrategyVersionControl:
    def __init__(self, uow):
        self.uow = uow
        self.strategies: Dict[str, list[StrategyConfig]] = {}

    async def save_strategy(self, strategy: StrategyConfig) -> None:
        if strategy.strategy_id not in self.strategies:
            self.strategies[strategy.strategy_id] = []

        existing = self.strategies[strategy.strategy_id]

        if existing and existing[-1].version >= strategy.version:
            strategy.version = existing[-1].version + 1

        self.strategies[strategy.strategy_id].append(strategy)

        try:
            async with self.uow as uow:
                await uow.strategies.create(
                    {
                        "id": strategy.strategy_id,
                        "version": strategy.version,
                        "name": strategy.name,
                        "description": strategy.description,
                        "timeframe": strategy.timeframe,
                        "market_type": strategy.market_type,
                        "is_active": True,
                        "raw_config": json.dumps(
                            {
                                "symbols": strategy.symbols,
                                "entry_condition": strategy.entry_condition,
                                "exit_condition": strategy.exit_condition,
                                "stop_loss_pct": float(strategy.stop_loss_pct)
                                if strategy.stop_loss_pct
                                else None,
                                "take_profit_pct": float(strategy.take_profit_pct)
                                if strategy.take_profit_pct
                                else None,
                                "trailing_stop_pct": float(strategy.trailing_stop_pct)
                                if strategy.trailing_stop_pct
                                else None,
                                "position_size_pct": float(strategy.position_size_pct),
                                "max_positions": strategy.max_positions,
                                "metadata": strategy.metadata,
                            }
                        ),
                    }
                )
                await uow.commit()
        except Exception as e:
            logger.error("Error saving strategy to database: %s", str(e)[:100])

    async def get_strategy(
        self, strategy_id: str, version: Optional[int] = None
    ) -> Optional[StrategyConfig]:
        if strategy_id not in self.strategies:
            return None

        versions = self.strategies[strategy_id]
        if not versions:
            return None

        if version is None:
            return versions[-1]

        for strat in versions:
            if strat.version == version:
                return strat

        return None

    async def list_strategy_versions(self, strategy_id: str) -> list[StrategyConfig]:
        return self.strategies.get(strategy_id, [])
