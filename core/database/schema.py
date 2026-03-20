SCHEMA_VERSION = 1

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    applied_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    description   TEXT    NOT NULL
)
"""

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT    PRIMARY KEY,
    started_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at      TEXT,
    trading_mode  TEXT    NOT NULL,
    mcp_version   TEXT    NOT NULL,
    metadata      TEXT    NOT NULL DEFAULT '{}'
)
"""

CREATE_STRATEGIES_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    id                  TEXT    PRIMARY KEY,
    version             INTEGER NOT NULL DEFAULT 1,
    name                TEXT    NOT NULL,
    description         TEXT    NOT NULL DEFAULT '',
    timeframe           TEXT    NOT NULL,
    market_type         TEXT    NOT NULL,
    indicators          TEXT    NOT NULL DEFAULT '[]',
    entry_conditions    TEXT    NOT NULL DEFAULT '[]',
    exit_conditions     TEXT    NOT NULL DEFAULT '[]',
    stop_loss_pct       REAL,
    take_profit_pct     REAL,
    trailing_stop_pct   REAL,
    raw_config          TEXT    NOT NULL DEFAULT '{}',
    is_active           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

CREATE_STRATEGIES_VERSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_strategies_version ON strategies(name, version)
"""

CREATE_BACKTESTS_TABLE = """
CREATE TABLE IF NOT EXISTS backtests (
    id                  TEXT    PRIMARY KEY,
    strategy_id         TEXT    NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    symbol              TEXT,
    symbols             TEXT    NOT NULL DEFAULT '[]',
    timeframe           TEXT    NOT NULL,
    start_date          TEXT    NOT NULL,
    end_date            TEXT    NOT NULL,
    initial_capital     REAL    NOT NULL,
    final_capital       REAL,
    total_pnl           REAL,
    total_pnl_pct       REAL,
    max_drawdown_pct    REAL,
    sharpe_ratio        REAL,
    sortino_ratio       REAL,
    calmar_ratio        REAL,
    win_rate_pct        REAL,
    profit_factor       REAL,
    total_trades        INTEGER,
    winning_trades      INTEGER,
    losing_trades       INTEGER,
    avg_trade_duration  REAL,
    avg_rr_ratio        REAL,
    annualized_return   REAL,
    status              TEXT    NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    equity_curve        TEXT    NOT NULL DEFAULT '[]',
    monthly_returns     TEXT    NOT NULL DEFAULT '{}',
    per_symbol_stats    TEXT    NOT NULL DEFAULT '{}',
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at        TEXT
)
"""

CREATE_BACKTESTS_STRATEGY_IDX = """
CREATE INDEX IF NOT EXISTS idx_backtests_strategy ON backtests(strategy_id)
"""

CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT    PRIMARY KEY,
    client_order_id     TEXT    UNIQUE,
    exchange_order_id   TEXT,
    session_id          TEXT    REFERENCES sessions(id),
    strategy_id         TEXT    REFERENCES strategies(id),
    symbol              TEXT    NOT NULL,
    market_type         TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    order_type          TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'pending',
    price               REAL,
    stop_price          REAL,
    quantity            REAL    NOT NULL,
    filled_quantity     REAL    NOT NULL DEFAULT 0.0,
    avg_fill_price      REAL,
    commission          REAL    NOT NULL DEFAULT 0.0,
    commission_asset    TEXT,
    is_paper            INTEGER NOT NULL DEFAULT 0,
    time_in_force       TEXT    NOT NULL DEFAULT 'GTC',
    reduce_only         INTEGER NOT NULL DEFAULT 0,
    close_position      INTEGER NOT NULL DEFAULT 0,
    raw_exchange_data   TEXT    NOT NULL DEFAULT '{}',
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    filled_at           TEXT
)
"""

CREATE_ORDERS_SYMBOL_IDX = """
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol, created_at)
"""

CREATE_ORDERS_STATUS_IDX = """
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)
"""

CREATE_ORDERS_SESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id)
"""

CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS positions (
    id                  TEXT    PRIMARY KEY,
    session_id          TEXT    REFERENCES sessions(id),
    strategy_id         TEXT    REFERENCES strategies(id),
    symbol              TEXT    NOT NULL,
    market_type         TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    entry_price         REAL    NOT NULL,
    current_price       REAL,
    quantity            REAL    NOT NULL,
    leverage            REAL    NOT NULL DEFAULT 1.0,
    unrealized_pnl      REAL    NOT NULL DEFAULT 0.0,
    realized_pnl        REAL    NOT NULL DEFAULT 0.0,
    stop_loss_price     REAL,
    take_profit_price   REAL,
    trailing_stop_pct   REAL,
    is_paper            INTEGER NOT NULL DEFAULT 0,
    is_open             INTEGER NOT NULL DEFAULT 1,
    entry_order_id      TEXT    REFERENCES orders(id),
    exit_order_id       TEXT    REFERENCES orders(id),
    opened_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    closed_at           TEXT,
    duration_seconds    REAL,
    metadata            TEXT    NOT NULL DEFAULT '{}'
)
"""

CREATE_POSITIONS_SYMBOL_IDX = """
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol, is_open)
"""

CREATE_POSITIONS_SESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_positions_session ON positions(session_id, is_open)
"""

CREATE_TRADES_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id                  TEXT    PRIMARY KEY,
    position_id         TEXT    NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    session_id          TEXT    REFERENCES sessions(id),
    strategy_id         TEXT    REFERENCES strategies(id),
    symbol              TEXT    NOT NULL,
    market_type         TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    entry_price         REAL    NOT NULL,
    exit_price          REAL    NOT NULL,
    quantity            REAL    NOT NULL,
    leverage            REAL    NOT NULL DEFAULT 1.0,
    gross_pnl           REAL    NOT NULL,
    commission          REAL    NOT NULL DEFAULT 0.0,
    net_pnl             REAL    NOT NULL,
    pnl_pct             REAL    NOT NULL,
    duration_seconds    REAL    NOT NULL,
    is_paper            INTEGER NOT NULL DEFAULT 0,
    entry_reason        TEXT    NOT NULL DEFAULT '',
    exit_reason         TEXT    NOT NULL DEFAULT '',
    closed_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

CREATE_TRADES_SYMBOL_IDX = """
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol, closed_at)
"""

CREATE_TRADES_SESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id, closed_at)
"""

CREATE_TRADES_STRATEGY_IDX = """
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)
"""

CREATE_RISK_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS risk_events (
    id              TEXT    PRIMARY KEY,
    session_id      TEXT    REFERENCES sessions(id),
    event_type      TEXT    NOT NULL,
    severity        TEXT    NOT NULL,
    symbol          TEXT,
    description     TEXT    NOT NULL,
    trigger_value   REAL,
    threshold_value REAL,
    action_taken    TEXT    NOT NULL DEFAULT '',
    resolved        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at     TEXT
)
"""

CREATE_RISK_EVENTS_SESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_risk_events_session ON risk_events(session_id, created_at)
"""

CREATE_MARKET_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    id          TEXT    PRIMARY KEY,
    symbol      TEXT    NOT NULL,
    market_type TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL,
    open_time   TEXT    NOT NULL,
    close_time  TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'websocket'
)
"""

CREATE_MARKET_SNAPSHOTS_SYMBOL_IDX = """
CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol ON market_snapshots(symbol, timeframe, open_time)
"""

CREATE_NOTIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id              TEXT    PRIMARY KEY,
    channel         TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    payload         TEXT    NOT NULL DEFAULT '{}',
    message         TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    sent_at         TEXT
)
"""

CREATE_NOTIFICATIONS_STATUS_IDX = """
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status, created_at)
"""

CREATE_PAPER_PORTFOLIO_TABLE = """
CREATE TABLE IF NOT EXISTS paper_portfolios (
    id              TEXT    PRIMARY KEY,
    session_id      TEXT    NOT NULL UNIQUE REFERENCES sessions(id),
    balance_usdt    REAL    NOT NULL,
    initial_balance REAL    NOT NULL,
    total_pnl       REAL    NOT NULL DEFAULT 0.0,
    realized_pnl    REAL    NOT NULL DEFAULT 0.0,
    unrealized_pnl  REAL    NOT NULL DEFAULT 0.0,
    peak_balance    REAL    NOT NULL,
    max_drawdown    REAL    NOT NULL DEFAULT 0.0,
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

ALL_DDL_STATEMENTS: list[str] = [
    CREATE_SCHEMA_VERSION_TABLE,
    CREATE_SESSIONS_TABLE,
    CREATE_STRATEGIES_TABLE,
    CREATE_STRATEGIES_VERSION_IDX,
    CREATE_BACKTESTS_TABLE,
    CREATE_BACKTESTS_STRATEGY_IDX,
    CREATE_ORDERS_TABLE,
    CREATE_ORDERS_SYMBOL_IDX,
    CREATE_ORDERS_STATUS_IDX,
    CREATE_ORDERS_SESSION_IDX,
    CREATE_POSITIONS_TABLE,
    CREATE_POSITIONS_SYMBOL_IDX,
    CREATE_POSITIONS_SESSION_IDX,
    CREATE_TRADES_TABLE,
    CREATE_TRADES_SYMBOL_IDX,
    CREATE_TRADES_SESSION_IDX,
    CREATE_TRADES_STRATEGY_IDX,
    CREATE_RISK_EVENTS_TABLE,
    CREATE_RISK_EVENTS_SESSION_IDX,
    CREATE_MARKET_SNAPSHOTS_TABLE,
    CREATE_MARKET_SNAPSHOTS_SYMBOL_IDX,
    CREATE_NOTIFICATIONS_TABLE,
    CREATE_NOTIFICATIONS_STATUS_IDX,
    CREATE_PAPER_PORTFOLIO_TABLE,
]
