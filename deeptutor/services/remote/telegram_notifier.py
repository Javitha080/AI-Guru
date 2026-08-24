"""
AI Guru Telegram Notification Service.
======================================

Delivers real-time study session updates, outbound tunnel links,
and high-priority distraction/stress alerts directly to parents via Telegram Bot API.
Operates with zero heavy external dependencies using asynchronous HTTP requests.

Message composition lives in pure ``compose_*`` builders so the durable
notification outbox (services/monitoring/notification_queue.py) reuses the
exact same formatting — including the one-tap Parent Portal link — instead
of maintaining a second, drifting copy of every template.
"""

from __future__ import annotations

import html
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dispatches study session alerts and encrypted tunnel links to parents via Telegram."""

    TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

    # ------------------------------------------------------------ plumbing

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

    @staticmethod
    def _esc(value: object) -> str:
        return html.escape(str(value if value is not None else ""), quote=False)

    @classmethod
    def _portal_section(cls, tunnel_url: Optional[str]) -> str:
        """One-tap Parent Portal footer, only when a public tunnel is live."""
        if not tunnel_url:
            return ""
        safe = cls._esc(tunnel_url)
        return f'\n\n🔗 <a href="{safe}/parent">Open Parent Portal</a>'

    @classmethod
    def _alert_title(cls, event_type: str) -> str:
        event_titles = {
            "PHONE_DETECTED": "📱 Mobile Phone Detected",
            "STUDENT_NOT_DETECTED": "🚶 Student Away / Not Visible",
            "STUDENT_AWAY": "🚶 Student Away / Not Visible",
            "LOOKING_AWAY": "👀 Prolonged Looking Away",
            "HIGH_DISTRACTION": "👀 Prolonged Looking Away",
            "IDENTITY_MISMATCH": "⚠️ Unverified Person Detected",
            "DROWSINESS": "😴 Drowsiness Detected",
            "HIGH_STRESS": "🧘 High Restlessness / Stress Detected",
        }
        return event_titles.get(event_type, f"Study Alert: {event_type}")

    # ------------------------------------------------------------ composers

    @classmethod
    def compose_session_start(
        cls,
        student_name: str,
        subject: str,
        target_minutes: int,
        tunnel_url: Optional[str] = None,
    ) -> str:
        """Text for the 'student began studying' notification."""
        text = (
            f"▶️ <b>AI Guru — Study Session Started</b>\n\n"
            f"👤 <b>Student:</b> {cls._esc(student_name)}\n"
            f"📚 <b>Subject:</b> {cls._esc(subject)}\n"
            f"⏱️ <b>Target Duration:</b> {float(target_minutes):.0f} minutes\n"
            f"🛡️ <b>Local AI Monitoring:</b> Active (Zero-Cloud Egress)"
            f"{cls._portal_section(tunnel_url)}\n\n"
            f"<i>You will receive updates if significant distractions are detected.</i>"
        )
        return text

    @classmethod
    def compose_distraction_alert(
        cls,
        event_type: str,
        student_name: str = "Student",
        subject: str = "General",
        details: str = "",
        tunnel_url: Optional[str] = None,
        confidence: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        severity: str = "",
    ) -> str:
        """Urgent distraction / absence notification text."""
        emoji = {"alert": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "🚨")
        metrics_bits = []
        if confidence is not None:
            metrics_bits.append(f"Confidence {int(float(confidence) * 100)}%")
        if duration_seconds is not None:
            metrics_bits.append(f"{float(duration_seconds):.0f}s")

        text = (
            f"{emoji} <b>AI Guru — {cls._alert_title(event_type)}</b>\n\n"
            f"👤 <b>Student:</b> {cls._esc(student_name)}\n"
            f"📚 <b>Subject:</b> {cls._esc(subject)}\n"
            f"ℹ️ <b>Details:</b> {cls._esc(details) or 'AI study monitor flagged this activity.'}"
        )
        if metrics_bits:
            text += f"\n📊 <i>{' · '.join(metrics_bits)}"
            if session_id:
                text += f" · Session {cls._esc(str(session_id)[:18])}"
            text += "</i>"
        text += (
            f"{cls._portal_section(tunnel_url)}\n\n"
            f"<i>AI Guru automatically issued a gentle reminder to the student.</i>"
        )
        return text

    @classmethod
    def compose_session_summary(
        cls,
        student_name: str,
        subject: str,
        duration_minutes: float,
        focus_score: float,
        xp_earned: int,
        badges_unlocked: Optional[list[str]] = None,
        ai_summary: str = "",
        engagement_score: Optional[float] = None,
        warning_count: Optional[int] = None,
        tunnel_url: Optional[str] = None,
    ) -> str:
        """Final study-session report-card text."""
        badges_text = ""
        if badges_unlocked:
            badges_text = f"\n🏆 <b>Badges Unlocked:</b> {', '.join(cls._esc(b) for b in badges_unlocked)}"

        extra_metrics = ""
        if engagement_score is not None:
            extra_metrics += f"\n⚡ <b>Engagement:</b> {float(engagement_score):.0f}%"
        if warning_count is not None:
            extra_metrics += f"\n⚠️ <b>Warnings:</b> {int(warning_count)}"

        summary_text = ""
        if ai_summary:
            summary_text = f"\n\n📝 <b>AI Summary:</b>\n<i>{cls._esc(ai_summary[:500])}</i>"

        text = (
            f"✅ <b>AI Guru — Study Session Completed!</b>\n\n"
            f"👤 <b>Student:</b> {cls._esc(student_name)}\n"
            f"📚 <b>Subject:</b> {cls._esc(subject)}\n"
            f"⏱️ <b>Actual Time:</b> {float(duration_minutes):.0f} minutes\n"
            f"🎯 <b>Focus Score:</b> {float(focus_score):.0f}%"
            f"{extra_metrics}\n"
            f"⭐ <b>XP Earned:</b> +{int(xp_earned)} XP"
            f"{badges_text}"
            f"{summary_text}"
            f"{cls._portal_section(tunnel_url)}"
        )
        return text

    # -------------------------------------------------------- send wrappers

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
        return await cls.send_message(
            bot_token, chat_id,
            cls.compose_session_start(student_name, subject, target_minutes, tunnel_url),
        )

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
        return await cls.send_message(
            bot_token, chat_id,
            cls.compose_distraction_alert(
                event_type, student_name=student_name, subject=subject,
                details=details, tunnel_url=tunnel_url,
            ),
        )

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
        return await cls.send_message(
            bot_token, chat_id,
            cls.compose_session_summary(
                student_name, subject, duration_minutes, focus_score,
                xp_earned, badges_unlocked, ai_summary,
            ),
        )
