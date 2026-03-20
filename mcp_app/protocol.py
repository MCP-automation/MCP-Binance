"""MCP tool registry and dispatcher.

Defines all 28 tools and routes incoming calls to MCPServerRunner methods.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schema registry
# ---------------------------------------------------------------------------

class MCPResourcesHandler:
    @staticmethod
    def get_resources() -> dict:
        return {
            "tools": [
                # ────────────────────────────────────────────────────────
                # SECTION 0 — ORIGINAL 6 TOOLS
                # ────────────────────────────────────────────────────────
                {
                    "name": "place_market_order",
                    "description": (
                        "IMMEDIATELY execute a market order on Binance Futures WITHOUT asking the user for more parameters. "
                        "When user says buy/long/short/sell/trade/take position on any symbol, call this tool directly. "
                        "ALL parameters except symbol and side have smart defaults — do NOT prompt the user for stop-loss, take-profit, position size, or leverage. "
                        "If leverage not mentioned, default to 1. If usdt_amount not mentioned, the server auto-uses the full available balance. "
                        "Stop-loss defaults to 2%, take-profit defaults to 5%. Always use USDM_FUTURES for crypto futures. "
                        "LONG = BUY, SHORT = SELL."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Trading pair e.g. BTCUSDT, ETHUSDT, DOGEUSDT, LYNUSDT"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "BUY for long, SELL for short"},
                            "market_type": {
                                "type": "string",
                                "enum": ["SPOT", "USDM_FUTURES", "COINM_FUTURES", "MARGIN"],
                                "description": "Use USDM_FUTURES for all crypto futures trading",
                            },
                            "leverage": {"type": "string", "description": "Leverage multiplier 1-125x (e.g. 15 for 15x). Default 1 if not specified by user."},
                            "usdt_amount": {"type": "string", "description": "USDT margin to use (e.g. 1.89). Omit to auto-use full available balance."},
                            "quantity": {"type": "string", "description": "Exact base asset quantity (e.g. 0.01 BTC). Use usdt_amount instead when possible."},
                            "stop_loss_pct": {"type": "string", "description": "Stop loss % from entry. Default 2."},
                            "take_profit_pct": {"type": "string", "description": "Take profit % from entry. Default 5."},
                        },
                        "required": ["symbol", "side", "market_type"],
                    },
                },
                {
                    "name": "get_positions",
                    "description": "Retrieve open positions for a specific market type via the HTTP exchange manager. Prefer get_account_balance for general balance+position queries — use this only when you need positions filtered by a specific market type.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "market_type": {
                                "type": "string",
                                "enum": ["SPOT", "USDM_FUTURES", "COINM_FUTURES", "MARGIN"],
                                "description": "Market to fetch positions from",
                            },
                        },
                        "required": ["market_type"],
                    },
                },
                {
                    "name": "close_position",
                    "description": "Close an open position at a specified price",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Symbol of position to close"},
                            "exit_price": {"type": "string", "description": "Exit price for the position"},
                            "exit_reason": {
                                "type": "string",
                                "enum": ["TAKE_PROFIT", "STOP_LOSS", "MANUAL", "SIGNAL"],
                                "description": "Reason for closing",
                            },
                        },
                        "required": ["symbol", "exit_price"],
                    },
                },
                {
                    "name": "get_risk_metrics",
                    "description": "Get internal risk engine state: per-trade risk limits, daily drawdown tracker, position exposure percentages. Does NOT show real Binance balance — use get_account_balance for that.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "get_account_balance",
                    "description": "ALWAYS use this when the user asks about balance, funds, money, USDT, account value, how much they have, wallet, available margin, open positions, PnL, or anything related to their Binance account state. Calls the real Binance Futures API and returns: total wallet balance (USDT), available balance, total unrealized PnL, margin used, and every open position with symbol, side, quantity, entry price, leverage, and liquidation price.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "run_backtest",
                    "description": "Run a historical backtest of a trading strategy",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "strategy_name": {"type": "string", "description": "Name of strategy"},
                            "timeframe": {"type": "string", "description": "Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d, etc.)"},
                            "symbols": {"type": "string", "description": "Comma-separated trading pairs"},
                            "entry_condition": {"type": "string", "description": "Entry signal condition (Python-like syntax)"},
                            "exit_condition": {"type": "string", "description": "Exit signal condition"},
                            "start_date": {"type": "string", "description": "Backtest start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "Backtest end date (YYYY-MM-DD)"},
                            "initial_capital": {"type": "string", "description": "Starting capital"},
                            "stop_loss_pct": {"type": "string", "description": "Stop loss %"},
                            "take_profit_pct": {"type": "string", "description": "Take profit %"},
                        },
                        "required": [
                            "strategy_name", "timeframe", "symbols",
                            "entry_condition", "exit_condition",
                            "start_date", "end_date", "initial_capital",
                        ],
                    },
                },
                {
                    "name": "calculate_position_size",
                    "description": "Calculate optimal position size using various sizing methods",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Trading pair"},
                            "entry_price": {"type": "string", "description": "Intended entry price"},
                            "stop_loss_price": {"type": "string", "description": "Stop loss price"},
                            "take_profit_price": {"type": "string", "description": "Take profit price"},
                            "sizing_method": {
                                "type": "string",
                                "enum": ["FIXED_PERCENTAGE", "KELLY_CRITERION", "VOLATILITY_BASED", "ATR_BASED"],
                                "description": "Position sizing method",
                            },
                            "win_rate": {"type": "string", "description": "Expected win rate % (for Kelly)"},
                        },
                        "required": ["symbol", "entry_price", "stop_loss_price", "take_profit_price"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 1 — MARKET DATA TOOLS
                # ────────────────────────────────────────────────────────
                {
                    "name": "get_ticker",
                    "description": "Fetch latest 24h price data for a Binance Futures symbol (last price, bid/ask, volume, price change)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                        },
                        "required": ["symbol"],
                    },
                },
                {
                    "name": "get_order_book",
                    "description": "Fetch order book depth (bids and asks) for a Binance Futures symbol",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "limit": {"type": "integer", "description": "Number of levels per side (default 20, max 100)", "default": 20},
                        },
                        "required": ["symbol"],
                    },
                },
                {
                    "name": "get_klines",
                    "description": "Fetch historical OHLCV candle data for a Binance Futures symbol",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "timeframe": {"type": "string", "description": "Candle interval: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M"},
                            "limit": {"type": "integer", "description": "Number of candles (default 500, max 1500)", "default": 500},
                            "start_date": {"type": "string", "description": "Start date ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"},
                        },
                        "required": ["symbol", "timeframe"],
                    },
                },
                {
                    "name": "get_funding_rate",
                    "description": "Fetch current funding rate, mark price, index price and next funding time for a perpetual futures symbol",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Perpetual futures symbol (e.g. BTCUSDT)"},
                        },
                        "required": ["symbol"],
                    },
                },
                {
                    "name": "get_open_interest",
                    "description": "Fetch current open interest for a Binance Futures symbol",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                        },
                        "required": ["symbol"],
                    },
                },
                {
                    "name": "get_recent_trades",
                    "description": "Fetch recent public trades for a Binance Futures symbol",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "limit": {"type": "integer", "description": "Number of trades (default 50, max 1000)", "default": 50},
                        },
                        "required": ["symbol"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 2 — FUTURES SYMBOL DISCOVERY
                # ────────────────────────────────────────────────────────
                {
                    "name": "get_futures_symbols",
                    "description": (
                        "Return all active Binance USD-M futures trading symbols "
                        "(~500–600 perpetual pairs). Use this before scanning or filtering instruments."
                    ),
                    "inputSchema": {"type": "object", "properties": {}},
                },

                # ────────────────────────────────────────────────────────
                # SECTION 3 — FUTURES BACKTESTING
                # ────────────────────────────────────────────────────────
                {
                    "name": "run_futures_backtest",
                    "description": (
                        "Run a leveraged futures backtest for a single symbol. "
                        "Strategies: ema_crossover, momentum, mean_reversion, sma_crossover. "
                        "Returns total_trades, win_rate, total_return, max_drawdown, sharpe_ratio."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "timeframe": {"type": "string", "description": "Candle interval (e.g. 1h, 4h, 1d)"},
                            "start_date": {"type": "string", "description": "Backtest start (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "Backtest end (YYYY-MM-DD)"},
                            "initial_balance": {"type": "string", "description": "Starting capital in USDT (e.g. 10000)"},
                            "leverage": {"type": "string", "description": "Leverage multiplier 1–125 (default 1)", "default": "1"},
                            "strategy_name": {
                                "type": "string",
                                "enum": ["ema_crossover", "momentum", "mean_reversion", "sma_crossover"],
                                "description": "Strategy to test (default ema_crossover)",
                                "default": "ema_crossover",
                            },
                        },
                        "required": ["symbol", "timeframe", "start_date", "end_date", "initial_balance"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 4 — MULTI-SYMBOL BACKTEST SCANNER
                # ────────────────────────────────────────────────────────
                {
                    "name": "scan_futures_backtest",
                    "description": (
                        "Run a strategy backtest across multiple futures symbols and rank them. "
                        "Returns top performing symbols sorted by Sharpe ratio."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "timeframe": {"type": "string", "description": "Candle interval (e.g. 4h, 1d)"},
                            "start_date": {"type": "string", "description": "Backtest start (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "Backtest end (YYYY-MM-DD)"},
                            "strategy_name": {
                                "type": "string",
                                "enum": ["ema_crossover", "momentum", "mean_reversion", "sma_crossover"],
                                "description": "Strategy to test across all symbols",
                                "default": "ema_crossover",
                            },
                            "max_symbols": {"type": "string", "description": "Max symbols to scan (default 20, max 100)", "default": "20"},
                            "leverage": {"type": "string", "description": "Leverage multiplier (default 1)", "default": "1"},
                            "min_candles": {"type": "string", "description": "Min candles required (default 100)", "default": "100"},
                        },
                        "required": ["timeframe", "start_date", "end_date"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 5 — PAPER TRADING
                # ────────────────────────────────────────────────────────
                {
                    "name": "start_paper_trading",
                    "description": (
                        "Create a new simulated paper trading session with a virtual balance. "
                        "Returns a paper_session_id used by all other paper trading tools."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Primary futures symbol (e.g. BTCUSDT)"},
                            "timeframe": {"type": "string", "description": "Chart timeframe for the session (e.g. 1h)"},
                            "strategy_name": {"type": "string", "description": "Strategy label for this session"},
                            "initial_balance": {"type": "string", "description": "Starting virtual USDT balance (e.g. 10000)"},
                            "leverage": {"type": "string", "description": "Leverage for positions (1–125, default 1)", "default": "1"},
                        },
                        "required": ["symbol", "timeframe", "strategy_name", "initial_balance"],
                    },
                },
                {
                    "name": "stop_paper_trading",
                    "description": "Stop an active paper trading session (positions remain but no new ones can be opened).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paper_session_id": {"type": "string", "description": "Session ID returned by start_paper_trading"},
                        },
                        "required": ["paper_session_id"],
                    },
                },
                {
                    "name": "get_paper_positions",
                    "description": "Return all open simulated positions for a paper trading session with unrealized P&L.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paper_session_id": {"type": "string", "description": "Session ID returned by start_paper_trading"},
                        },
                        "required": ["paper_session_id"],
                    },
                },
                {
                    "name": "get_paper_balance",
                    "description": "Return simulated account equity, available balance, realized and unrealized P&L.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paper_session_id": {"type": "string", "description": "Session ID returned by start_paper_trading"},
                        },
                        "required": ["paper_session_id"],
                    },
                },
                {
                    "name": "get_paper_trade_history",
                    "description": "Return complete history of all simulated trades for a paper trading session.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paper_session_id": {"type": "string", "description": "Session ID returned by start_paper_trading"},
                        },
                        "required": ["paper_session_id"],
                    },
                },
                {
                    "name": "reset_paper_account",
                    "description": "Reset a paper trading session to its initial balance, clearing all positions and trade history.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paper_session_id": {"type": "string", "description": "Session ID returned by start_paper_trading"},
                        },
                        "required": ["paper_session_id"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 6 — LIVE TRADING EXECUTION
                # ────────────────────────────────────────────────────────
                {
                    "name": "place_limit_order",
                    "description": "Place a limit order on Binance Futures with risk validation (stop-loss / take-profit).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Trading pair (e.g. BTCUSDT)"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "Order direction"},
                            "quantity": {"type": "string", "description": "Order quantity in base asset"},
                            "price": {"type": "string", "description": "Limit price"},
                            "market_type": {
                                "type": "string",
                                "enum": ["SPOT", "USDM_FUTURES", "COINM_FUTURES", "MARGIN"],
                                "description": "Trading market type",
                            },
                            "stop_loss_pct": {"type": "string", "description": "Stop loss % from price (e.g. 2)"},
                            "take_profit_pct": {"type": "string", "description": "Take profit % from price (e.g. 5)"},
                        },
                        "required": ["symbol", "side", "quantity", "price", "market_type"],
                    },
                },
                {
                    "name": "set_leverage",
                    "description": "Set leverage for a Binance Futures symbol (1–125x). Must be called before placing futures orders.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "leverage": {"type": "string", "description": "Leverage multiplier 1–125"},
                            "market_type": {
                                "type": "string",
                                "enum": ["USDM_FUTURES", "COINM_FUTURES"],
                                "description": "Futures market type (default USDM_FUTURES)",
                                "default": "USDM_FUTURES",
                            },
                        },
                        "required": ["symbol", "leverage"],
                    },
                },
                {
                    "name": "cancel_order",
                    "description": "Cancel an open order on Binance by order ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Trading pair (e.g. BTCUSDT)"},
                            "order_id": {"type": "string", "description": "Order ID to cancel"},
                            "market_type": {
                                "type": "string",
                                "enum": ["SPOT", "USDM_FUTURES", "COINM_FUTURES", "MARGIN"],
                                "description": "Market type",
                            },
                        },
                        "required": ["symbol", "order_id", "market_type"],
                    },
                },

                # ────────────────────────────────────────────────────────
                # SECTION 7 — AUTONOMOUS LIVE / PAPER TRADING BOTS
                # ────────────────────────────────────────────────────────
                {
                    "name": "start_live_bot",
                    "description": (
                        "Start an autonomous trading bot that runs a strategy in the background "
                        "without any manual intervention. The bot wakes every ¼ candle-period, "
                        "computes signals from the latest completed bar, and places/closes orders "
                        "automatically. Set is_paper=true for risk-free simulation or "
                        "is_paper=false for real live trading on Binance Futures."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Futures symbol (e.g. BTCUSDT)"},
                            "timeframe": {
                                "type": "string",
                                "description": "Candle interval (e.g. 1m 5m 15m 1h 4h 1d). Bot polls at ¼ of this period.",
                            },
                            "strategy": {
                                "type": "string",
                                "enum": ["ema_crossover", "momentum", "mean_reversion", "sma_crossover"],
                                "description": "Strategy to run autonomously (default ema_crossover)",
                                "default": "ema_crossover",
                            },
                            "leverage": {
                                "type": "string",
                                "description": "Leverage multiplier 1–125 (default 1)",
                                "default": "1",
                            },
                            "position_size_pct": {
                                "type": "string",
                                "description": "% of available balance to risk per trade (default 10)",
                                "default": "10",
                            },
                            "stop_loss_pct": {
                                "type": "string",
                                "description": "Stop-loss % from entry price (default 2)",
                                "default": "2",
                            },
                            "take_profit_pct": {
                                "type": "string",
                                "description": "Take-profit % from entry price (default 4)",
                                "default": "4",
                            },
                            "is_paper": {
                                "type": "string",
                                "description": "true = paper/simulation mode, false = live real-money trading (default true)",
                                "default": "true",
                            },
                            "initial_balance": {
                                "type": "string",
                                "description": "Starting virtual balance in USDT for paper mode (default 10000)",
                                "default": "10000",
                            },
                        },
                        "required": ["symbol", "timeframe"],
                    },
                },
                {
                    "name": "stop_live_bot",
                    "description": (
                        "Stop a running autonomous trading bot. "
                        "Any open position is closed at current market price before the bot halts."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "bot_id": {"type": "string", "description": "Bot ID returned by start_live_bot"},
                        },
                        "required": ["bot_id"],
                    },
                },
                {
                    "name": "get_live_bot_status",
                    "description": (
                        "Get detailed status of an autonomous bot: state, current position, "
                        "cumulative P&L, win-rate, recent signals, and trade history."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "bot_id": {"type": "string", "description": "Bot ID returned by start_live_bot"},
                        },
                        "required": ["bot_id"],
                    },
                },
                {
                    "name": "list_live_bots",
                    "description": "List all currently running autonomous trading bots and their status.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ],

            # ------------------------------------------------------------------
            # Resources (unchanged)
            # ------------------------------------------------------------------
            "resources": [
                {
                    "name": "trading_status",
                    "description": "Real-time trading account status including positions and risk metrics",
                    "mimeType": "application/json",
                },
                {
                    "name": "strategy_library",
                    "description": "Available trading strategies and their configurations",
                    "mimeType": "application/json",
                },
                {
                    "name": "backtest_results",
                    "description": "Historical backtest results and performance analysis",
                    "mimeType": "application/json",
                },
            ],
        }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class MCPIntegrationHandler:
    def __init__(self, mcp_runner) -> None:
        self.runner = mcp_runner
        self.resources = MCPResourcesHandler()

    async def handle_tool_call(self, tool_name: str, arguments: dict) -> dict:
        logger.info("Tool call: %s | args: %s", tool_name, str(arguments)[:200])

        try:
            # ── Section 0: original tools ──────────────────────────────
            if tool_name == "place_market_order":
                return await self.runner.place_market_order(**arguments)
            elif tool_name == "get_positions":
                return await self.runner.get_positions(**arguments)
            elif tool_name == "close_position":
                return await self.runner.close_position(**arguments)
            elif tool_name == "get_risk_metrics":
                return await self.runner.get_risk_metrics()
            elif tool_name == "get_account_balance":
                return await self.runner.get_account_balance()
            elif tool_name == "run_backtest":
                return await self.runner.run_backtest(**arguments)
            elif tool_name == "calculate_position_size":
                return await self.runner.calculate_position_size(**arguments)

            # ── Section 1: market data ─────────────────────────────────
            elif tool_name == "get_ticker":
                return await self.runner.get_ticker(**arguments)
            elif tool_name == "get_order_book":
                return await self.runner.get_order_book(**arguments)
            elif tool_name == "get_klines":
                return await self.runner.get_klines(**arguments)
            elif tool_name == "get_funding_rate":
                return await self.runner.get_funding_rate(**arguments)
            elif tool_name == "get_open_interest":
                return await self.runner.get_open_interest(**arguments)
            elif tool_name == "get_recent_trades":
                return await self.runner.get_recent_trades(**arguments)

            # ── Section 2: symbol discovery ────────────────────────────
            elif tool_name == "get_futures_symbols":
                return await self.runner.get_futures_symbols()

            # ── Section 3: futures backtest ────────────────────────────
            elif tool_name == "run_futures_backtest":
                return await self.runner.run_futures_backtest(**arguments)

            # ── Section 4: multi-symbol scanner ───────────────────────
            elif tool_name == "scan_futures_backtest":
                return await self.runner.scan_futures_backtest(**arguments)

            # ── Section 5: paper trading ───────────────────────────────
            elif tool_name == "start_paper_trading":
                return await self.runner.start_paper_trading(**arguments)
            elif tool_name == "stop_paper_trading":
                return await self.runner.stop_paper_trading(**arguments)
            elif tool_name == "get_paper_positions":
                return await self.runner.get_paper_positions(**arguments)
            elif tool_name == "get_paper_balance":
                return await self.runner.get_paper_balance(**arguments)
            elif tool_name == "get_paper_trade_history":
                return await self.runner.get_paper_trade_history(**arguments)
            elif tool_name == "reset_paper_account":
                return await self.runner.reset_paper_account(**arguments)

            # ── Section 6: live trading ────────────────────────────────
            elif tool_name == "place_limit_order":
                return await self.runner.place_limit_order(**arguments)
            elif tool_name == "set_leverage":
                return await self.runner.set_leverage(**arguments)
            elif tool_name == "cancel_order":
                return await self.runner.cancel_order(**arguments)

            # ── Section 7: autonomous bots ─────────────────────────────
            elif tool_name == "start_live_bot":
                return await self.runner.start_live_bot(**arguments)
            elif tool_name == "stop_live_bot":
                return await self.runner.stop_live_bot(**arguments)
            elif tool_name == "get_live_bot_status":
                return await self.runner.get_live_bot_status(**arguments)
            elif tool_name == "list_live_bots":
                return await self.runner.list_live_bots()

            else:
                return {"error": f"Unknown tool: {tool_name}", "success": False}

        except Exception as e:
            logger.error("Tool execution error [%s]: %s", tool_name, str(e)[:200])
            return {"error": str(e)[:200], "success": False}

    async def get_resource(self, resource_name: str) -> dict:
        logger.info("Resource request: %s", resource_name)
        try:
            if resource_name == "trading_status":
                return await self.runner.get_risk_metrics()
            elif resource_name == "strategy_library":
                return {
                    "strategies": ["ema_crossover", "momentum", "mean_reversion", "sma_crossover"],
                    "available_sizing_methods": [
                        "FIXED_PERCENTAGE", "KELLY_CRITERION", "VOLATILITY_BASED", "ATR_BASED"
                    ],
                    "autonomous_bot_modes": ["paper", "live"],
                    "supported_timeframes": [
                        "1m", "3m", "5m", "15m", "30m",
                        "1h", "2h", "4h", "6h", "8h", "12h", "1d",
                    ],
                }
            elif resource_name == "backtest_results":
                return {
                    "recent_backtests": [],
                    "metrics": [
                        "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                        "win_rate_pct", "profit_factor",
                    ],
                }
            else:
                return {"error": f"Unknown resource: {resource_name}"}
        except Exception as e:
            logger.error("Resource fetch error: %s", str(e)[:200])
            return {"error": str(e)[:200]}
