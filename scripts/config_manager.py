from __future__ import annotations
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from pydantic import BaseModel, Field, validator
import json

logger = logging.getLogger(__name__)


class TelegramConfig(BaseModel):
    bot_token: str = Field(..., min_length=10)
    default_chat_id: str = Field(..., min_length=5)

    class Config:
        extra = "forbid"


class BinanceConfig(BaseModel):
    api_key: str = Field(..., min_length=10)
    api_secret: str = Field(..., min_length=10)
    testnet: bool = Field(default=False)
    sandbox: bool = Field(default=True)

    class Config:
        extra = "forbid"


class RiskConfig(BaseModel):
    max_trade_loss_pct: float = Field(default=2.0, gt=0, le=100)
    max_daily_loss_pct: float = Field(default=5.0, gt=0, le=100)
    max_open_positions: int = Field(default=10, gt=0, le=100)
    max_portfolio_risk_pct: float = Field(default=10.0, gt=0, le=100)

    class Config:
        extra = "forbid"


class DashboardConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, gt=0, le=65535)
    debug: bool = Field(default=False)

    class Config:
        extra = "forbid"


class DatabaseConfig(BaseModel):
    path: str = Field(default="./data/trading.db")
    backup_enabled: bool = Field(default=True)
    backup_interval_hours: int = Field(default=24, gt=0, le=168)

    class Config:
        extra = "forbid"


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO")
    log_dir: str = Field(default="./logs")
    max_file_size_mb: int = Field(default=10, gt=0, le=1000)
    backup_count: int = Field(default=5, gt=0, le=100)

    class Config:
        extra = "forbid"


class DeploymentConfig(BaseModel):
    binance: BinanceConfig
    telegram: Optional[TelegramConfig] = None
    risk: RiskConfig = Field(default_factory=RiskConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @validator("binance", pre=True, always=True)
    def validate_binance(cls, v):
        if v is None:
            raise ValueError("Binance configuration is required")
        return v

    class Config:
        extra = "forbid"


class EnvConfigManager:
    def __init__(self, env_file: str = ".env.json"):
        self.env_file = Path(env_file)
        self.config: Optional[DeploymentConfig] = None

    def load_from_file(self) -> bool:
        if not self.env_file.exists():
            logger.error("Environment file not found: %s", self.env_file)
            return False

        try:
            with open(self.env_file, "r") as f:
                data = json.load(f)

            self.config = DeploymentConfig(**data)
            logger.info("Configuration loaded from %s", self.env_file)
            return True
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in config file: %s", str(e)[:100])
            return False
        except Exception as e:
            logger.error("Error loading configuration: %s", str(e)[:100])
            return False

    def load_from_dict(self, data: Dict[str, Any]) -> bool:
        try:
            self.config = DeploymentConfig(**data)
            logger.info("Configuration loaded from dictionary")
            return True
        except Exception as e:
            logger.error("Error loading configuration from dict: %s", str(e)[:100])
            return False

    def save_to_file(self, path: Optional[str] = None) -> bool:
        if not self.config:
            logger.error("No configuration to save")
            return False

        save_path = Path(path or self.env_file)

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)

            with open(save_path, "w") as f:
                json.dump(self.config.dict(), f, indent=2)

            logger.info("Configuration saved to %s", save_path)
            return True
        except Exception as e:
            logger.error("Error saving configuration: %s", str(e)[:100])
            return False

    def validate(self) -> bool:
        if not self.config:
            logger.error("No configuration loaded")
            return False

        try:
            DeploymentConfig(**self.config.dict())
            logger.info("Configuration validation passed")
            return True
        except Exception as e:
            logger.error("Configuration validation failed: %s", str(e)[:100])
            return False

    def get_config(self) -> Optional[DeploymentConfig]:
        return self.config

    def get_binance_config(self) -> Optional[BinanceConfig]:
        return self.config.binance if self.config else None

    def get_telegram_config(self) -> Optional[TelegramConfig]:
        return self.config.telegram if self.config else None

    def get_risk_config(self) -> RiskConfig:
        return self.config.risk if self.config else RiskConfig()

    def get_dashboard_config(self) -> DashboardConfig:
        return self.config.dashboard if self.config else DashboardConfig()

    def get_database_config(self) -> DatabaseConfig:
        return self.config.database if self.config else DatabaseConfig()

    def get_logging_config(self) -> LoggingConfig:
        return self.config.logging if self.config else LoggingConfig()
