from __future__ import annotations
import json
import logging
import logging.handlers
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.schema import LoggingConfig


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            payload["extra"] = record.extra
        return json.dumps(payload, ensure_ascii=False)


class _ConsoleFormatter(logging.Formatter):
    _LEVEL_COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        prefix = f"{color}[{ts}] [{record.levelname:<8}]{self._RESET}"
        return f"{prefix} {record.name}: {record.getMessage()}"


class LoggingManager:
    _instance: "LoggingManager | None" = None

    def __init__(self, config: LoggingConfig) -> None:
        self._config = config
        self._configured = False

    @classmethod
    def get_instance(cls) -> "LoggingManager":
        if cls._instance is None:
            raise RuntimeError("LoggingManager has not been initialized.")
        return cls._instance

    @classmethod
    def initialize(cls, config: LoggingConfig) -> "LoggingManager":
        instance = cls(config)
        instance._setup()
        cls._instance = instance
        return instance

    def _setup(self) -> None:
        self._config.log_dir.mkdir(parents=True, exist_ok=True)
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(self._config.level.value)

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(self._config.level.value)
        console_handler.setFormatter(_ConsoleFormatter())
        root_logger.addHandler(console_handler)

        main_log_path = self._config.log_dir / "main.log"
        file_handler = logging.handlers.RotatingFileHandler(
            filename=main_log_path,
            maxBytes=self._config.max_bytes_per_file,
            backupCount=self._config.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(self._config.level.value)
        file_handler.setFormatter(_JsonFormatter())
        root_logger.addHandler(file_handler)

        error_log_path = self._config.log_dir / "errors.log"
        error_handler = logging.handlers.RotatingFileHandler(
            filename=error_log_path,
            maxBytes=self._config.max_bytes_per_file,
            backupCount=self._config.backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(_JsonFormatter())
        root_logger.addHandler(error_handler)

        trade_log_path = self._config.log_dir / "trades.log"
        trade_handler = logging.handlers.RotatingFileHandler(
            filename=trade_log_path,
            maxBytes=self._config.max_bytes_per_file,
            backupCount=self._config.backup_count,
            encoding="utf-8",
        )
        trade_handler.setLevel(logging.INFO)
        trade_handler.setFormatter(_JsonFormatter())
        trade_logger = logging.getLogger("trades")
        trade_logger.addHandler(trade_handler)
        trade_logger.propagate = False

        self._configured = True

    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
