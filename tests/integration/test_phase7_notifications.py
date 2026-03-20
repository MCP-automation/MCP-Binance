import pytest
from decimal import Decimal
from datetime import datetime, timedelta
import asyncio

from notifications.telegram.client import TelegramClient, TelegramMessage
from notifications.telegram.manager import NotificationManager, AlertType, AlertSeverity, AlertTrigger
from notifications.orchestrator import NotificationOrchestrator


class TestTelegramMessage:
    def test_message_creation(self):
        msg = TelegramMessage(
            chat_id="12345",
            message_type="test",
            content="Test message",
        )

        assert msg.chat_id == "12345"
        assert msg.message_type == "test"
        assert msg.content == "Test message"
        assert msg.retry_count == 0

    def test_message_metadata(self):
        metadata = {"symbol": "BTCUSDT", "price": "45000"}
        msg = TelegramMessage(
            chat_id="12345",
            message_type="order",
            content="Order placed",
            metadata=metadata,
        )

        assert msg.metadata == metadata


class TestAlertTrigger:
    def test_trigger_enabled(self):
        trigger = AlertTrigger(AlertType.ORDER_EXECUTED, AlertSeverity.INFO, enabled=True)
        assert trigger.can_trigger() is True

    def test_trigger_disabled(self):
        trigger = AlertTrigger(AlertType.ORDER_EXECUTED, AlertSeverity.INFO, enabled=False)
        assert trigger.can_trigger() is False

    def test_trigger_throttle(self):
        trigger = AlertTrigger(
            AlertType.ORDER_EXECUTED,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=60,
        )

        assert trigger.can_trigger() is True
        trigger.mark_triggered()
        assert trigger.can_trigger() is False

    def test_trigger_throttle_expiration(self):
        trigger = AlertTrigger(
            AlertType.ORDER_EXECUTED,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=1,
        )

        trigger.mark_triggered()
        assert trigger.can_trigger() is False

        import time
        time.sleep(1.1)
        assert trigger.can_trigger() is True


class TestNotificationManager:
    def test_manager_initialization(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        assert len(manager.triggers) > 0
        assert AlertType.ORDER_EXECUTED in manager.triggers

    def test_alert_enabled_by_default(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        assert manager.triggers[AlertType.ORDER_EXECUTED].enabled is True
        assert manager.triggers[AlertType.RISK_BREACH].enabled is True

    def test_enable_disable_alert(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        manager.disable_alert(AlertType.ORDER_EXECUTED)
        assert manager.triggers[AlertType.ORDER_EXECUTED].enabled is False

        manager.enable_alert(AlertType.ORDER_EXECUTED)
        assert manager.triggers[AlertType.ORDER_EXECUTED].enabled is True

    def test_set_throttle(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        manager.set_throttle(AlertType.DAILY_LOSS_WARNING, 600)
        assert manager.triggers[AlertType.DAILY_LOSS_WARNING].throttle_seconds == 600

    def test_get_alert_status(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        status = manager.get_alert_status()
        assert "ORDER_EXECUTED" in status
        assert "enabled" in status["ORDER_EXECUTED"]


class TestAlertTypes:
    def test_all_alert_types_exist(self):
        assert AlertType.ORDER_EXECUTED
        assert AlertType.POSITION_CLOSED
        assert AlertType.RISK_BREACH
        assert AlertType.DAILY_LOSS_WARNING
        assert AlertType.DRAWDOWN_WARNING
        assert AlertType.MAX_POSITIONS_REACHED
        assert AlertType.DAILY_SUMMARY
        assert AlertType.STATUS_UPDATE

    def test_alert_severity_levels(self):
        assert AlertSeverity.INFO
        assert AlertSeverity.WARNING
        assert AlertSeverity.CRITICAL


class TestNotificationOrchestrator:
    def test_orchestrator_initialization(self):
        class MockContext:
            risk_manager = None
            exchange_manager = None

        class MockTelegramClient:
            async def initialize(self):
                return True

        orchestrator = NotificationOrchestrator(MockContext(), "token", "chat_id")
        assert orchestrator.is_initialized is False

    def test_orchestrator_configure_alert(self):
        class MockContext:
            risk_manager = None
            exchange_manager = None

        orchestrator = NotificationOrchestrator(MockContext(), "token", "chat_id")

        result = orchestrator.configure_alert("ORDER_EXECUTED", enabled=False)
        assert result is True

    def test_orchestrator_alert_configuration(self):
        class MockContext:
            risk_manager = None
            exchange_manager = None

        orchestrator = NotificationOrchestrator(MockContext(), "token", "chat_id")
        config = orchestrator.get_alert_configuration()

        assert "ORDER_EXECUTED" in config
        assert "enabled" in config["ORDER_EXECUTED"]


class TestTelegramMessageQueue:
    def test_queue_initialization(self):
        client = TelegramClient("token", "chat_id", max_queue_size=100)
        assert client.queue_size() == 0

    def test_message_queueing(self):
        client = TelegramClient("token", "chat_id", max_queue_size=100)

        msg = TelegramMessage("chat_id", "test", "Test message")
        client.message_queue.append(msg)

        assert client.queue_size() == 1

    def test_queue_max_size(self):
        client = TelegramClient("token", "chat_id", max_queue_size=5)

        for i in range(10):
            msg = TelegramMessage("chat_id", "test", f"Message {i}")
            client.message_queue.append(msg)

        assert client.queue_size() <= 5


class TestAlertThrottling:
    def test_order_executed_throttle(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        trigger = manager.triggers[AlertType.ORDER_EXECUTED]
        assert trigger.throttle_seconds == 0

    def test_risk_breach_throttle(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        trigger = manager.triggers[AlertType.RISK_BREACH]
        assert trigger.throttle_seconds == 60

    def test_daily_summary_throttle(self):
        class MockTelegramClient:
            async def send_message(self, text, chat_id=None, parse_mode="HTML"):
                return True

        client = MockTelegramClient()
        manager = NotificationManager(client)

        trigger = manager.triggers[AlertType.DAILY_SUMMARY]
        assert trigger.throttle_seconds == 86400


class TestNotificationMessageFormats:
    def test_order_executed_message_format(self):
        client = TelegramClient("token", "chat_id")
        assert client.api_base_url == "https://api.telegram.org/bottoken"

    def test_position_closed_emoji(self):
        pass


class TestAlertConfiguration:
    def test_configure_multiple_alerts(self):
        class MockContext:
            risk_manager = None
            exchange_manager = None

        orchestrator = NotificationOrchestrator(MockContext(), "token", "chat_id")

        orchestrator.configure_alert("ORDER_EXECUTED", enabled=False, throttle_seconds=0)
        orchestrator.configure_alert("RISK_BREACH", enabled=True, throttle_seconds=120)

        config = orchestrator.get_alert_configuration()
        assert config["ORDER_EXECUTED"]["enabled"] is False
        assert config["RISK_BREACH"]["throttle_seconds"] == 120
