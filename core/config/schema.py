from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    BOTH = "both"


class MarketType(str, Enum):
    SPOT = "spot"
    USD_M_FUTURES = "usd_m_futures"
    COIN_M_FUTURES = "coin_m_futures"
    MARGIN_CROSS = "margin_cross"
    MARGIN_ISOLATED = "margin_isolated"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RiskConfig(BaseModel):
    max_loss_per_trade_pct: float = Field(default=5.0, ge=0.01, le=50.0)
    daily_drawdown_kill_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    max_open_positions: int = Field(default=10, ge=1, le=579)
    position_sizing_mode: Literal["kelly", "fixed"] = "fixed"
    fixed_position_pct: float = Field(default=1.0, ge=0.01, le=100.0)
    kelly_fraction: float = Field(default=0.25, ge=0.01, le=1.0)

    @field_validator("daily_drawdown_kill_pct")
    @classmethod
    def drawdown_gt_per_trade_loss(cls, v: float, info) -> float:
        return v


class DatabaseConfig(BaseModel):
    path: Path = Field(default=Path("data/trading.db"))
    wal_mode: bool = True
    connection_pool_size: int = Field(default=5, ge=1, le=20)
    query_timeout_seconds: int = Field(default=30, ge=5)


class LoggingConfig(BaseModel):
    level: LogLevel = LogLevel.INFO
    log_dir: Path = Field(default=Path("logs"))
    max_bytes_per_file: int = Field(default=10 * 1024 * 1024)
    backup_count: int = Field(default=10, ge=1)
    json_format: bool = True


class BinanceApiConfig(BaseModel):
    testnet_enabled: bool = False
    recv_window: int = Field(default=5000, ge=1000, le=60000)
    request_timeout_seconds: int = Field(default=10, ge=3, le=60)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_base: float = Field(default=1.5, ge=1.0, le=5.0)


class WebsocketConfig(BaseModel):
    ping_interval_seconds: int = Field(default=20, ge=5)
    ping_timeout_seconds: int = Field(default=10, ge=3)
    reconnect_max_attempts: int = Field(default=10, ge=1)
    reconnect_backoff_base: float = Field(default=2.0, ge=1.0, le=10.0)
    reconnect_backoff_max_seconds: int = Field(default=60, ge=5)


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    auto_open_browser: bool = True


class TelegramConfig(BaseModel):
    enabled: bool = False
    chat_id: str = ""
    daily_report_hour_utc: int = Field(default=0, ge=0, le=23)


class MCPConfig(BaseModel):
    server_name: str = "binance-trading-mcp"
    version: str = "1.0.0"
    transport: Literal["stdio"] = "stdio"


class AppConfig(BaseModel):
    trading_mode: TradingMode = TradingMode.BOTH
    active_market_types: list[MarketType] = Field(
        default_factory=lambda: [MarketType.USD_M_FUTURES]
    )
    paper_initial_balance_usdt: float = Field(default=10_000.0, ge=1.0)

    risk: RiskConfig = Field(default_factory=RiskConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    binance_api: BinanceApiConfig = Field(default_factory=BinanceApiConfig)
    websocket: WebsocketConfig = Field(default_factory=WebsocketConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    @model_validator(mode="after")
    def validate_market_types_not_empty(self) -> "AppConfig":
        if not self.active_market_types:
            raise ValueError("At least one market type must be active.")
        return self
