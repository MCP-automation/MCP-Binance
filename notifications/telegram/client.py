from __future__ import annotations
import logging
import aiohttp
from typing import Optional
from datetime import datetime
from decimal import Decimal
import asyncio
from collections import deque

logger = logging.getLogger(__name__)


class TelegramMessage:
    def __init__(
        self,
        chat_id: str,
        message_type: str,
        content: str,
        metadata: dict = None,
    ):
        self.chat_id = chat_id
        self.message_type = message_type
        self.content = content
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()
        self.retry_count = 0
        self.max_retries = 3


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        default_chat_id: str,
        max_queue_size: int = 1000,
    ):
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.max_queue_size = max_queue_size
        self.message_queue: deque = deque(maxlen=max_queue_size)
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_connected = False
        self.api_base_url = f"https://api.telegram.org/bot{bot_token}"

    async def initialize(self) -> bool:
        try:
            self.session = aiohttp.ClientSession()
            result = await self.test_connection()
            self.is_connected = result
            if result:
                logger.info("Telegram client initialized successfully")
            else:
                logger.error("Telegram connection test failed")
            return result
        except Exception as e:
            logger.error("Error initializing Telegram client: %s", str(e)[:100])
            self.is_connected = False
            return False

    async def shutdown(self) -> None:
        if self.session:
            await self.session.close()
            self.is_connected = False
            logger.info("Telegram client shut down")

    async def test_connection(self) -> bool:
        try:
            async with self.session.get(f"{self.api_base_url}/getMe") as response:
                return response.status == 200
        except Exception as e:
            logger.error("Telegram connection test error: %s", str(e)[:100])
            return False

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        chat_id = chat_id or self.default_chat_id

        if not self.is_connected or not self.session:
            logger.warning("Telegram client not connected, queueing message")
            msg = TelegramMessage(chat_id, "text", text)
            self.message_queue.append(msg)
            return False

        try:
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }

            async with self.session.post(
                f"{self.api_base_url}/sendMessage",
                json=data,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    logger.debug("Telegram message sent successfully")
                    return True
                else:
                    logger.error("Telegram send error: %d", response.status)
                    msg = TelegramMessage(chat_id, "text", text)
                    self.message_queue.append(msg)
                    return False

        except Exception as e:
            logger.error("Error sending Telegram message: %s", str(e)[:100])
            msg = TelegramMessage(chat_id, "text", text)
            self.message_queue.append(msg)
            return False

    async def send_order_notification(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> bool:
        message = f"""
📊 <b>Order Executed</b>
━━━━━━━━━━━━━━━━━
Symbol: <code>{symbol}</code>
Side: <b>{side}</b>
Quantity: {quantity}
Price: ${price}
Stop Loss: ${stop_loss if stop_loss else 'N/A'}
Take Profit: ${take_profit if take_profit else 'N/A'}
Time: {datetime.utcnow().strftime('%H:%M:%S')}
"""
        return await self.send_message(message.strip())

    async def send_position_closed(
        self,
        symbol: str,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        pnl: Decimal,
        pnl_pct: Decimal,
        exit_reason: str,
    ) -> bool:
        emoji = "✅" if pnl > 0 else "❌"
        message = f"""
{emoji} <b>Position Closed</b>
━━━━━━━━━━━━━━━━━
Symbol: <code>{symbol}</code>
Entry: ${entry_price}
Exit: ${exit_price}
Quantity: {quantity}
P&L: ${pnl} ({pnl_pct:.2f}%)
Reason: {exit_reason}
Time: {datetime.utcnow().strftime('%H:%M:%S')}
"""
        return await self.send_message(message.strip())

    async def send_risk_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        metric_value: Optional[Decimal] = None,
        threshold: Optional[Decimal] = None,
    ) -> bool:
        emoji_map = {
            "CRITICAL": "🚨",
            "WARNING": "⚠️",
            "INFO": "ℹ️",
        }
        emoji = emoji_map.get(severity, "📌")

        notification = f"""
{emoji} <b>Risk Alert - {severity}</b>
━━━━━━━━━━━━━━━━━
Type: {alert_type}
Message: {message}
"""

        if metric_value is not None and threshold is not None:
            notification += f"Value: {metric_value} (Threshold: {threshold})\n"

        notification += f"Time: {datetime.utcnow().strftime('%H:%M:%S')}"

        return await self.send_message(notification.strip())

    async def send_daily_summary(
        self,
        equity: Decimal,
        daily_pnl: Decimal,
        daily_pnl_pct: Decimal,
        trades_count: int,
        win_rate: Decimal,
        drawdown: Decimal,
    ) -> bool:
        status_emoji = "📈" if daily_pnl > 0 else "📉"
        message = f"""
{status_emoji} <b>Daily Summary</b>
━━━━━━━━━━━━━━━━━
Account Equity: ${equity}
Daily P&L: ${daily_pnl} ({daily_pnl_pct:.2f}%)
Trades: {trades_count}
Win Rate: {win_rate:.1f}%
Drawdown: {drawdown:.2f}%
Time: {datetime.utcnow().strftime('%H:%M:%S')}
"""
        return await self.send_message(message.strip())

    async def send_status_update(
        self,
        status: str,
        open_positions: int,
        total_risk_pct: Decimal,
        is_within_limits: bool,
    ) -> bool:
        status_emoji = "🟢" if is_within_limits else "🔴"
        message = f"""
{status_emoji} <b>Trading Status</b>
━━━━━━━━━━━━━━━━━
Status: {status}
Open Positions: {open_positions}
Total Risk: {total_risk_pct:.2f}%
Within Limits: {'Yes' if is_within_limits else 'No'}
Time: {datetime.utcnow().strftime('%H:%M:%S')}
"""
        return await self.send_message(message.strip())

    def queue_size(self) -> int:
        return len(self.message_queue)

    async def flush_queue(self) -> int:
        flushed_count = 0

        while self.message_queue and self.is_connected:
            msg = self.message_queue.popleft()

            if msg.retry_count < msg.max_retries:
                success = await self.send_message(msg.content, msg.chat_id)
                if not success:
                    msg.retry_count += 1
                    self.message_queue.append(msg)
                else:
                    flushed_count += 1
            else:
                logger.warning("Message discarded after max retries: %s", msg.message_type)

        return flushed_count
