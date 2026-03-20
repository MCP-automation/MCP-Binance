import pytest
from pathlib import Path
import json
import tempfile

from scripts.config_manager import (
    EnvConfigManager,
    DeploymentConfig,
    BinanceConfig,
    TelegramConfig,
    RiskConfig,
    DashboardConfig,
    DatabaseConfig,
    LoggingConfig,
)
from scripts.deployment import (
    DockerfileBuilder,
    DockerComposeBuilder,
    EnvFileBuilder,
    DockerIgnoreBuilder,
    DeploymentPackager,
)


class TestBinanceConfig:
    def test_valid_config(self):
        config = BinanceConfig(
            api_key="test_api_key_12345",
            api_secret="test_api_secret_12345",
        )
        assert config.api_key == "test_api_key_12345"
        assert config.testnet is False
        assert config.sandbox is True

    def test_invalid_api_key(self):
        with pytest.raises(ValueError):
            BinanceConfig(
                api_key="short",
                api_secret="test_api_secret_12345",
            )


class TestTelegramConfig:
    def test_valid_config(self):
        config = TelegramConfig(
            bot_token="123456789:ABCDEFghijklmnop",
            default_chat_id="9876543210",
        )
        assert config.bot_token == "123456789:ABCDEFghijklmnop"

    def test_invalid_bot_token(self):
        with pytest.raises(ValueError):
            TelegramConfig(
                bot_token="short",
                default_chat_id="9876543210",
            )


class TestRiskConfig:
    def test_default_values(self):
        config = RiskConfig()
        assert config.max_trade_loss_pct == 2.0
        assert config.max_daily_loss_pct == 5.0
        assert config.max_open_positions == 10

    def test_custom_values(self):
        config = RiskConfig(
            max_trade_loss_pct=3.0,
            max_daily_loss_pct=7.0,
            max_open_positions=20,
        )
        assert config.max_trade_loss_pct == 3.0
        assert config.max_daily_loss_pct == 7.0


class TestDashboardConfig:
    def test_default_values(self):
        config = DashboardConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.debug is False

    def test_custom_port(self):
        config = DashboardConfig(port=9000)
        assert config.port == 9000


class TestDatabaseConfig:
    def test_default_values(self):
        config = DatabaseConfig()
        assert config.backup_enabled is True
        assert config.backup_interval_hours == 24

    def test_custom_backup_interval(self):
        config = DatabaseConfig(backup_interval_hours=12)
        assert config.backup_interval_hours == 12


class TestLoggingConfig:
    def test_default_values(self):
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.max_file_size_mb == 10

    def test_custom_level(self):
        config = LoggingConfig(level="DEBUG")
        assert config.level == "DEBUG"


class TestDeploymentConfig:
    def test_minimal_config(self):
        config = DeploymentConfig(
            binance=BinanceConfig(
                api_key="test_api_key_12345",
                api_secret="test_api_secret_12345",
            )
        )
        assert config.binance is not None
        assert config.risk.max_trade_loss_pct == 2.0

    def test_full_config(self):
        config = DeploymentConfig(
            binance=BinanceConfig(
                api_key="test_api_key_12345",
                api_secret="test_api_secret_12345",
            ),
            telegram=TelegramConfig(
                bot_token="123456789:ABCDEFghijklmnop",
                default_chat_id="9876543210",
            ),
        )
        assert config.binance is not None
        assert config.telegram is not None


class TestEnvConfigManager:
    def test_load_from_dict(self):
        manager = EnvConfigManager()
        data = {
            "binance": {
                "api_key": "test_api_key_12345",
                "api_secret": "test_api_secret_12345",
            }
        }
        result = manager.load_from_dict(data)
        assert result is True
        assert manager.config is not None

    def test_get_config(self):
        manager = EnvConfigManager()
        data = {
            "binance": {
                "api_key": "test_api_key_12345",
                "api_secret": "test_api_secret_12345",
            }
        }
        manager.load_from_dict(data)
        config = manager.get_config()
        assert config is not None

    def test_validate(self):
        manager = EnvConfigManager()
        data = {
            "binance": {
                "api_key": "test_api_key_12345",
                "api_secret": "test_api_secret_12345",
            }
        }
        manager.load_from_dict(data)
        result = manager.validate()
        assert result is True

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.json"

            manager = EnvConfigManager(str(env_file))
            data = {
                "binance": {
                    "api_key": "test_api_key_12345",
                    "api_secret": "test_api_secret_12345",
                }
            }
            manager.load_from_dict(data)
            manager.save_to_file()

            manager2 = EnvConfigManager(str(env_file))
            result = manager2.load_from_file()
            assert result is True
            assert manager2.config is not None


class TestDockerfileBuilder:
    def test_build_content(self):
        builder = DockerfileBuilder()
        content = builder.build()
        assert "FROM python:3.12-slim" in content
        assert "WORKDIR /app" in content
        assert "pip install" in content

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile_path = Path(tmpdir) / "Dockerfile"
            builder = DockerfileBuilder()
            result = builder.save(str(dockerfile_path))
            assert result is True
            assert dockerfile_path.exists()


class TestDockerComposeBuilder:
    def test_build_content(self):
        builder = DockerComposeBuilder()
        content = builder.build()
        assert "version: '3.8'" in content
        assert "services:" in content
        assert "healthcheck:" in content

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_path = Path(tmpdir) / "docker-compose.yml"
            builder = DockerComposeBuilder()
            result = builder.save(str(compose_path))
            assert result is True
            assert compose_path.exists()


class TestEnvFileBuilder:
    def test_build_template(self):
        builder = EnvFileBuilder()
        content = builder.build_template()
        assert "binance" in content
        assert "telegram" in content
        assert "risk" in content
        assert json.loads(content) is not None

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.json.template"
            builder = EnvFileBuilder()
            result = builder.save(str(env_path))
            assert result is True
            assert env_path.exists()


class TestDockerIgnoreBuilder:
    def test_build_content(self):
        builder = DockerIgnoreBuilder()
        content = builder.build()
        assert "__pycache__" in content
        assert "*.pyc" in content
        assert ".env" in content

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ignore_path = Path(tmpdir) / ".dockerignore"
            builder = DockerIgnoreBuilder()
            result = builder.save(str(ignore_path))
            assert result is True
            assert ignore_path.exists()


class TestDeploymentPackager:
    def test_create_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packager = DeploymentPackager()
            result = packager.create_all(tmpdir)
            assert result is True

            assert (Path(tmpdir) / "Dockerfile").exists()
            assert (Path(tmpdir) / "docker-compose.yml").exists()
            assert (Path(tmpdir) / ".env.json.template").exists()
            assert (Path(tmpdir) / ".dockerignore").exists()

    def test_summary(self):
        packager = DeploymentPackager()
        summary = packager.create_deployment_summary()
        assert "DEPLOYMENT SUMMARY" in summary
        assert "docker build" in summary


class TestConfigurationValidation:
    def test_invalid_risk_values(self):
        with pytest.raises(ValueError):
            RiskConfig(max_trade_loss_pct=0)

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            DashboardConfig(port=70000)

    def test_invalid_database_path(self):
        config = DatabaseConfig(path="/invalid/path")
        assert config.path == "/invalid/path"


class TestDeploymentIntegration:
    def test_full_deployment_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / ".env.json"
            config_data = {
                "binance": {
                    "api_key": "test_api_key_12345",
                    "api_secret": "test_api_secret_12345",
                }
            }

            manager = EnvConfigManager(str(config_file))
            manager.load_from_dict(config_data)
            manager.save_to_file()

            packager = DeploymentPackager()
            packager.create_all(tmpdir)

            assert (Path(tmpdir) / ".env.json").exists()
            assert (Path(tmpdir) / "Dockerfile").exists()
            assert (Path(tmpdir) / "docker-compose.yml").exists()
