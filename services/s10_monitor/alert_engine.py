"""Alert Engine for APEX Trading System Monitor."""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText

import aiohttp

from core.config import Settings
from core.logger import get_logger

logger = get_logger("s10_monitor.alert_engine")


class AlertEngine:
    """Configurable alert dispatcher via email (SMTP) and SMS (Twilio)."""

    def __init__(self, settings: Settings) -> None:
        """Initialize alert engine.

        Args:
            settings: System settings with alert configuration.
        """
        self._settings = settings
        self._queue: list[tuple[str, str]] = []  # [(level, message), ...]

    def alert(self, level: str, message: str) -> None:
        """Queue an alert for dispatch.

        Args:
            level: "WARNING" or "CRITICAL".
            message: Human-readable alert message.
        """
        self._queue.append((level, message))
        logger.info("Alert queued", level=level, message=message)

    async def send_email(self, subject: str, body: str) -> None:
        """Send an email alert via SMTP.

        Args:
            subject: Email subject line.
            body: Email body text.
        """
        if not self._settings.alert_email or not self._settings.alert_smtp_user:
            return
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[APEX Trading] {subject}"
            msg["From"] = self._settings.alert_smtp_user
            msg["To"] = self._settings.alert_email
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)
        except Exception as exc:
            logger.error("Email send failed", error=str(exc))

    def _send_smtp(self, msg: MIMEText) -> None:
        """Synchronous SMTP send (runs in executor)."""
        with smtplib.SMTP(self._settings.alert_smtp_host, self._settings.alert_smtp_port) as server:
            server.starttls()
            server.login(
                self._settings.alert_smtp_user,
                self._settings.alert_smtp_password.get_secret_value(),
            )
            server.send_message(msg)

    async def send_sms(self, message: str) -> None:
        """Send an SMS alert via Twilio.

        Args:
            message: SMS message text (max 160 chars recommended).
        """
        if not self._settings.twilio_sid or not self._settings.twilio_token:
            return
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._settings.twilio_sid.get_secret_value()}/Messages.json"
        data = {
            "To": self._settings.alert_phone_number,
            "From": self._settings.twilio_from_number,
            "Body": message,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=data,
                    auth=aiohttp.BasicAuth(
                        self._settings.twilio_sid.get_secret_value(),
                        self._settings.twilio_token.get_secret_value(),
                    ),
                ) as resp:
                    if resp.status not in (200, 201):
                        logger.warning("SMS send failed", status=resp.status)
        except Exception as exc:
            logger.error("SMS send error", error=str(exc))

    async def flush_alerts(self) -> None:
        """Process all queued alerts and dispatch notifications."""
        if not self._queue:
            return
        alerts = self._queue.copy()
        self._queue.clear()
        for level, message in alerts:
            if level == "CRITICAL":
                await self.send_email(f"CRITICAL: {message}", message)
                await self.send_sms(f"APEX CRITICAL: {message[:140]}")
            elif level == "WARNING":
                await self.send_email(f"WARNING: {message}", message)
