from __future__ import annotations
import logging
from typing import Optional
import asyncio
from uvicorn import Server, Config
import threading

logger = logging.getLogger(__name__)


class DashboardManager:
    def __init__(
        self,
        app_context,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.app_context = app_context
        self.host = host
        self.port = port
        self.server: Optional[Server] = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_running = False

    async def start(self) -> None:
        from dashboard.server import create_app

        try:
            app = create_app(self.app_context)
            config = Config(
                app=app,
                host=self.host,
                port=self.port,
                log_level="info",
                access_log=False,
            )
            self.server = Server(config)

            self.is_running = True
            logger.info("Dashboard server starting on http://%s:%d", self.host, self.port)

            await self.server.serve()

        except Exception as e:
            logger.error("Error starting dashboard server: %s", str(e)[:200])
            self.is_running = False

    async def stop(self) -> None:
        if self.server:
            self.is_running = False
            self.server.should_exit = True
            logger.info("Dashboard server stopped")

    def start_in_thread(self) -> None:
        loop = asyncio.new_event_loop()

        def run_server():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.start())

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        logger.info("Dashboard server thread started")

    def stop_server(self) -> None:
        if self.is_running and self.server:
            self.is_running = False
            self.server.should_exit = True
            logger.info("Dashboard server shutdown initiated")

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "url": f"http://{self.host}:{self.port}" if self.host != "0.0.0.0" else f"http://localhost:{self.port}",
        }
