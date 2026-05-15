"""
Telegram integration for StrikeCore.

Sends alerts on critical/high findings, session reports, and ad-hoc
messages via the Telegram Bot API using the ``python-telegram-bot``
library.

Usage::

    from messaging.telegram_bot import TelegramNotifier

    notifier = TelegramNotifier()          # reads config from Settings
    await notifier.send_alert(finding)
    await notifier.send_report("/path/to/report.html")
    await notifier.send_message("Scan complete.")
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from log_system.logger import log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI = {
    "critical": "\U0001f534",   # red circle
    "high": "\U0001f7e0",       # orange circle
    "medium": "\U0001f7e1",     # yellow circle
    "low": "\U0001f535",        # blue circle
    "info": "\u2139\ufe0f",     # info
}

_MAX_MESSAGE_LENGTH = 4096  # Telegram message limit


# ---------------------------------------------------------------------------
# Notifier class
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """Sends alerts and reports to a Telegram chat.

    The notifier reads ``bot_token`` and ``chat_id`` from the StrikeCore
    :class:`~strikecore.config.settings.Settings` singleton.  If either value
    is missing the notifier degrades gracefully -- all public methods become
    silent no-ops and log a warning once.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._bot: Any = None
        self._configured: Optional[bool] = None  # lazy tri-state
        self._warned = False

    # -- Lazy initialisation ------------------------------------------------

    def _resolve_config(self) -> bool:
        """Load token/chat_id from Settings if not supplied at init time."""
        if self._configured is not None:
            return self._configured

        if not self._bot_token or not self._chat_id:
            try:
                from config.settings import get_settings

                settings = get_settings()
                self._bot_token = self._bot_token or settings.get("telegram.bot_token")
                self._chat_id = self._chat_id or settings.get("telegram.chat_id")
            except Exception:
                pass

        if not self._bot_token or not self._chat_id:
            self._configured = False
            if not self._warned:
                log.warning(
                    "Telegram notifier is not configured "
                    "(missing bot_token or chat_id). Notifications disabled."
                )
                self._warned = True
            return False

        self._configured = True
        return True

    def _get_bot(self) -> Any:
        """Return a ``telegram.Bot`` instance, creating it lazily."""
        if self._bot is not None:
            return self._bot

        try:
            from telegram import Bot

            self._bot = Bot(token=self._bot_token)
            return self._bot
        except ImportError:
            log.error(
                "python-telegram-bot is not installed. "
                "Install it with: pip install python-telegram-bot"
            )
            self._configured = False
            return None

    # -- Public API ---------------------------------------------------------

    async def send_alert(self, finding: Dict[str, Any]) -> bool:
        """Send an alert for a security finding.

        Only findings with severity ``critical`` or ``high`` trigger a
        message.  Lower-severity findings are silently skipped.

        Parameters
        ----------
        finding:
            Dict with keys such as ``title``, ``severity``, ``description``,
            ``evidence``, ``recommendation``.

        Returns
        -------
        bool
            *True* if the message was sent successfully.
        """
        if not self._resolve_config():
            return False

        severity = str(finding.get("severity", "info")).lower()
        if severity not in ("critical", "high"):
            log.debug(
                "Skipping Telegram alert for {severity} finding",
                severity=severity,
            )
            return False

        emoji = _SEVERITY_EMOJI.get(severity, "")
        title = finding.get("title", finding.get("name", "Untitled Finding"))
        description = finding.get("description", "")
        evidence = finding.get("evidence", "")
        recommendation = finding.get("recommendation", "")

        parts = [
            f"{emoji} <b>StrikeCore Alert: {severity.upper()}</b>",
            "",
            f"<b>Finding:</b> {_escape_html(title)}",
        ]
        if description:
            parts.append(f"<b>Description:</b> {_escape_html(description)}")
        if evidence:
            truncated = evidence[:500] + ("..." if len(evidence) > 500 else "")
            parts.append(f"<b>Evidence:</b>\n<pre>{_escape_html(truncated)}</pre>")
        if recommendation:
            parts.append(f"<b>Recommendation:</b> {_escape_html(recommendation)}")

        message = "\n".join(parts)
        return await self._send_text(message, parse_mode="HTML")

    async def send_report(self, report_path: str | Path) -> bool:
        """Send a report file as a Telegram document.

        Parameters
        ----------
        report_path:
            Path to the report file on disk.

        Returns
        -------
        bool
            *True* if the document was sent successfully.
        """
        if not self._resolve_config():
            return False

        path = Path(report_path)
        if not path.exists():
            log.error("Report file not found: {path}", path=path)
            return False

        bot = self._get_bot()
        if bot is None:
            return False

        try:
            with open(path, "rb") as fh:
                await bot.send_document(
                    chat_id=self._chat_id,
                    document=fh,
                    filename=path.name,
                    caption=f"StrikeCore Report: {path.stem}",
                )
            log.info("Telegram report sent: {path}", path=path)
            return True
        except Exception as exc:
            log.error("Failed to send Telegram report: {exc}", exc=exc)
            return False

    async def send_message(self, text: str) -> bool:
        """Send a plain-text message.

        Parameters
        ----------
        text:
            The message body.  Messages exceeding the Telegram limit
            (4096 chars) are split automatically.

        Returns
        -------
        bool
            *True* if all message chunks were sent successfully.
        """
        if not self._resolve_config():
            return False

        # Split long messages
        chunks = _split_message(text, _MAX_MESSAGE_LENGTH)
        success = True
        for chunk in chunks:
            if not await self._send_text(chunk):
                success = False
        return success

    # -- Internal -----------------------------------------------------------

    async def _send_text(
        self,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> bool:
        bot = self._get_bot()
        if bot is None:
            return False

        try:
            await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except Exception as exc:
            log.error("Failed to send Telegram message: {exc}", exc=exc)
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram's HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _split_message(text: str, max_len: int) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters.

    Tries to split on newlines for readability; falls back to hard splits.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try to break at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
