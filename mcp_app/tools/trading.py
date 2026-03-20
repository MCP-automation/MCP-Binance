from __future__ import annotations
import logging
import json
from typing import Any
from decimal import Decimal

logger = logging.getLogger(__name__)


class TradingTools:
    def __init__(self, exchange_manager, risk_manager, backtest_runner):
        self.exchange = exchange_manager
        self.risk_manager = risk_manager
        self.backtest_runner = backtest_runner

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: str,
        market_type: str,
        stop_loss_pct: str,
        take_profit_pct: str,
    ) -> dict:
        from exchange.types import OrderSide, OrderType, OrderRequest, MarketType

        try:
            quantity_dec = Decimal(quantity)
            stop_loss_pct_dec = Decimal(stop_loss_pct) if stop_loss_pct else None
            take_profit_pct_dec = Decimal(take_profit_pct) if take_profit_pct else None

            market_type_enum = MarketType[market_type]
            side_enum = OrderSide[side.upper()]

            ticker = await self.exchange.get_ticker(market_type_enum, symbol)
            entry_price = ticker.last

            is_valid, msg, _ = await self.risk_manager.validate_order_pre_placement(
                symbol=symbol,
                entry_price=entry_price,
                stop_loss_price=entry_price * (Decimal("1") - stop_loss_pct_dec / Decimal("100"))
                if stop_loss_pct_dec
                else entry_price * Decimal("0.95"),
                quantity=quantity_dec,
            )

            if not is_valid:
                return {
                    "success": False,
                    "error": f"Order validation failed: {msg}",
                    "order_id": None,
                }

            order_request = OrderRequest(
                symbol=symbol,
                side=side_enum,
                order_type=OrderType.MARKET,
                quantity=quantity_dec,
            )

            order = await self.exchange.place_order(market_type_enum, order_request)

            await self.risk_manager.register_executed_order(
                order=order,
                stop_loss_price=entry_price
                * (Decimal("1") - stop_loss_pct_dec / Decimal("100"))
                if stop_loss_pct_dec
                else entry_price * Decimal("0.95"),
                take_profit_price=entry_price
                * (Decimal("1") + take_profit_pct_dec / Decimal("100"))
                if take_profit_pct_dec
                else entry_price * Decimal("1.05"),
            )

            logger.info("Order placed: %s | Side: %s | Qty: %s | Price: %.2f", symbol, side, quantity, entry_price)

            return {
                "success": True,
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "price": str(entry_price),
                "status": order.status.value,
            }

        except Exception as e:
            logger.error("Error placing order: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
                "order_id": None,
            }

    async def get_positions(self, market_type: str) -> dict:
        from exchange.types import MarketType

        try:
            market_type_enum = MarketType[market_type]
            positions = await self.exchange.get_positions(market_type_enum)

            return {
                "success": True,
                "source": "exchange",
                "market_type": market_type,
                "positions": [
                    {
                        "symbol": pos.symbol,
                        "quantity": str(pos.quantity),
                        "entry_price": str(pos.entry_price),
                        "current_price": str(pos.current_price),
                        "unrealized_pnl": str(pos.unrealized_pnl),
                        "unrealized_pnl_pct": str(pos.unrealized_pnl_pct),
                    }
                    for pos in positions
                ],
                "total_positions": len(positions),
            }

        except Exception as e:
            # API auth failed — fall back to locally tracked paper positions
            logger.warning(
                "Exchange API unavailable (%s). Returning paper positions from risk manager.",
                str(e)[:120],
            )
            paper_positions = self.risk_manager.get_active_positions()
            positions_list = [
                {
                    "symbol": sym,
                    "quantity": str(pos.quantity),
                    "entry_price": str(pos.entry_price),
                    "current_price": str(pos.entry_price),
                    "unrealized_pnl": "0",
                    "unrealized_pnl_pct": "0",
                    "stop_loss_price": str(pos.stop_loss_price),
                    "take_profit_price": str(pos.take_profit_price),
                    "max_loss_amount": str(pos.max_loss_amount),
                    "risk_reward_ratio": str(pos.risk_reward_ratio),
                }
                for sym, pos in paper_positions.items()
            ]
            return {
                "success": True,
                "source": "paper_trading",
                "market_type": market_type,
                "positions": positions_list,
                "total_positions": len(positions_list),
                "note": "Live exchange API unavailable — showing locally tracked paper positions.",
            }

    async def close_position(
        self,
        symbol: str,
        exit_price: str,
        exit_reason: str = "MANUAL",
    ) -> dict:
        from exchange.types import MarketType

        try:
            exit_price_dec = Decimal(exit_price)
            positions = await self.exchange.get_all_positions_across_markets()

            found_position = None
            market_type = None

            for market, pos_list in positions.items():
                for pos in pos_list:
                    if pos.symbol == symbol:
                        found_position = pos
                        market_type = market
                        break

            if not found_position:
                return {
                    "success": False,
                    "error": f"No position found for {symbol}",
                }

            await self.risk_manager.close_position(
                symbol=symbol,
                exit_price=exit_price_dec,
                quantity=found_position.quantity,
                exit_reason=exit_reason,
            )

            logger.info("Position closed: %s | Exit price: %.2f | Reason: %s", symbol, exit_price_dec, exit_reason)

            return {
                "success": True,
                "symbol": symbol,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
            }

        except Exception as e:
            logger.error("Error closing position: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
            }

    async def get_risk_metrics(self) -> dict:
        try:
            metrics = self.risk_manager.get_risk_metrics()
            summary = self.risk_manager.get_summary()

            return {
                "success": True,
                "metrics": {
                    "account_equity": str(metrics.account_equity),
                    "total_risk_exposure": str(metrics.total_risk_exposure),
                    "total_risk_pct": str(metrics.total_risk_pct),
                    "open_positions": metrics.open_positions_count,
                    "daily_loss": str(metrics.daily_loss_realized),
                    "daily_loss_pct": str(metrics.daily_loss_pct),
                    "drawdown_pct": str(metrics.drawdown_pct),
                    "is_within_limits": metrics.is_within_limits,
                    "breached_limits": metrics.breached_limits,
                },
                "summary": summary,
            }

        except Exception as e:
            logger.error("Error getting risk metrics: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
            }

    async def run_backtest(
        self,
        strategy_name: str,
        timeframe: str,
        symbols: str,
        entry_condition: str,
        exit_condition: str,
        stop_loss_pct: str,
        take_profit_pct: str,
        start_date: str,
        end_date: str,
        initial_capital: str,
    ) -> dict:
        from backtesting import StrategyConfigBuilder, BacktestConfig
        from datetime import datetime

        try:
            symbols_list = [s.strip() for s in symbols.split(",")]
            initial_capital_dec = Decimal(initial_capital)
            stop_loss_dec = Decimal(stop_loss_pct) if stop_loss_pct else None
            take_profit_dec = Decimal(take_profit_pct) if take_profit_pct else None

            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)

            strategy = (
                StrategyConfigBuilder()
                .set_name(strategy_name)
                .set_timeframe(timeframe)
                .set_symbols(symbols_list)
                .set_entry_condition(entry_condition)
                .set_exit_condition(exit_condition)
            )

            if stop_loss_dec:
                strategy.set_stop_loss(stop_loss_dec)
            if take_profit_dec:
                strategy.set_take_profit(take_profit_dec)

            strategy_config = strategy.build()

            config = BacktestConfig(
                strategy_config=strategy_config,
                initial_capital=initial_capital_dec,
                start_date=start_dt,
                end_date=end_dt,
            )

            result = await self.backtest_runner.run_backtest(strategy_config, config)

            return {
                "success": result.status == "COMPLETED",
                "backtest_id": result.backtest_id,
                "status": result.status,
                "error": result.error_message,
                "metrics": result.metrics if result.metrics else {},
                "trades_count": len(result.trades),
                "per_symbol_stats": result.per_symbol_stats,
            }

        except Exception as e:
            logger.error("Error running backtest: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
            }

    async def calculate_position_size(
        self,
        symbol: str,
        entry_price: str,
        stop_loss_price: str,
        take_profit_price: str,
        sizing_method: str = "FIXED_PERCENTAGE",
        win_rate: str = "55",
    ) -> dict:
        from risk.sizing import SizingMethod

        try:
            entry_dec = Decimal(entry_price)
            stop_loss_dec = Decimal(stop_loss_price)
            take_profit_dec = Decimal(take_profit_price)
            win_rate_dec = Decimal(win_rate)

            method = SizingMethod[sizing_method]

            result = self.risk_manager.calculate_position_size(
                symbol=symbol,
                entry_price=entry_dec,
                stop_loss_price=stop_loss_dec,
                take_profit_price=take_profit_dec,
                method=method,
                win_rate_pct=win_rate_dec,
            )

            return {
                "success": True,
                "symbol": symbol,
                "quantity": str(result.quantity),
                "risk_amount": str(result.risk_amount),
                "method": result.method.value,
                "reasoning": result.reasoning,
            }

        except Exception as e:
            logger.error("Error calculating position size: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
            }
