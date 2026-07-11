"""Pluggable, fan-out notification framework.

A :class:`Dispatcher` fans a :class:`NotifyEvent` out to any number of
:class:`Notifier` plugins (Telegram, Discord, Slack, generic webhook). Notifiers
guard their own network dependencies with lazy imports and never raise to the
caller, so a misconfigured channel can never break the launch engine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from occfix.config import NotifyConfig

logger = logging.getLogger(__name__)

#: Event types that must reach the user immediately and flush any digest buffer.
CRITICAL_EVENTS = frozenset({"launched", "error", "stopped"})

#: Credential values treated as "not configured".
_PLACEHOLDERS = frozenset({"", "xxxx"})


@dataclass
class NotifyEvent:
    """A single notification, routed unchanged to every channel."""

    type: str
    title: str
    message: str
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Return a JSON-serialisable representation of the event."""

        return {
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "data": self.data,
        }


class Notifier(ABC):
    """Base class for a single delivery channel.

    Implementations must catch their own errors and return ``False`` on failure;
    :meth:`send` must never raise to the caller.
    """

    name: str = "notifier"

    @abstractmethod
    def send(self, event: NotifyEvent) -> bool:
        """Deliver ``event``; return ``True`` on success, ``False`` otherwise."""


def _format_text(event: NotifyEvent) -> str:
    """Combine an event title and message into a single text body."""

    if event.title and event.message:
        return f"{event.title}\n\n{event.message}"
    return event.title or event.message


class TelegramNotifier(Notifier):
    """Send messages via the Telegram Bot API using ``telebot``."""

    name = "telegram"

    def __init__(self, bot_token: str, uid: str) -> None:
        self.bot_token = bot_token
        self.uid = uid

    def send(self, event: NotifyEvent) -> bool:
        try:
            import telebot

            bot = telebot.TeleBot(self.bot_token)
            bot.send_message(self.uid, _format_text(event))
            return True
        except Exception:
            logger.exception("telegram notification failed")
            return False


class WebhookNotifier(Notifier):
    """POST the full event payload to a generic JSON webhook."""

    name = "webhook"

    def __init__(self, url: str) -> None:
        self.url = url

    def send(self, event: NotifyEvent) -> bool:
        try:
            import requests

            resp = requests.post(self.url, json=event.as_dict(), timeout=10)
            resp.raise_for_status()
            return True
        except Exception:
            logger.exception("webhook notification failed")
            return False


class DiscordNotifier(Notifier):
    """POST a message to a Discord incoming webhook."""

    name = "discord"

    def __init__(self, url: str) -> None:
        self.url = url

    def send(self, event: NotifyEvent) -> bool:
        try:
            import requests

            resp = requests.post(self.url, json={"content": _format_text(event)}, timeout=10)
            resp.raise_for_status()
            return True
        except Exception:
            logger.exception("discord notification failed")
            return False


class SlackNotifier(Notifier):
    """POST a message to a Slack incoming webhook."""

    name = "slack"

    def __init__(self, url: str) -> None:
        self.url = url

    def send(self, event: NotifyEvent) -> bool:
        try:
            import requests

            resp = requests.post(self.url, json={"text": _format_text(event)}, timeout=10)
            resp.raise_for_status()
            return True
        except Exception:
            logger.exception("slack notification failed")
            return False


class Dispatcher:
    """Fan events out to every configured notifier.

    When ``digest`` is enabled, non-critical events are buffered and only sent
    when a critical event arrives (types in :data:`CRITICAL_EVENTS`) or when
    :meth:`flush` is called. Critical events are always delivered immediately.
    """

    def __init__(self, notifiers: list[Notifier], *, digest: bool = False) -> None:
        self.notifiers = list(notifiers)
        self.digest = digest
        self._buffer: list[NotifyEvent] = []

    def notify(self, event: NotifyEvent) -> None:
        """Route ``event`` to all channels, swallowing any failures."""

        if self.digest and event.type not in CRITICAL_EVENTS:
            self._buffer.append(event)
            return
        if event.type in CRITICAL_EVENTS:
            self.flush()
        self._dispatch(event)

    def flush(self) -> None:
        """Send and clear any buffered non-critical events."""

        if not self._buffer:
            return
        buffered = self._buffer
        self._buffer = []
        for event in buffered:
            self._dispatch(event)

    def _dispatch(self, event: NotifyEvent) -> None:
        for notifier in self.notifiers:
            try:
                if not notifier.send(event):
                    logger.warning("notifier %s failed to send event %s", notifier.name, event.type)
            except Exception:
                logger.exception("notifier %s raised on event %s", notifier.name, event.type)


def _configured(*values: str) -> bool:
    """True only when every credential is present and not a placeholder."""

    return all(value not in _PLACEHOLDERS for value in values)


def build_dispatcher(config: NotifyConfig) -> Dispatcher:
    """Construct a :class:`Dispatcher` from a :class:`NotifyConfig`.

    Channels with missing or placeholder credentials are skipped.
    """

    notifiers: list[Notifier] = []
    for channel in config.channels:
        name = channel.strip().lower()
        if name == "telegram":
            if _configured(config.telegram_bot_token, config.telegram_uid):
                notifiers.append(TelegramNotifier(config.telegram_bot_token, config.telegram_uid))
        elif name == "webhook":
            if _configured(config.webhook_url):
                notifiers.append(WebhookNotifier(config.webhook_url))
        elif name == "discord":
            if _configured(config.discord_webhook_url):
                notifiers.append(DiscordNotifier(config.discord_webhook_url))
        elif name == "slack":
            if _configured(config.slack_webhook_url):
                notifiers.append(SlackNotifier(config.slack_webhook_url))
        else:
            logger.warning("unknown notify channel: %s", channel)

    return Dispatcher(notifiers, digest=config.digest)
