"""MCP server runner – exposes all trading tools over stdio transport."""

from __future__ import annotations

import asyncio
import logging
import json
import os
import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, Any
from dotenv import load_dotenv

# Load environment variables (.env must override any stale system-level vars)
load_dotenv(override=True)

import numpy as np

import exchange_client
from exchange_client import TF_MS as _TF_MS  # timeframe → ms, used for deciding paginated fetch

logger = logging.getLogger(__name__)


def _safe_str(val, default="0") -> str:
    """Convert val to str, returning default on None or any error."""
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


def _safe_val(val, default=0):
    """Return val if not None, else default. Swallows conversion errors."""
    try:
        return val if val is not None else default
    except Exception:
        return default


_RISK_METRICS_DEFAULTS = {
    "account_equity": "0",
    "total_risk_exposure": "0",
    "total_risk_pct": "0",
    "open_positions": 0,
    "daily_loss": "0",
    "daily_loss_pct": "0",
    "drawdown_pct": "0",
    "is_within_limits": True,
    "breached_limits": [],
    "summary": {},
}


# ---------------------------------------------------------------------------
# EMA helper (used by futures backtest)
# ---------------------------------------------------------------------------


def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    result = np.zeros(len(prices))
    k = 2.0 / (period + 1)
    result[0] = prices[0]
    for i in range(1, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)
    return result


def _sma(prices: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        result[i] = np.mean(prices[i - period + 1 : i + 1])
    return result


def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))
    if len(gains) >= period:
        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])
        for i in range(period + 1, len(prices)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = np.where(avg_loss == 0, 100.0, rsi)  # all gains → RSI = 100
    return rsi


# ---------------------------------------------------------------------------
# Strategy simulation helper (shared by single and multi-symbol backtests)
# ---------------------------------------------------------------------------


def _simulate_strategy(
    closes: np.ndarray,
    volumes: np.ndarray,
    strategy_name: str,
    lev: int,
    balance: float,
    highs: np.ndarray = None,
    lows: np.ndarray = None,
) -> dict:
    """Generate signals and simulate trades on pre-fetched OHLCV arrays.

    Returns a metrics dict with: total_trades, winning_trades, losing_trades,
    win_rate, total_return, max_drawdown, sharpe_ratio, final_equity,
    avg_pnl_per_trade, sample_trades.
    """
    signals = np.zeros(len(closes))
    strat = strategy_name.lower()

    if strat in ("ema_crossover", "ema"):
        fast_ema = _ema(closes, 9)
        slow_ema = _ema(closes, 21)
        for i in range(21, len(closes)):
            if fast_ema[i] > slow_ema[i] and fast_ema[i - 1] <= slow_ema[i - 1]:
                signals[i] = 1
            elif fast_ema[i] < slow_ema[i] and fast_ema[i - 1] >= slow_ema[i - 1]:
                signals[i] = -1

    elif strat == "momentum":
        period = 20
        for i in range(period, len(closes)):
            mom = (closes[i] - closes[i - period]) / closes[i - period]
            vol_ratio = volumes[i] / (np.mean(volumes[i - period : i]) + 1e-9)
            if mom > 0.02 and vol_ratio > 1.5:
                signals[i] = 1
            elif mom < -0.02 and vol_ratio > 1.5:
                signals[i] = -1

    elif strat in ("mean_reversion", "rsi"):
        rsi_vals = _rsi(closes, 14)
        for i in range(15, len(closes)):
            if rsi_vals[i] < 30 and rsi_vals[i - 1] >= 30:
                signals[i] = 1
            elif rsi_vals[i] > 70 and rsi_vals[i - 1] <= 70:
                signals[i] = -1

    elif strat in ("btc_trend", "btc_trend_v2"):
        # ── Strategy 1 & 2: EMA50/200 trend-follow + ATR breakout + RSI + volume
        # strategy1 (btc_trend): ATR/close > 0.008, volume > 1.05x — more signals
        # strategy2 (btc_trend_v2): ATR/close > 0.015, volume > 1.2x — stricter
        atr_thresh  = 0.008 if strat == "btc_trend" else 0.015
        vol_mult    = 1.05  if strat == "btc_trend" else 1.20

        ema50  = _ema(closes, 50)
        ema200 = _ema(closes, 200)

        # ATR(14): use high/low if available, else approximate from close-to-close
        if highs is not None and lows is not None:
            tr = np.maximum(highs - lows,
                 np.maximum(np.abs(highs - np.roll(closes, 1)),
                            np.abs(lows  - np.roll(closes, 1))))
            tr[0] = highs[0] - lows[0]
        else:
            tr = np.abs(np.diff(closes, prepend=closes[0]))
        atr14 = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(closes)]

        # RSI(14)
        rsi_arr = _rsi(closes, 14)

        # Highest-high of last 20 bars (shifted 1 to avoid lookahead)
        hh20 = np.full(len(closes), np.nan)
        if highs is not None:
            for i in range(20, len(closes)):
                hh20[i] = np.max(highs[i - 20 : i])
        else:
            for i in range(20, len(closes)):
                hh20[i] = np.max(closes[i - 20 : i])

        # Volume MA(20)
        vol_ma20 = np.convolve(volumes, np.ones(20) / 20, mode="full")[:len(closes)]

        for i in range(200, len(closes)):
            if np.isnan(hh20[i]) or np.isnan(rsi_arr[i]):
                continue
            bull_regime  = ema50[i] > ema200[i]
            high_atr     = (atr14[i] / (closes[i] + 1e-9)) > atr_thresh
            breakout     = closes[i] > hh20[i]
            not_overbought = rsi_arr[i] < 70
            high_volume  = volumes[i] > vol_mult * vol_ma20[i]

            if bull_regime and high_atr and breakout and not_overbought and high_volume:
                signals[i] = 1   # LONG only

    elif strat == "futures_trend":
        # ── Strategy 3: Futures long+short, slippage + funding rate baked in
        # Long:  EMA50>EMA200 + ATR breakout + close>HH20 + RSI<70 + vol spike
        # Short: EMA50<EMA200 + ATR breakout + close<LL20 + RSI>30 + vol spike
        ema50  = _ema(closes, 50)
        ema200 = _ema(closes, 200)

        if highs is not None and lows is not None:
            tr = np.maximum(highs - lows,
                 np.maximum(np.abs(highs - np.roll(closes, 1)),
                            np.abs(lows  - np.roll(closes, 1))))
            tr[0] = highs[0] - lows[0]
        else:
            tr = np.abs(np.diff(closes, prepend=closes[0]))
        atr14 = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(closes)]

        rsi_arr  = _rsi(closes, 14)
        vol_ma20 = np.convolve(volumes, np.ones(20) / 20, mode="full")[:len(closes)]

        hh20 = np.full(len(closes), np.nan)
        ll20 = np.full(len(closes), np.nan)
        src_h = highs  if highs  is not None else closes
        src_l = lows   if lows   is not None else closes
        for i in range(20, len(closes)):
            hh20[i] = np.max(src_h[i - 20 : i])
            ll20[i] = np.min(src_l[i - 20 : i])

        slippage     = 0.0003
        funding_rate = 0.0001   # per 8h

        in_trade   = False
        direction  = 0
        ep         = 0.0
        stop_p     = 0.0
        tgt_p      = 0.0
        bars_held  = 0
        units_t    = 0.0
        equity_t   = balance

        for i in range(200, len(closes)):
            if np.isnan(hh20[i]) or np.isnan(rsi_arr[i]):
                signals[i] = 0
                continue

            if not in_trade:
                high_atr    = (atr14[i] / (closes[i] + 1e-9)) > 0.008
                high_vol    = volumes[i] > 1.1 * vol_ma20[i]
                long_sig    = (ema50[i] > ema200[i] and closes[i] > hh20[i]
                               and rsi_arr[i] < 70 and high_atr and high_vol)
                short_sig   = (ema50[i] < ema200[i] and closes[i] < ll20[i]
                               and rsi_arr[i] > 30 and high_atr and high_vol)

                if long_sig:
                    direction = 1
                    ep = closes[i] * (1 + slippage)
                    sd = 1.5 * atr14[i]
                    stop_p = ep - sd
                    tgt_p  = ep + 3 * sd
                    units_t = (equity_t * 0.01) / sd
                    in_trade = True
                    bars_held = 0
                    signals[i] = 1
                elif short_sig:
                    direction = -1
                    ep = closes[i] * (1 - slippage)
                    sd = 1.5 * atr14[i]
                    stop_p = ep + sd
                    tgt_p  = ep - 3 * sd
                    units_t = (equity_t * 0.01) / sd
                    in_trade = True
                    bars_held = 0
                    signals[i] = -1
            else:
                bars_held += 1
                h_i = highs[i] if highs is not None else closes[i]
                l_i = lows[i]  if lows  is not None else closes[i]

                exit_now = False
                if direction == 1:
                    if l_i <= stop_p:
                        exit_now = True
                    elif h_i >= tgt_p:
                        exit_now = True
                else:
                    if h_i >= stop_p:
                        exit_now = True
                    elif l_i <= tgt_p:
                        exit_now = True

                if exit_now:
                    xp = stop_p if (direction == 1 and l_i <= stop_p) or \
                                   (direction == -1 and h_i >= stop_p) else tgt_p
                    if direction == 1:
                        xp *= (1 - slippage)
                        raw_pnl = (xp - ep) * units_t
                    else:
                        xp *= (1 + slippage)
                        raw_pnl = (ep - xp) * units_t
                    raw_pnl -= abs(xp * units_t) * 0.0004
                    raw_pnl -= abs(ep * units_t) * funding_rate * (bars_held / 8)
                    equity_t += raw_pnl
                    in_trade = False
                    signals[i] = -direction  # mark exit

    else:  # sma_crossover
        sma_f = _sma(closes, 10)
        sma_s = _sma(closes, 30)
        for i in range(30, len(closes)):
            if not np.isnan(sma_f[i]) and not np.isnan(sma_s[i]):
                if sma_f[i] > sma_s[i] and sma_f[i - 1] <= sma_s[i - 1]:
                    signals[i] = 1
                elif sma_f[i] < sma_s[i] and sma_f[i - 1] >= sma_s[i - 1]:
                    signals[i] = -1

    # Trade simulation (1 position at a time, long & short)
    equity = balance
    position = 0
    entry_price = 0.0
    entry_qty = 0.0
    margin_used = 0.0
    trades: list = []
    equity_curve = [equity]
    commission_rate = 0.0004
    sl_pct = 0.02 / lev
    tp_pct = 0.04 / lev

    for i in range(1, len(closes)):
        price = closes[i]

        if position != 0:
            price_chg = (
                (price - entry_price) / entry_price
                if position == 1
                else (entry_price - price) / entry_price
            )
            close_reason = ""
            if price_chg <= -sl_pct:
                close_reason = "SL"
            elif price_chg >= tp_pct:
                close_reason = "TP"
            elif (position == 1 and signals[i] == -1) or (position == -1 and signals[i] == 1):
                close_reason = "SIGNAL"

            if close_reason:
                net_pnl = price_chg * lev * margin_used - entry_qty * price * commission_rate
                equity += net_pnl + margin_used
                trades.append(
                    {
                        "side": "LONG" if position == 1 else "SHORT",
                        "entry_price": round(entry_price, 6),
                        "exit_price": round(price, 6),
                        "quantity": round(entry_qty, 6),
                        "pnl": round(net_pnl, 4),
                        "pnl_pct": round(price_chg * lev * 100, 4),
                        "close_reason": close_reason,
                    }
                )
                position = 0

        if position == 0 and signals[i] != 0:
            margin_used = equity * 0.10
            entry_price = price
            entry_qty = (margin_used * lev) / price
            fee = entry_qty * price * commission_rate
            if margin_used + fee <= equity:
                equity -= margin_used + fee
                position = 1 if signals[i] == 1 else -1

        equity_curve.append(round(equity, 4))

    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "final_equity": round(equity, 2),
            "avg_pnl_per_trade": 0.0,
            "sample_trades": [],
        }

    winning = [t for t in trades if t["pnl"] > 0]
    total_return = (equity - balance) / balance * 100

    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    arr = np.array(equity_curve)
    rets = np.diff(arr) / (arr[:-1] + 1e-9)
    sharpe = (
        float(np.mean(rets) / np.std(rets) * np.sqrt(252))
        if len(rets) > 1 and np.std(rets) > 0
        else 0.0
    )

    return {
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(trades) - len(winning),
        "win_rate": round(len(winning) / len(trades) * 100, 2),
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 4),
        "final_equity": round(equity, 2),
        "avg_pnl_per_trade": round(sum(t["pnl"] for t in trades) / len(trades), 4),
        "sample_trades": trades[:10],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class MCPServerRunner:
    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self.exchange = ctx.exchange_manager
        self.risk_manager = ctx.risk_manager
        self.backtest_runner = ctx.backtest_runner

        # Lazy-init ccxt client and paper session manager
        self._ccxt_client: Optional[Any] = None

        from exchange.paper_session import PaperSessionManager
        from trading.autonomous_engine import BotManager

        self._paper_manager = PaperSessionManager()
        self._bot_manager   = BotManager()

    # ------------------------------------------------------------------
    # MCP server lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        logger.info("MCP Trading Server initialised and ready")

        from mcp.server import Server, NotificationOptions
        from mcp.server.models import InitializationOptions
        import mcp.server.stdio
        from mcp_app.protocol import MCPResourcesHandler, MCPIntegrationHandler
        from mcp.types import Tool, TextContent

        server = Server("binance-trading-mcp")
        integration_handler = MCPIntegrationHandler(self)

        @server.list_tools()
        async def list_tools() -> list:
            tools_info = MCPResourcesHandler.get_resources()["tools"]
            return [
                Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in tools_info
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            try:
                result = await integration_handler.handle_tool_call(name, arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except asyncio.CancelledError:
                logger.warning("Tool call cancelled: %s", name)
                raise
            except Exception as e:
                logger.error("Error executing tool %s: %s", name, str(e)[:200])
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"success": False, "error": str(e)[:500]}),
                    )
                ]

        options = InitializationOptions(
            server_name="binance-trading-mcp",
            server_version="2.0.0",
            capabilities=server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            logger.info("Starting stdio MCP server loop…")
            try:
                await server.run(read_stream, write_stream, options)
            except BrokenPipeError:
                logger.warning("MCP client disconnected (broken pipe)")
            except ConnectionResetError:
                logger.warning("MCP client disconnected (connection reset)")
            except asyncio.CancelledError:
                logger.info("MCP server loop cancelled")
            except Exception as e:
                logger.error("MCP server error: %s", str(e)[:200])

    # ------------------------------------------------------------------
    # ccxt lazy initialiser
    # ------------------------------------------------------------------

    async def _get_ccxt(self):
        if self._ccxt_client is None or not self._ccxt_client._initialized:
            import os
            from exchange.ccxt_client import CCXTFuturesClient

            config = self._ctx.config
            vault = self._ctx.vault

            if config.binance_api.testnet_enabled:
                api_key = (
                    os.getenv("BINANCE_API_KEY")
                    or vault.get("BINANCE_TESTNET_API_KEY")
                    or vault.get("binance_testnet_api_key")
                    or ""
                )
                api_secret = (
                    os.getenv("BINANCE_API_SECRET")
                    or vault.get("BINANCE_TESTNET_API_SECRET")
                    or vault.get("binance_testnet_api_secret")
                    or ""
                )
            else:
                api_key = (
                    os.getenv("BINANCE_API_KEY")
                    or vault.get("BINANCE_FUTURES_API_KEY")
                    or vault.get("BINANCE_LIVE_API_KEY")
                    or vault.get("binance_live_api_key")
                    or ""
                )
                api_secret = (
                    os.getenv("BINANCE_API_SECRET")
                    or vault.get("BINANCE_FUTURES_API_SECRET")
                    or vault.get("BINANCE_LIVE_API_SECRET")
                    or vault.get("binance_live_api_secret")
                    or ""
                )

            # Initialize first, then store — so a failed init doesn't cache
            # a broken client and block all future retries.
            client = CCXTFuturesClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=config.binance_api.testnet_enabled,
            )
            await client.initialize()
            self._ccxt_client = client

        return self._ccxt_client

    # ==================================================================
    # SECTION 0 — ORIGINAL TOOLS (unchanged)
    # ==================================================================

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        market_type: str,
        leverage: Optional[str] = None,
        quantity: Optional[str] = None,
        usdt_amount: Optional[str] = None,
        stop_loss_pct: Optional[str] = None,
        take_profit_pct: Optional[str] = None,
    ) -> dict:
        try:
            sl_pct = Decimal(stop_loss_pct) if stop_loss_pct else Decimal("2")
            tp_pct = Decimal(take_profit_pct) if take_profit_pct else Decimal("5")

            ccxt_client = await self._get_ccxt()

            lev = max(1, min(int(leverage), 125)) if leverage else 1
            if leverage:
                try:
                    await ccxt_client.set_leverage(symbol, lev)
                    logger.info("Leverage set: %s → %dx", symbol, lev)
                except Exception as lev_err:
                    logger.warning("set_leverage warning (non-fatal): %s", str(lev_err)[:120])

            ticker = await exchange_client.fetch_ticker(symbol)
            entry_price = Decimal(str(ticker["last_price"]))

            if not quantity and not usdt_amount:
                acct = await ccxt_client.get_account_balance()
                avail = Decimal(str(acct.get("available_balance", "0")))
                if avail <= 0:
                    return {"success": False, "error": "No available balance in account", "order_id": None}
                usdt_margin = avail * Decimal("0.95")
                notional = usdt_margin * Decimal(str(lev))
                raw_qty = float(notional / entry_price)
            elif usdt_amount and not quantity:
                usdt_margin = Decimal(usdt_amount)
                notional = usdt_margin * Decimal(str(lev))
                raw_qty = float(notional / entry_price)
            else:
                raw_qty = float(Decimal(quantity))

            ccxt_sym = ccxt_client._to_ccxt_symbol(symbol)
            qty = Decimal(str(ccxt_client._exchange.amount_to_precision(ccxt_sym, raw_qty)))

            if qty <= 0:
                return {"success": False, "error": "Computed quantity is zero — balance too small for this symbol's minimum lot size", "order_id": None}

            sl_price = entry_price * (Decimal("1") - sl_pct / Decimal("100"))
            tp_price = entry_price * (Decimal("1") + tp_pct / Decimal("100"))

            if side.upper() == "SELL":
                sl_price = entry_price * (Decimal("1") + sl_pct / Decimal("100"))
                tp_price = entry_price * (Decimal("1") - tp_pct / Decimal("100"))

            order = await ccxt_client.place_market_order(symbol, side, float(qty))

            logger.info(
                "Market order filled: %s %s qty=%s price=%s lev=%dx", side, symbol, qty, order.price, lev
            )
            return {
                "success": True,
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side.upper(),
                "leverage": lev,
                "quantity": str(order.quantity),
                "filled_price": str(order.price),
                "notional_usdt": str(float(qty) * float(order.price)),
                "stop_loss_price": str(sl_price),
                "take_profit_price": str(tp_price),
                "status": order.status.value,
            }

        except Exception as e:
            logger.error("place_market_order error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200], "order_id": None}

    async def get_positions(self, market_type: str) -> dict:
        from exchange.types import MarketType

        try:
            market_type_enum = MarketType[market_type.upper()]
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
            logger.warning(
                "Exchange API unavailable (%s). Returning paper positions.",
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
        try:
            ccxt_client = await self._get_ccxt()

            # 1. Check if an open position exists before attempting to close
            position = await ccxt_client.fetch_open_position(symbol)
            if not position:
                logger.warning("close_position: no open position for %s", symbol)
                return {
                    "success": False,
                    "error": f"No open position found for {symbol}",
                    "symbol": symbol,
                }

            # 2. Close on Binance via market order with reduceOnly
            close_result = await ccxt_client.close_position_market(symbol)

            # 2. Use actual fill price if available, otherwise use the provided exit_price
            actual_price = close_result.get("avg_price") or exit_price
            exit_price_dec = Decimal(str(actual_price))
            quantity_dec = Decimal(str(close_result["quantity"]))

            # 3. Update risk manager tracking
            await self.risk_manager.close_position(
                symbol=symbol,
                exit_price=exit_price_dec,
                quantity=quantity_dec,
                exit_reason=exit_reason,
            )

            logger.info(
                "Position closed on exchange: %s | Price: %s | Reason: %s",
                symbol,
                actual_price,
                exit_reason,
            )
            return {
                "success": True,
                "symbol": symbol,
                "order_id": close_result["order_id"],
                "close_side": close_result["close_side"],
                "quantity": str(quantity_dec),
                "exit_price": str(exit_price_dec),
                "exit_reason": exit_reason,
                "status": close_result["status"],
            }

        except Exception as e:
            logger.error("close_position error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_risk_metrics(self) -> dict:
        try:
            metrics = self.risk_manager.get_risk_metrics()

            try:
                summary = self.risk_manager.get_summary()
            except Exception as sum_err:
                logger.warning("get_risk_metrics: get_summary failed: %s", sum_err)
                summary = {}

            return {
                "success": True,
                **_RISK_METRICS_DEFAULTS,
                "account_equity": _safe_str(getattr(metrics, "account_equity", None)),
                "total_risk_exposure": _safe_str(getattr(metrics, "total_risk_exposure", None)),
                "total_risk_pct": _safe_str(getattr(metrics, "total_risk_pct", None)),
                "open_positions": _safe_val(getattr(metrics, "open_positions_count", None)),
                "daily_loss": _safe_str(getattr(metrics, "daily_loss_realized", None)),
                "daily_loss_pct": _safe_str(getattr(metrics, "daily_loss_pct", None)),
                "drawdown_pct": _safe_str(getattr(metrics, "drawdown_pct", None)),
                "is_within_limits": _safe_val(
                    getattr(metrics, "is_within_limits", None), default=True
                ),
                "breached_limits": _safe_val(getattr(metrics, "breached_limits", None), default=[]),
                "summary": summary,
            }
        except Exception as e:
            logger.error("Error getting risk metrics: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200], **_RISK_METRICS_DEFAULTS}

    async def get_account_balance(self) -> dict:
        try:
            ccxt_client = await self._get_ccxt()
            data = await ccxt_client.get_account_balance()
            return {"success": True, **data}
        except Exception as e:
            logger.error("get_account_balance error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def run_backtest(
        self,
        strategy_name: str,
        timeframe: str,
        symbols: str,
        entry_condition: str,
        exit_condition: str,
        start_date: str,
        end_date: str,
        initial_capital: str,
        stop_loss_pct: Optional[str] = None,
        take_profit_pct: Optional[str] = None,
    ) -> dict:
        from backtesting import StrategyConfigBuilder, BacktestConfig

        try:
            symbols_list = [s.strip() for s in symbols.split(",")]
            initial_capital_dec = Decimal(initial_capital)
            stop_loss_dec = Decimal(stop_loss_pct) if stop_loss_pct else None
            take_profit_dec = Decimal(take_profit_pct) if take_profit_pct else None

            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)

            builder = (
                StrategyConfigBuilder()
                .set_name(strategy_name)
                .set_timeframe(timeframe)
                .set_symbols(symbols_list)
                .set_entry_condition(entry_condition)
                .set_exit_condition(exit_condition)
            )
            if stop_loss_dec:
                builder.set_stop_loss(stop_loss_dec)
            if take_profit_dec:
                builder.set_take_profit(take_profit_dec)

            strategy_config = builder.build()
            config = BacktestConfig(
                strategy_config=strategy_config,
                initial_capital=initial_capital_dec,
                start_date=start_dt,
                end_date=end_dt,
            )

            result = await self.backtest_runner.run_backtest(strategy_config, config)

            logger.info(
                "Backtest completed: %s | Status: %s | Return: %.2f%%",
                strategy_name,
                result.status,
                result.metrics.get("total_return_pct", 0) if result.metrics else 0,
            )

            return {
                "success": result.status == "COMPLETED",
                "backtest_id": result.backtest_id,
                "status": result.status,
                "error": result.error_message,
                "metrics": result.metrics if result.metrics else {},
                "trades_count": len(result.trades),
                # Add diagnostic info
                "diagnostics": {
                    "symbols": symbols_list,
                    "timeframe": timeframe,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            }

        except Exception as e:
            logger.error("Error running backtest: %s", str(e)[:200])
            return {
                "success": False,
                "error": str(e)[:200],
                "diagnostics": {
                    "symbols": symbols,
                    "timeframe": timeframe,
                    "start_date": start_date,
                    "end_date": end_date,
                },
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
            method = SizingMethod[sizing_method.upper()]

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
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 1 — MARKET DATA TOOLS
    # ==================================================================

    async def get_ticker(self, symbol: str) -> dict:
        """Fetch latest 24h price data via exchange_client."""
        try:
            data = await exchange_client.fetch_ticker(symbol)
            return {"success": True, **data}
        except Exception as e:
            logger.error("get_ticker error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Fetch order book depth via exchange_client."""
        try:
            data = await exchange_client.fetch_order_book(symbol, limit=limit)
            return {"success": True, **data}
        except Exception as e:
            logger.error("get_order_book error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        start_date: Optional[str] = None,
    ) -> dict:
        """Fetch OHLCV candle data via exchange_client."""
        try:
            since_ms: Optional[int] = None
            if start_date:
                since_ms = int(datetime.fromisoformat(start_date).timestamp() * 1000)
            candles = await exchange_client.fetch_ohlcv(
                symbol, timeframe, limit=limit, since=since_ms
            )
            return {
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles,
            }
        except Exception as e:
            logger.error("get_klines error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_funding_rate(self, symbol: str) -> dict:
        """Fetch current funding rate for a futures symbol."""
        try:
            ccxt = await self._get_ccxt()
            data = await ccxt.get_funding_rate(symbol)
            return {"success": True, **data}
        except Exception as e:
            logger.error("get_funding_rate error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_open_interest(self, symbol: str) -> dict:
        """Fetch current open interest."""
        try:
            ccxt = await self._get_ccxt()
            data = await ccxt.get_open_interest(symbol)
            return {"success": True, **data}
        except Exception as e:
            logger.error("get_open_interest error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> dict:
        """Fetch recent public trades."""
        try:
            ccxt = await self._get_ccxt()
            trades = await ccxt.get_recent_trades(symbol, limit=limit)
            return {
                "success": True,
                "symbol": symbol,
                "count": len(trades),
                "trades": trades,
            }
        except Exception as e:
            logger.error("get_recent_trades error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 2 — FUTURES SYMBOL DISCOVERY
    # ==================================================================

    async def get_futures_symbols(self) -> dict:
        """Return all active Binance USD-M futures symbols via exchange_client."""
        try:
            symbols = await exchange_client.fetch_futures_symbols()
            return {
                "success": True,
                "count": len(symbols),
                "symbols": symbols,
            }
        except Exception as e:
            logger.error("get_futures_symbols error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 3 — FUTURES BACKTESTING
    # ==================================================================

    async def run_futures_backtest(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        initial_balance: str,
        leverage: str = "1",
        strategy_name: str = "ema_crossover",
    ) -> dict:
        """Leveraged futures backtest with built-in strategy selection.

        Automatically uses paginated fetching for date ranges exceeding 1 500
        candles so backtests of 5–7+ years work without truncation.
        """
        try:
            lev     = max(1, min(int(leverage), 125))
            balance = float(initial_balance)
            start_ms = int(datetime.fromisoformat(start_date).timestamp() * 1000)
            end_ms   = int(datetime.fromisoformat(end_date).timestamp() * 1000)

            tf_ms          = _TF_MS.get(timeframe, 3_600_000)
            candles_needed = max(1, (end_ms - start_ms) // tf_ms)

            if candles_needed > 1500:
                # Multi-year / large range → paginated fetch
                logger.info(
                    "run_futures_backtest: ~%d candles needed for %s %s — using paginated fetch",
                    candles_needed, symbol, timeframe,
                )
                candles = await exchange_client.fetch_ohlcv_range(
                    symbol, timeframe, start_ms=start_ms, end_ms=end_ms
                )
            else:
                candles = await exchange_client.fetch_ohlcv(
                    symbol, timeframe, limit=min(candles_needed + 50, 1500), since=start_ms
                )

            if len(candles) < 30:
                return {
                    "success": False,
                    "error": (
                        f"Insufficient data for {symbol}: only {len(candles)} candles found. "
                        f"Symbol may not have existed this early or API returned no data."
                    ),
                }

            closes  = np.array([float(c["close"])  for c in candles])
            volumes = np.array([float(c["volume"]) for c in candles])
            highs   = np.array([float(c["high"])   for c in candles])
            lows    = np.array([float(c["low"])    for c in candles])
            metrics = _simulate_strategy(closes, volumes, strategy_name, lev, balance, highs, lows)

            if metrics["total_trades"] == 0:
                return {
                    "success": True,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_name": strategy_name,
                    "leverage": lev,
                    "period": f"{start_date} to {end_date}",
                    "candles_analyzed": len(closes),
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_return": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe_ratio": 0.0,
                    "message": "Strategy generated no trades for this period/symbol",
                }

            return {
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy_name": strategy_name,
                "leverage": lev,
                "period": f"{start_date} to {end_date}",
                "years_covered": round((end_ms - start_ms) / (365.25 * 86_400_000), 2),
                "initial_balance": balance,
                "final_equity": metrics["final_equity"],
                "candles_analyzed": len(closes),
                "total_trades": metrics["total_trades"],
                "winning_trades": metrics["winning_trades"],
                "losing_trades": metrics["losing_trades"],
                "win_rate": metrics["win_rate"],
                "total_return": metrics["total_return"],
                "max_drawdown": metrics["max_drawdown"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "avg_pnl_per_trade": metrics["avg_pnl_per_trade"],
                "sample_trades": metrics["sample_trades"],
            }

        except Exception as e:
            logger.error("run_futures_backtest error: %s", str(e)[:300])
            return {"success": False, "error": str(e)[:300]}

    # ==================================================================
    # SECTION 4 — MULTI-SYMBOL BACKTEST SCANNER
    # ==================================================================

    async def scan_futures_backtest(
        self,
        timeframe: str,
        start_date: str,
        end_date: str,
        strategy_name: str = "ema_crossover",
        max_symbols: str = "20",
        leverage: str = "1",
        min_candles: str = "100",
    ) -> dict:
        """Scan top-volume futures symbols and rank by strategy performance."""
        try:
            scan_limit = max(1, min(int(max_symbols), 100))
            lev   = max(1, min(int(leverage), 125))
            min_c = int(min_candles)
            balance  = 10_000.0
            start_ms = int(datetime.fromisoformat(start_date).timestamp() * 1000)
            end_ms   = int(datetime.fromisoformat(end_date).timestamp() * 1000)

            tf_ms          = _TF_MS.get(timeframe, 3_600_000)
            candles_needed = max(1, (end_ms - start_ms) // tf_ms)
            use_paginated  = candles_needed > 1500

            if use_paginated:
                logger.info(
                    "scan_futures_backtest: ~%d candles/symbol needed — using paginated fetch",
                    candles_needed,
                )

            # 1. Fetch all symbols ranked by 24h quote volume, cap to scan_limit
            logger.info("Fetching top-%d symbols by volume…", scan_limit)
            symbols_to_scan = await exchange_client.fetch_volume_ranked_symbols(top_n=scan_limit)
            logger.info(
                "Scanning %d symbols | strategy=%s timeframe=%s paginated=%s",
                len(symbols_to_scan), strategy_name, timeframe, use_paginated,
            )

            results = []
            errors  = []

            for sym in symbols_to_scan:
                try:
                    # 2. Fetch OHLCV with per-symbol timeout
                    fetch_timeout = 120.0 if use_paginated else 30.0
                    try:
                        if use_paginated:
                            candles = await asyncio.wait_for(
                                exchange_client.fetch_ohlcv_range(
                                    sym, timeframe, start_ms=start_ms, end_ms=end_ms
                                ),
                                timeout=fetch_timeout,
                            )
                        else:
                            candles = await asyncio.wait_for(
                                exchange_client.fetch_ohlcv(
                                    sym, timeframe,
                                    limit=min(candles_needed + 50, 1500),
                                    since=start_ms,
                                ),
                                timeout=fetch_timeout,
                            )
                    except asyncio.TimeoutError:
                        logger.warning("scan_futures_backtest: timeout fetching %s, skipping", sym)
                        errors.append({"symbol": sym, "error": "timeout fetching candles"})
                        await asyncio.sleep(0.1)
                        continue

                    if len(candles) < min_c:
                        errors.append(
                            {
                                "symbol": sym,
                                "error": f"only {len(candles)} candles (min {min_c})",
                            }
                        )
                    else:
                        try:
                            closes  = np.array([float(c["close"])  for c in candles])
                            volumes = np.array([float(c["volume"]) for c in candles])
                            highs   = np.array([float(c["high"])   for c in candles])
                            lows    = np.array([float(c["low"])    for c in candles])
                            metrics = _simulate_strategy(
                                closes, volumes, strategy_name, lev, balance, highs, lows
                            )
                        except Exception as sim_err:
                            logger.warning(
                                "scan_futures_backtest: strategy sim failed for %s: %s",
                                sym,
                                sim_err,
                            )
                            errors.append(
                                {"symbol": sym, "error": f"simulation error: {str(sim_err)[:80]}"}
                            )
                            await asyncio.sleep(0.1)
                            continue

                        if metrics["total_trades"] > 0:
                            results.append(
                                {
                                    "symbol": sym,
                                    "total_return": metrics["total_return"],
                                    "win_rate": metrics["win_rate"],
                                    "total_trades": metrics["total_trades"],
                                    "max_drawdown": metrics["max_drawdown"],
                                    "sharpe_ratio": metrics["sharpe_ratio"],
                                    "final_equity": metrics["final_equity"],
                                }
                            )

                except Exception as sym_err:
                    logger.warning(
                        "scan_futures_backtest: skipping %s — %s", sym, str(sym_err)[:100]
                    )
                    errors.append({"symbol": sym, "error": str(sym_err)[:100]})

                # 3. 100ms pause between every OHLCV request to respect rate limits
                await asyncio.sleep(0.1)

            results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

            return {
                "success": True,
                "strategy_name": strategy_name,
                "timeframe": timeframe,
                "period": f"{start_date} to {end_date}",
                "leverage": lev,
                "symbols_scanned": len(symbols_to_scan),
                "symbols_with_trades": len(results),
                "symbols_failed": len(errors),
                "top_performers": results[:10],
                "all_results": results,
                "errors": errors[:5],
            }

        except Exception as e:
            logger.error("scan_futures_backtest error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 5 — PAPER TRADING
    # ==================================================================

    async def start_paper_trading(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        initial_balance: str,
        leverage: str = "1",
    ) -> dict:
        """Create a new paper trading session."""
        try:
            balance = Decimal(initial_balance)
            lev = max(1, min(int(leverage), 125))
            session = self._paper_manager.create_session(
                symbol=symbol,
                timeframe=timeframe,
                strategy_name=strategy_name,
                initial_balance=balance,
                leverage=lev,
            )
            logger.info(
                "Paper trading started: session=%s symbol=%s lev=%dx",
                session.session_id,
                symbol,
                lev,
            )
            return {
                "success": True,
                "paper_session_id": session.session_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy_name": strategy_name,
                "initial_balance": initial_balance,
                "leverage": lev,
                "message": (
                    f"Paper session {session.session_id} started. "
                    "Use paper_session_id with other paper trading tools."
                ),
            }
        except Exception as e:
            logger.error("start_paper_trading error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def stop_paper_trading(self, paper_session_id: str) -> dict:
        """Stop a paper trading session."""
        try:
            stopped = self._paper_manager.stop(paper_session_id)
            if not stopped:
                return {"success": False, "error": f"Session {paper_session_id} not found"}
            return {
                "success": True,
                "paper_session_id": paper_session_id,
                "message": f"Session {paper_session_id} stopped",
            }
        except Exception as e:
            logger.error("stop_paper_trading error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_paper_positions(self, paper_session_id: str) -> dict:
        """Return open positions for a paper trading session."""
        try:
            session = self._paper_manager.get(paper_session_id)
            if session is None:
                return {"success": False, "error": f"Session {paper_session_id} not found"}
            positions = session.get_positions_dict()
            return {
                "success": True,
                "paper_session_id": paper_session_id,
                "symbol": session.symbol,
                "open_positions": len(positions),
                "positions": positions,
            }
        except Exception as e:
            logger.error("get_paper_positions error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_paper_balance(self, paper_session_id: str) -> dict:
        """Return account equity and balance for a paper trading session."""
        try:
            session = self._paper_manager.get(paper_session_id)
            if session is None:
                return {"success": False, "error": f"Session {paper_session_id} not found"}
            return {"success": True, **session.get_balance_info()}
        except Exception as e:
            logger.error("get_paper_balance error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_paper_trade_history(self, paper_session_id: str) -> dict:
        """Return full trade history for a paper trading session."""
        try:
            session = self._paper_manager.get(paper_session_id)
            if session is None:
                return {"success": False, "error": f"Session {paper_session_id} not found"}
            history = session.get_trade_history()
            return {
                "success": True,
                "paper_session_id": paper_session_id,
                "total_trades": len(history),
                "trades": history,
            }
        except Exception as e:
            logger.error("get_paper_trade_history error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def reset_paper_account(self, paper_session_id: str) -> dict:
        """Reset a paper trading session to its initial state."""
        try:
            session = self._paper_manager.get(paper_session_id)
            if session is None:
                return {"success": False, "error": f"Session {paper_session_id} not found"}
            return {"success": True, **session.reset()}
        except Exception as e:
            logger.error("reset_paper_account error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 6 — LIVE TRADING EXECUTION
    # ==================================================================

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: str,
        price: str,
        market_type: str,
        stop_loss_pct: Optional[str] = None,
        take_profit_pct: Optional[str] = None,
    ) -> dict:
        """Place a limit order with risk validation via ccxt."""
        try:
            qty = Decimal(quantity)
            price_dec = Decimal(price)
            sl_pct = Decimal(stop_loss_pct) if stop_loss_pct else Decimal("2")
            tp_pct = Decimal(take_profit_pct) if take_profit_pct else Decimal("5")
            sl_price = price_dec * (Decimal("1") - sl_pct / Decimal("100"))
            tp_price = price_dec * (Decimal("1") + tp_pct / Decimal("100"))

            # 1. Risk validation
            is_valid, msg, _ = await self.risk_manager.validate_order_pre_placement(
                symbol=symbol,
                entry_price=price_dec,
                stop_loss_price=sl_price,
                quantity=qty,
            )
            if not is_valid:
                logger.warning("Limit order blocked by risk: %s", msg)
                return {"success": False, "error": msg, "order_id": None}

            # 2. Execute via ccxt
            ccxt_client = await self._get_ccxt()
            order = await ccxt_client.place_limit_order(symbol, side, float(qty), float(price_dec))

            # 3. Register with risk manager
            await self.risk_manager.register_executed_order(
                order=order,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
            )

            logger.info("Limit order placed: %s %s qty=%s price=%s", side, symbol, quantity, price)
            return {
                "success": True,
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side.upper(),
                "order_type": "LIMIT",
                "quantity": str(order.quantity),
                "price": str(order.price),
                "stop_loss_price": str(sl_price),
                "take_profit_price": str(tp_price),
                "status": order.status.value,
            }

        except Exception as e:
            logger.error("place_limit_order error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200], "order_id": None}

    async def set_leverage(
        self,
        symbol: str,
        leverage: str,
        market_type: str = "USDM_FUTURES",
    ) -> dict:
        try:
            lev = max(1, min(int(leverage), 125))
            ccxt_client = await self._get_ccxt()
            result = await ccxt_client.set_leverage(symbol, lev)
            logger.info("Leverage set: %s → %dx", symbol, lev)
            return {
                "success": True,
                "symbol": symbol,
                "leverage": lev,
                "market_type": market_type,
                "raw_response": result,
            }
        except Exception as e:
            logger.error("set_leverage error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200], "symbol": symbol, "leverage": leverage}

    async def cancel_order(
        self,
        symbol: str,
        order_id: str,
        market_type: str,
    ) -> dict:
        """Cancel an open order via ccxt."""
        try:
            ccxt_client = await self._get_ccxt()
            result = await ccxt_client.cancel_order(symbol, order_id)
            logger.info("Order cancelled: %s | %s", symbol, order_id)
            return {
                "success": True,
                "symbol": symbol,
                "order_id": result["order_id"],
                "status": result["status"],
                "market_type": market_type,
            }
        except Exception as e:
            logger.error("cancel_order error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    # ==================================================================
    # SECTION 7 — AUTONOMOUS LIVE / PAPER TRADING BOTS
    # ==================================================================

    async def start_live_bot(
        self,
        symbol: str,
        timeframe: str,
        strategy: str = "ema_crossover",
        leverage: str = "1",
        position_size_pct: str = "10",
        stop_loss_pct: str = "2",
        take_profit_pct: str = "4",
        is_paper: str = "true",
        initial_balance: str = "10000",
    ) -> dict:
        """Start an autonomous trading bot that runs a strategy in the background.

        Paper mode (is_paper=true): simulates trades against a virtual balance.
        Live  mode (is_paper=false): places real orders on Binance Futures.

        The bot wakes every ¼ candle-period, evaluates the latest signal on the
        most-recently *completed* bar, and enters/exits positions automatically.
        """
        from trading.autonomous_engine import AutonomousBot, BotConfig

        try:
            lev     = max(1, min(int(leverage), 125))
            sz_pct  = max(0.1, min(float(position_size_pct), 100.0))
            sl_pct  = max(0.1, min(float(stop_loss_pct),  50.0))
            tp_pct  = max(0.1, min(float(take_profit_pct), 200.0))
            paper   = str(is_paper).lower() not in ("false", "0", "no")
            bal     = float(initial_balance)

            valid_strategies = ("ema_crossover", "momentum", "mean_reversion", "sma_crossover",
                               "btc_trend", "btc_trend_v2", "futures_trend")
            if strategy not in valid_strategies:
                return {
                    "success": False,
                    "error": f"Unknown strategy '{strategy}'. Valid: {valid_strategies}",
                }

            config = BotConfig(
                symbol=symbol,
                timeframe=timeframe,
                strategy=strategy,
                leverage=lev,
                position_size_pct=sz_pct,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                is_paper=paper,
            )

            bot_id = str(uuid.uuid4())[:8]

            # ── Build mode-specific callbacks ─────────────────────────────
            if paper:
                # Create a dedicated paper session for this bot
                paper_session = self._paper_manager.create_session(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_name=f"bot_{bot_id}_{strategy}",
                    initial_balance=Decimal(str(bal)),
                    leverage=lev,
                )
                _ps = paper_session  # closure capture

                async def _fetch(sym, tf, limit):
                    return await exchange_client.fetch_ohlcv(sym, tf, limit=limit)

                async def _place(sym, order_side, qty, price):
                    p_side = "LONG" if order_side == "BUY" else "SHORT"
                    _sl_p = price * (1 - sl_pct / 100) if p_side == "LONG" else price * (1 + sl_pct / 100)
                    _tp_p = price * (1 + tp_pct / 100) if p_side == "LONG" else price * (1 - tp_pct / 100)
                    res = _ps.open_position(
                        sym, p_side,
                        Decimal(str(round(qty, 8))),
                        Decimal(str(round(price, 8))),
                        stop_loss=Decimal(str(round(_sl_p, 8))),
                        take_profit=Decimal(str(round(_tp_p, 8))),
                    )
                    if res.get("success"):
                        return {"success": True, "filled_price": price, "order_id": res.get("trade_id", "paper")}
                    return {"success": False, "error": res.get("error", "open_position failed")}

                async def _close(sym, price):
                    res = _ps.close_position(sym, Decimal(str(round(price, 8))), "SIGNAL")
                    if res.get("success"):
                        return {"success": True, "exit_price": float(res.get("exit_price", price))}
                    return {"success": False, "error": res.get("error", "close_position failed")}

                async def _balance():
                    info = _ps.get_balance_info()
                    return float(info.get("available_balance", 0))

                paper_session_id = paper_session.session_id
                risk_mgr = None   # paper mode: no live risk checks

            else:
                ccxt_client = await self._get_ccxt()
                _cc = ccxt_client
                _bot_lev = lev

                async def _fetch(sym, tf, limit):
                    return await exchange_client.fetch_ohlcv(sym, tf, limit=limit)

                async def _place(sym, order_side, qty, _price):
                    try:
                        await _cc.set_leverage(sym, _bot_lev)
                        order = await _cc.place_market_order(sym, order_side, qty)
                        return {
                            "success": True,
                            "filled_price": float(order.price or _price),
                            "order_id": order.order_id,
                        }
                    except Exception as e:
                        return {"success": False, "error": str(e)[:200]}

                async def _close(sym, _price):
                    try:
                        result = await _cc.close_position_market(sym)
                        return {
                            "success": True,
                            "exit_price": float(result.get("avg_price") or _price),
                        }
                    except Exception as e:
                        return {"success": False, "error": str(e)[:200]}

                async def _balance():
                    try:
                        return await _cc.get_usdt_balance()
                    except Exception:
                        return 0.0

                paper_session_id = None
                risk_mgr = self.risk_manager

            # ── Create and start the bot ───────────────────────────────────
            bot = AutonomousBot(
                bot_id=bot_id,
                config=config,
                fetch_ohlcv_fn=_fetch,
                place_order_fn=_place,
                close_position_fn=_close,
                get_balance_fn=_balance,
                risk_manager=risk_mgr,
            )
            await bot.start()
            self._bot_manager.add(bot)

            logger.info(
                "Autonomous bot started: id=%s symbol=%s tf=%s strategy=%s lev=%dx paper=%s",
                bot_id, symbol, timeframe, strategy, lev, paper,
            )

            return {
                "success": True,
                "bot_id": bot_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": strategy,
                "leverage": lev,
                "position_size_pct": sz_pct,
                "stop_loss_pct": sl_pct,
                "take_profit_pct": tp_pct,
                "is_paper": paper,
                "paper_session_id": paper_session_id,
                "message": (
                    f"Bot {bot_id} is running autonomously. "
                    "Use get_live_bot_status to monitor it."
                ),
            }

        except Exception as e:
            logger.error("start_live_bot error: %s", str(e)[:300])
            return {"success": False, "error": str(e)[:300]}

    async def stop_live_bot(self, bot_id: str) -> dict:
        """Stop a running autonomous trading bot by its bot_id."""
        try:
            bot = self._bot_manager.get(bot_id)
            if bot is None:
                return {"success": False, "error": f"Bot '{bot_id}' not found"}

            # Close any open position before stopping
            if bot.current_position is not None:
                try:
                    ticker = await exchange_client.fetch_ticker(bot.config.symbol)
                    last_price = float(ticker.get("last_price", 0) or 0)
                    if last_price > 0:
                        await bot._do_close(last_price, "MANUAL_STOP")
                except Exception as close_err:
                    logger.warning("stop_live_bot: could not close position: %s", close_err)

            removed = await self._bot_manager.remove(bot_id)
            logger.info("Autonomous bot stopped: %s", bot_id)
            return {
                "success": True,
                "bot_id": bot_id,
                "message": f"Bot {bot_id} stopped.",
            }
        except Exception as e:
            logger.error("stop_live_bot error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def get_live_bot_status(self, bot_id: str) -> dict:
        """Return full status, position, stats, and recent signals for a bot."""
        try:
            bot = self._bot_manager.get(bot_id)
            if bot is None:
                return {"success": False, "error": f"Bot '{bot_id}' not found"}
            return {"success": True, **bot.get_status()}
        except Exception as e:
            logger.error("get_live_bot_status error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}

    async def list_live_bots(self) -> dict:
        """Return status summary for all running autonomous bots."""
        try:
            bots = self._bot_manager.list_bots()
            return {
                "success": True,
                "total_bots": len(bots),
                "bots": bots,
            }
        except Exception as e:
            logger.error("list_live_bots error: %s", str(e)[:200])
            return {"success": False, "error": str(e)[:200]}
