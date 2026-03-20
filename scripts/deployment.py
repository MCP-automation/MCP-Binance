from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class DockerfileBuilder:
    def __init__(self, app_name: str = "binance-trading-bot", python_version: str = "3.12"):
        self.app_name = app_name
        self.python_version = python_version

    def build(self) -> str:
        content = f"""FROM python:{self.python_version}-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard.server:app", "--host", "0.0.0.0", "--port", "8000"]
"""
        return content.strip()

    def save(self, path: Optional[str] = None) -> bool:
        try:
            save_path = Path(path or "Dockerfile")
            save_path.write_text(self.build())
            logger.info("Dockerfile created at %s", save_path)
            return True
        except Exception as e:
            logger.error("Error creating Dockerfile: %s", str(e)[:100])
            return False


class DockerComposeBuilder:
    def __init__(self, app_name: str = "binance-trading-bot"):
        self.app_name = app_name

    def build(self) -> str:
        content = f"""version: '3.8'

services:
  {self.app_name}:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {self.app_name}
    environment:
      - TRADING_ENV=production
      - PYTHONUNBUFFERED=1
    volumes:
      - ./.env.json:/app/.env.json:ro
      - ./logs:/app/logs
      - ./data:/app/data
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - trading-network

networks:
  trading-network:
    driver: bridge
"""
        return content.strip()

    def save(self, path: Optional[str] = None) -> bool:
        try:
            save_path = Path(path or "docker-compose.yml")
            save_path.write_text(self.build())
            logger.info("docker-compose.yml created at %s", save_path)
            return True
        except Exception as e:
            logger.error("Error creating docker-compose.yml: %s", str(e)[:100])
            return False


class EnvFileBuilder:
    def __init__(self):
        pass

    def build_template(self) -> str:
        content = """{
  "binance": {
    "api_key": "YOUR_BINANCE_API_KEY",
    "api_secret": "YOUR_BINANCE_API_SECRET",
    "testnet": true,
    "sandbox": true
  },
  "telegram": {
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "default_chat_id": "YOUR_TELEGRAM_CHAT_ID"
  },
  "risk": {
    "max_trade_loss_pct": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_open_positions": 10,
    "max_portfolio_risk_pct": 10.0
  },
  "dashboard": {
    "host": "0.0.0.0",
    "port": 8000,
    "debug": false
  },
  "database": {
    "path": "./data/trading.db",
    "backup_enabled": true,
    "backup_interval_hours": 24
  },
  "logging": {
    "level": "INFO",
    "log_dir": "./logs",
    "max_file_size_mb": 10,
    "backup_count": 5
  }
}
"""
        return content.strip()

    def save(self, path: Optional[str] = None) -> bool:
        try:
            save_path = Path(path or ".env.json.template")
            save_path.write_text(self.build_template())
            logger.info("Environment template created at %s", save_path)
            return True
        except Exception as e:
            logger.error("Error creating env template: %s", str(e)[:100])
            return False


class DockerIgnoreBuilder:
    def __init__(self):
        self.patterns = [
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".pytest_cache",
            ".env",
            ".env.json",
            "logs",
            "data",
            ".git",
            ".gitignore",
            "*.log",
            ".DS_Store",
            "tests",
        ]

    def build(self) -> str:
        return "\n".join(self.patterns)

    def save(self, path: Optional[str] = None) -> bool:
        try:
            save_path = Path(path or ".dockerignore")
            save_path.write_text(self.build())
            logger.info(".dockerignore created at %s", save_path)
            return True
        except Exception as e:
            logger.error("Error creating .dockerignore: %s", str(e)[:100])
            return False


class DeploymentPackager:
    def __init__(self, app_name: str = "binance-trading-bot"):
        self.app_name = app_name
        self.dockerfile_builder = DockerfileBuilder(app_name)
        self.compose_builder = DockerComposeBuilder(app_name)
        self.env_builder = EnvFileBuilder()
        self.ignore_builder = DockerIgnoreBuilder()

    def create_all(self, base_path: Optional[str] = None) -> bool:
        base = Path(base_path or ".")

        try:
            self.dockerfile_builder.save(str(base / "Dockerfile"))
            self.compose_builder.save(str(base / "docker-compose.yml"))
            self.env_builder.save(str(base / ".env.json.template"))
            self.ignore_builder.save(str(base / ".dockerignore"))

            logger.info("All deployment files created successfully")
            return True
        except Exception as e:
            logger.error("Error creating deployment files: %s", str(e)[:100])
            return False

    def create_deployment_summary(self) -> str:
        summary = f"""
# {self.app_name.upper()} DEPLOYMENT SUMMARY

## Files Created

1. **Dockerfile** - Container image definition
2. **docker-compose.yml** - Multi-service orchestration
3. **.env.json.template** - Configuration template
4. **.dockerignore** - Docker build exclusions

## Quick Start

### 1. Configure Environment
```bash
cp .env.json.template .env.json
# Edit .env.json with your credentials
```

### 2. Build Image
```bash
docker build -t {self.app_name}:latest .
```

### 3. Run Container
```bash
docker-compose up -d
```

### 4. View Logs
```bash
docker logs -f {self.app_name}
```

## Volumes

- **logs/** - Application logs
- **data/** - SQLite database and data
- **.env.json** - Configuration file

## Ports

- **8000** - Dashboard web interface

## Health Check

```bash
curl http://localhost:8000/api/health
```

## Services

- Trading system (24/7)
- Risk management (real-time)
- Dashboard (web UI)
- Telegram notifications (async)

## Environment Variables

All configuration in **.env.json**:
- Binance API credentials
- Telegram bot token
- Risk parameters
- Database settings
- Logging configuration

## Production Considerations

- Use environment variables for secrets
- Enable health checks
- Set up log rotation
- Regular database backups
- Monitor memory usage
- Use restart policies

## Troubleshooting

### Container won't start
```bash
docker logs {self.app_name}
```

### Health check failing
```bash
docker ps
# Check HEALTH column
```

### Volume mounting issues
```bash
docker inspect {self.app_name}
# Check Mounts section
```
"""
        return summary.strip()
