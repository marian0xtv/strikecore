"""
WhatsApp integration for StrikeCore via Twilio.

Sends alerts on critical findings and ad-hoc messages through the Twilio
WhatsApp API.

Usage::

    from messaging.whatsapp_bot import WhatsAppNotifier

    notifier = WhatsAppNotifier()          # reads config from Settings
    await notifier.send_alert(finding)
    await notifier.send_message("Scan complete.")
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Dict, Optional

from log_system.logger import log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WHATSAPP_MAX_LENGTH = 1600  # WhatsApp message body limit


# ---------------------------------------------------------------------------
# Notifier class
# ---------------------------------------------------------------------------


class WhatsAppNotifier:
    """Sends alerts and messages via Twilio's WhatsApp API.

    The notifier reads ``twilio_sid``, ``twilio_token``, ``from_number``, and
    ``to_number`` from the StrikeCore
    :class:`~strikecore.config.settings.Settings` singleton.  If any required
    value is missing the notifier degrades gracefully -- all public methods
    become silent no-ops and log a warning once.
    """

    def __init__(
        self,
        twilio_sid: Optional[str] = None,
        twilio_token: Optional[str] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
    ) -> None:
        self._twilio_sid = twilio_sid
        self._twilio_token = twilio_token
        self._from_number = from_number
        self._to_number = to_number
        self._client: Any = None
        self._configured: Optional[bool] = None  # lazy tri-state
        self._warned = False

    # -- Lazy initialisation ------------------------------------------------

    def _resolve_config(self) -> bool:
        """Load Twilio credentials from Settings if not supplied at init."""
        if self._configured is not None:
            return self._configured

        if not all([self._twilio_sid, self._twilio_token,
                    self._from_number, self._to_number]):
            try:
                from config.settings import get_settings

                settings = get_settings()
                self._twilio_sid = self._twilio_sid or settings.get(
                    "whatsapp.twilio_sid"
                )
                self._twilio_token = self._twilio_token or settings.get(
                    "whatsapp.twilio_token"
                )
                self._from_number = self._from_number or settings.get(
                    "whatsapp.from_number"
                )
                self._to_number = self._to_number or settings.get(
                    "whatsapp.to_number"
                )
            except Exception:
                pass

        required = [
            self._twilio_sid,
            self._twilio_token,
            self._from_number,
            self._to_number,
        ]
        if not all(required):
            self._configured = False
            if not self._warned:
                log.warning(
                    "WhatsApp notifier is not configured "
                    "(missing Twilio credentials). Notifications disabled."
                )
                self._warned = True
            return False

        self._configured = True
        return True

    def _get_client(self) -> Any:
        """Return a ``twilio.rest.Client`` instance, creating it lazily."""
        if self._client is not None:
            return self._client

        try:
            from twilio.rest import Client

            self._client = Client(self._twilio_sid, self._twilio_token)
            return self._client
        except ImportError:
            log.error(
                "twilio is not installed. "
                "Install it with: pip install twilio"
            )
            self._configured = False
            return None

    # -- Internal: run blocking Twilio SDK in executor ----------------------

    async def _send_whatsapp(self, body: str) -> bool:
        """Send a WhatsApp message through the Twilio API.

        The Twilio Python SDK is synchronous, so we run the call in the
        default executor to avoid blocking the event loop.
        """
        client = self._get_client()
        if client is None:
            return False

        from_whatsapp = self._normalise_whatsapp_number(self._from_number)
        to_whatsapp = self._normalise_whatsapp_number(self._to_number)

        loop = asyncio.get_running_loop()
        try:
            create_fn = functools.partial(
                client.messages.create,
                body=body,
                from_=from_whatsapp,
                to=to_whatsapp,
            )
            message = await loop.run_in_executor(None, create_fn)
            log.info(
                "WhatsApp message sent: sid={sid}",
                sid=message.sid,
            )
            return True
        except Exception as exc:
            log.error("Failed to send WhatsApp message: {exc}", exc=exc)
            return False

    # -- Public API ---------------------------------------------------------

    async def send_alert(self, finding: Dict[str, Any]) -> bool:
        """Send an alert for a security finding.

        Only findings with severity ``critical`` trigger a WhatsApp message.
        Lower-severity findings are silently skipped.

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
        if severity != "critical":
            log.debug(
                "Skipping WhatsApp alert for {severity} finding",
                severity=severity,
            )
            return False

        title = finding.get("title", finding.get("name", "Untitled Finding"))
        description = finding.get("description", "")
        recommendation = finding.get("recommendation", "")

        parts = [
            f"[StrikeCore CRITICAL ALERT]",
            "",
            f"Finding: {title}",
        ]
        if description:
            parts.append(f"Description: {description}")
        if recommendation:
            parts.append(f"Recommendation: {recommendation}")

        body = "\n".join(parts)

        # Truncate if necessary
        if len(body) > _WHATSAPP_MAX_LENGTH:
            body = body[: _WHATSAPP_MAX_LENGTH - 3] + "..."

        return await self._send_whatsapp(body)

    async def send_message(self, text: str) -> bool:
        """Send a plain-text WhatsApp message.

        Parameters
        ----------
        text:
            The message body.  Messages exceeding the WhatsApp limit
            (1600 chars) are split automatically.

        Returns
        -------
        bool
            *True* if all chunks were sent successfully.
        """
        if not self._resolve_config():
            return False

        chunks = _split_message(text, _WHATSAPP_MAX_LENGTH)
        success = True
        for chunk in chunks:
            if not await self._send_whatsapp(chunk):
                success = False
        return success

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _normalise_whatsapp_number(number: str) -> str:
        """Ensure *number* carries the ``whatsapp:`` prefix."""
        if not number.startswith("whatsapp:"):
            return f"whatsapp:{number}"
        return number


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


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

        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
