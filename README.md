# Binance MCP Trading Bot

A Binance Futures trading system built as a Claude MCP server. Talk to it through Claude, and it handles everything from market data lookups to running autonomous trading bots — live or simulated.

---

## What it does

- Executes trades on Binance Futures (USD-M, COIN-M, Spot, Margin)
- Runs backtests across single symbols or hundreds at once
- Operates fully autonomous bots that wake, compute signals, and trade on their own
- Simulates trading with a paper account (no real money needed to test)
- Guards all trades through a risk engine with per-trade and daily limits
- Sends Telegram alerts for orders, SL/TP hits, and daily summaries
- Exposes a live web dashboard at `localhost:8000`

Everything is controlled through Claude via MCP — no UI required for trading.

---

## Setup

**Requirements:** Python 3.12+, Binance API keys

```bash
git clone <repo>
cd binance_mcp

pip install -r requirements.txt

cp .env.json.template .env.json
# fill in your Binance API keys and optional Telegram config

python main.py
```

**Claude Desktop config** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "binance-trading-bot": {
      "command": "python",
      "args": ["/path/to/binance_mcp/main.py"]
    }
  }
}
```

Once connected, Claude has access to all 29 tools below.

---

## MCP Tools (29 total)

### Trading

| Tool | What it does |
|------|-------------|
| `place_market_order` | Execute a market order instantly. Smart defaults for SL/TP/leverage — no need to specify everything. |
| `place_limit_order` | Place a limit order with SL/TP and risk validation. |
| `close_position` | Close an open position at a given price. |
| `cancel_order` | Cancel an open order by order ID. |
| `set_leverage` | Set leverage (1–125x) for a futures symbol before trading. |
| `get_positions` | Fetch open positions filtered by market type. |
| `get_account_balance` | Real Binance account state: wallet balance, available margin, unrealized PnL, all open positions. |

### Market Data

| Tool | What it does |
|------|-------------|
| `get_ticker` | Latest 24h price, bid/ask, volume, and price change for any symbol. |
| `get_order_book` | Bids and asks at configurable depth (up to 100 levels). |
| `get_klines` | Historical OHLCV candles. Supports all 15 timeframes from 1m to 1M. |
| `get_funding_rate` | Current funding rate, mark price, index price, and next funding time. |
| `get_open_interest` | Total open interest for a futures symbol. |
| `get_recent_trades` | Recent public trades (up to 1000). |
| `get_futures_symbols` | Full list of active Binance USD-M perpetual futures (~500–600 symbols). |

### Backtesting

| Tool | What it does |
|------|-------------|
| `run_backtest` | Custom strategy backtest with user-defined entry/exit conditions. |
| `run_futures_backtest` | Leveraged futures backtest for a single symbol using a built-in strategy. Handles multi-year date ranges via paginated candle fetch. |
| `scan_futures_backtest` | Run a strategy across up to 100 symbols at once. Returns ranked results by Sharpe ratio. |

**Built-in strategies:** `ema_crossover` (9/21 EMA), `sma_crossover` (10/30 SMA), `momentum` (20-period), `mean_reversion` (RSI 14)

### Paper Trading

All paper sessions are isolated, in-memory, and support leverage 1–125x.

| Tool | What it does |
|------|-------------|
| `start_paper_trading` | Create a virtual trading session with a starting balance. Returns a session ID. |
| `stop_paper_trading` | Close a paper session (existing positions stay, no new ones). |
| `get_paper_positions` | Open paper positions with unrealized PnL. |
| `get_paper_balance` | Virtual equity, available balance, realized and unrealized PnL. |
| `get_paper_trade_history` | Full trade history for a session. |
| `reset_paper_account` | Wipe positions and history, restore initial balance. |

### Autonomous Bots

Bots run as background asyncio tasks. Each bot wakes every ¼ candle period (minimum 15s), reads the last *completed* bar, computes the signal, and places or closes a position automatically.

| Tool | What it does |
|------|-------------|
| `start_live_bot` | Start an autonomous bot. Set `is_paper=true` for simulation or `false` for live real-money trading. |
| `stop_live_bot` | Stop a bot. Open positions are closed at market price before shutdown. |
| `get_live_bot_status` | Bot state, current position, cumulative PnL, win rate, recent signals, trade history. |
| `list_live_bots` | All running bots and their current status. |

### Risk & Sizing

| Tool | What it does |
|------|-------------|
| `get_risk_metrics` | Internal risk engine state: per-trade limits, daily drawdown tracker, position exposure. |
| `calculate_position_size` | Optimal position size using FIXED_PERCENTAGE, KELLY_CRITERION, VOLATILITY_BASED, or ATR_BASED method. |

---

## Configuration

```json
{
  "binance": {
    "api_key": "YOUR_API_KEY",
    "api_secret": "YOUR_API_SECRET",
    "testnet": true
  },
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "default_chat_id": "YOUR_CHAT_ID"
  },
  "risk": {
    "max_trade_loss_pct": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_open_positions": 10,
    "max_portfolio_risk_pct": 10.0
  },
  "dashboard": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "database": {
    "path": "./data/trading.db",
    "backup_enabled": true,
    "backup_interval_hours": 24
  },
  "logging": {
    "level": "INFO",
    "log_dir": "./logs"
  }
}
```

Start on `testnet: true` until you've verified behavior with your strategies.

---

## Risk Engine

Every trade goes through four circuit breakers before execution:

| Guard | Default | Behavior |
|-------|---------|----------|
| Per-trade max loss | 2% | Hard block on the individual order |
| Daily drawdown kill-switch | 5% | Halts all new trades for the day |
| Max open positions | 10 | Rejects new entries above the limit |
| Portfolio concentration | 10% | Caps risk exposure per position |

These limits are configurable in `.env.json`. The risk engine runs continuous checks every 5 seconds.

---

## Backtesting

The backtesting engine fetches real Binance candle data (paginated for large date ranges), runs tick-by-tick simulation with realistic slippage and commissions, and reports:

- Total return, CAGR, Sharpe ratio
- Max drawdown, volatility
- Win rate, profit factor, expectancy
- Recovery factor

`scan_futures_backtest` runs this across multiple symbols in sequence and surfaces the best performers — useful for finding which pairs a strategy actually works on before deploying capital.

---

## Security

API keys are never stored in plaintext. The vault uses:

- **Fernet symmetric encryption** (from the `cryptography` library)
- **PBKDF2 key derivation** with 480,000 iterations
- Salt stored separately from the encrypted vault file

All Binance API connections use SSL/TLS. Rate limiting is handled automatically.

---

## Dashboard

A live web dashboard runs at `http://localhost:8000` showing:

- Account equity and PnL
- Risk exposure and drawdown
- Open positions
- Trade history and daily stats

Updates via WebSocket — no manual refresh needed.

---

## Telegram Alerts

When configured, the bot sends alerts for:

- Order executed / position closed (with PnL)
- Risk breach (critical violations)
- Daily loss warning / drawdown warning
- Max positions reached
- Take profit / stop loss triggered
- Daily summary
- Account status updates

Alerts are throttled to prevent spam.

---

## Project Structure

```
binance_mcp/
├── core/
│   ├── security/        # Fernet vault, PBKDF2 key derivation
│   ├── config/          # Config schema and manager
│   ├── database/        # SQLite with async pooling (aiosqlite)
│   └── logging/         # Structured logging
├── exchange/
│   ├── clients/         # Spot, USD-M Futures, COIN-M Futures, Margin
│   ├── ccxt_client.py   # Async ccxt wrapper for futures data
│   └── paper_session.py # Paper trading sessions
├── risk/
│   ├── guards.py        # Circuit breakers
│   ├── sizing.py        # Position sizing methods
│   └── manager.py       # Real-time risk monitoring
├── backtesting/
│   ├── engine/          # Tick-by-tick simulator
│   ├── metrics/         # Performance metrics calculator
│   └── orchestrator.py  # Backtest runner and scanner
├── trading/
│   └── autonomous_engine.py  # AutonomousBot + BotManager
├── mcp_app/
│   ├── server/runner.py # MCPServerRunner (all tool implementations)
│   └── protocol.py      # Tool registry and dispatcher (29 tools)
├── dashboard/
│   ├── server.py        # FastAPI app
│   ├── routes.py        # REST API endpoints
│   └── public/          # Web frontend
├── notifications/       # Telegram alerts
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Docker

```bash
# Build and run
docker build -t binance-trading-bot:latest .
docker-compose up -d

# Logs
docker logs -f binance-trading-bot

# With volume mounts for config and data
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/.env.json:/app/.env.json \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  binance-trading-bot:latest
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Specific test file
pytest tests/integration/test_phase3_risk.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

---

## Stack

| Layer | Library |
|-------|---------|
| MCP server | `mcp` |
| Exchange API | `ccxt`, `aiohttp`, Binance REST |
| Web dashboard | `fastapi`, `uvicorn`, `websockets` |
| Data processing | `pandas`, `numpy` |
| Security | `cryptography` (Fernet + PBKDF2) |
| Database | `aiosqlite` (SQLite) |
| Validation | `pydantic` |
| HTTP client | `httpx`, `requests` |

---

## Notes

- Always test new strategies on testnet or paper mode first
- The autonomous bot acts on the **last completed bar** — not the still-forming current candle
- `scan_futures_backtest` can scan up to 100 symbols but will take time — use a smaller `max_symbols` for quick checks
- Database and logs are written to `./data/` and `./logs/` — back these up if running long-term

---

## License

Use at your own risk. This is a trading tool — real money can be lost. Test thoroughly before going live.
