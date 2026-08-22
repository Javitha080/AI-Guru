"""
AI Guru Telegram Notification Service.
======================================

Delivers real-time study session updates, outbound tunnel links,
and high-priority distraction/stress alerts directly to parents via Telegram Bot API.
Operates with zero heavy external dependencies using asynchronous HTTP requests.
"""

from __future__ import annotations

import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dispatches study session alerts and encrypted tunnel links to parents via Telegram."""

    TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

    @classmethod
    async def send_message(
        cls,
        bot_token: str,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
    ) -> bool:
        """Send a message to a Telegram chat using standard Bot API."""
        if not bot_token or not chat_id:
            logger.debug("Telegram notification skipped: bot_token or chat_id not configured.")
            return False

        url = cls.TELEGRAM_API_BASE.format(token=bot_token)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("Telegram notification successfully delivered to %s", chat_id)
                        return True
                    body = await resp.text()
                    logger.warning("Telegram API error (status %d): %s", resp.status, body)
                    return False
        except Exception as e:
            logger.warning("Failed to dispatch Telegram notification: %s", e)
            return False

    @classmethod
    async def send_session_start(
        cls,
        bot_token: str,
        chat_id: str,
        student_name: str,
        subject: str,
        target_minutes: int,
        tunnel_url: Optional[str] = None,
    ) -> bool:
        """Send notification when student begins a study session."""
        link_section = ""
        if tunnel_url:
            link_section = (
                f"\n\n🔗 <b>Parent Live Portal:</b>\n"
                f'<a href="{tunnel_url}/parent">{tunnel_url}/parent</a>'
            )

        text = (
            f"🎓 <b>AI Guru — Study Session Started</b>\n\n"
            f"👤 <b>Student:</b> {student_name}\n"
            f"📚 <b>Subject:</b> {subject}\n"
            f"⏱️ <b>Target Duration:</b> {target_minutes} minutes\n"
            f"🛡️ <b>Local AI Monitoring:</b> Active (Zero-Cloud Egress)"
            f"{link_section}\n\n"
            f"<i>You will receive updates if significant distractions or high stress are detected.</i>"
        )
        return await cls.send_message(bot_token, chat_id, text)

    @classmethod
    async def send_distraction_alert(
        cls,
        bot_token: str,
        chat_id: str,
        student_name: str,
        event_type: str,
        subject: str = "General",
        details: str = "",
        tunnel_url: Optional[str] = None,
    ) -> bool:
        """Send urgent distraction or absence notification."""
        event_titles = {
            "PHONE_DETECTED": "📱 Mobile Phone Detected",
            "STUDENT_NOT_DETECTED": "🚶 Student Away / Not Visible",
            "IDENTITY_MISMATCH": "⚠️ Unverified Person Detected",
            "HIGH_DISTRACTION": "👀 Prolonged Looking Away",
            "HIGH_STRESS": "🧘 High Restlessness / Stress Detected",
        }
        title = event_titles.get(event_type, f"⚠️ Study Alert: {event_type}")

        link_section = ""
        if tunnel_url:
            link_section = f'\n\n🔗 <a href="{tunnel_url}/parent">Open Parent Portal</a>'

        text = (
            f"🚨 <b>AI Guru Alert — {title}</b>\n\n"
            f"👤 <b>Student:</b> {student_name}\n"
            f"📚 <b>Subject:</b> {subject}\n"
            f"ℹ️ <b>Details:</b> {details or 'AI study monitor flagged this activity.'}"
            f"{link_section}\n\n"
            f"<i>AI Guru automatically issued a gentle reminder to the student.</i>"
        )
        return await cls.send_message(bot_token, chat_id, text)

    @classmethod
    async def send_session_summary(
        cls,
        bot_token: str,
        chat_id: str,
        student_name: str,
        subject: str,
        duration_minutes: int,
        focus_score: float,
        xp_earned: int,
        badges_unlocked: list[str] | None = None,
        ai_summary: str = "",
    ) -> bool:
        """Send final study session summary report card."""
        badges_text = ""
        if badges_unlocked:
            badges_text = f"\n🏆 <b>Badges Unlocked:</b> {', '.join(badges_unlocked)}"

        summary_text = ""
        if ai_summary:
            summary_text = f"\n\n📝 <b>AI Summary:</b>\n<i>{ai_summary}</i>"

        text = (
            f"✅ <b>AI Guru — Study Session Completed!</b>\n\n"
            f"👤 <b>Student:</b> {student_name}\n"
            f"📚 <b>Subject:</b> {subject}\n"
            f"⏱️ <b>Actual Time:</b> {duration_minutes} minutes\n"
            f"🎯 <b>Focus Score:</b> {focus_score:.0f}%\n"
            f"⭐ <b>XP Earned:</b> +{xp_earned} XP"
            f"{badges_text}"
            f"{summary_text}"
        )
        return await cls.send_message(bot_token, chat_id, text)
