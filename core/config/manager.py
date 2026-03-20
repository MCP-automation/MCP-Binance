from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .schema import AppConfig


class ConfigError(Exception):
    pass


class ConfigManager:
    _CONFIG_FILE = "config.json"

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = config_dir / self._CONFIG_FILE
        self._config: AppConfig | None = None

    @property
    def is_configured(self) -> bool:
        return self._config_path.exists()

    def load(self) -> AppConfig:
        if not self.is_configured:
            self._config = AppConfig()
            self.save()
            return self._resolve_paths(self._config)
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            self._config = AppConfig.model_validate(raw)
            return self._resolve_paths(self._config)
        except Exception as exc:
            raise ConfigError(f"Failed to load configuration: {exc}") from exc

    def _resolve_paths(self, config: AppConfig) -> AppConfig:
        root_dir = self._config_dir.parent
        
        # Ensure database path is absolute
        if not config.database.path.is_absolute():
            config.database.path = root_dir / config.database.path
            
        # Ensure logging directory is absolute
        if not config.logging.log_dir.is_absolute():
            config.logging.log_dir = root_dir / config.logging.log_dir
            
        return config

    def save(self) -> None:
        if self._config is None:
            raise ConfigError("No configuration loaded. Call load() first.")
        tmp_path = self._config_path.with_suffix(".tmp")
        tmp_path.write_text(
            self._config.model_dump_json(indent=2), encoding="utf-8"
        )
        tmp_path.replace(self._config_path)

    def get(self) -> AppConfig:
        if self._config is None:
            return self.load()
        return self._config

    def update(self, **kwargs: Any) -> AppConfig:
        current = self.get()
        updated_data = current.model_dump()
        for key, value in kwargs.items():
            if key not in updated_data:
                raise ConfigError(f"Unknown configuration key: '{key}'")
            updated_data[key] = value
        self._config = AppConfig.model_validate(updated_data)
        self.save()
        return self._config

    def update_nested(self, section: str, **kwargs: Any) -> AppConfig:
        current = self.get()
        updated_data = current.model_dump()
        if section not in updated_data:
            raise ConfigError(f"Unknown configuration section: '{section}'")
        updated_data[section].update(kwargs)
        self._config = AppConfig.model_validate(updated_data)
        self.save()
        return self._config

    def reset_to_defaults(self) -> AppConfig:
        self._config = AppConfig()
        self.save()
        return self._config
