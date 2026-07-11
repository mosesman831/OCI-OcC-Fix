"""Unit tests for the pluggable notification framework."""

from __future__ import annotations

import requests

from occfix.config import NotifyConfig
from occfix.notify import (
    DiscordNotifier,
    Dispatcher,
    Notifier,
    NotifyEvent,
    SlackNotifier,
    TelegramNotifier,
    WebhookNotifier,
    build_dispatcher,
)


class FakeNotifier(Notifier):
    """Records every event it receives; optionally simulates failure/raising."""

    def __init__(self, name: str = "fake", *, ok: bool = True, raises: bool = False) -> None:
        self.name = name
        self._ok = ok
        self._raises = raises
        self.events: list[NotifyEvent] = []

    def send(self, event: NotifyEvent) -> bool:
        if self._raises:
            raise RuntimeError("boom")
        self.events.append(event)
        return self._ok


class FakeResponse:
    """Minimal stand-in for a ``requests`` response object."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def _event(type_: str = "started") -> NotifyEvent:
    return NotifyEvent(type=type_, title="T", message="M")


def test_notify_event_defaults_and_as_dict():
    event = NotifyEvent(type="started", title="Hi", message="there")
    assert event.data == {}
    assert event.as_dict() == {
        "type": "started",
        "title": "Hi",
        "message": "there",
        "data": {},
    }


def test_dispatcher_fans_out_to_multiple_notifiers():
    a, b = FakeNotifier("a"), FakeNotifier("b")
    dispatcher = Dispatcher([a, b])

    event = _event("started")
    dispatcher.notify(event)

    assert a.events == [event]
    assert b.events == [event]


def test_notifier_that_raises_does_not_break_dispatcher():
    good_before = FakeNotifier("before")
    bad = FakeNotifier("bad", raises=True)
    good_after = FakeNotifier("after")
    dispatcher = Dispatcher([good_before, bad, good_after])

    event = _event("started")
    dispatcher.notify(event)  # must not raise

    assert good_before.events == [event]
    assert good_after.events == [event]


def test_notifier_returning_false_does_not_break_dispatcher():
    failing = FakeNotifier("failing", ok=False)
    good = FakeNotifier("good")
    dispatcher = Dispatcher([failing, good])

    dispatcher.notify(_event("started"))

    assert len(good.events) == 1


def test_digest_buffers_non_critical_until_critical_arrives():
    fake = FakeNotifier()
    dispatcher = Dispatcher([fake], digest=True)

    dispatcher.notify(_event("started"))
    dispatcher.notify(_event("throttled"))
    assert fake.events == []  # buffered, nothing sent yet

    critical = _event("launched")
    dispatcher.notify(critical)

    types = [e.type for e in fake.events]
    assert types == ["started", "throttled", "launched"]


def test_digest_flush_sends_buffered_events():
    fake = FakeNotifier()
    dispatcher = Dispatcher([fake], digest=True)

    dispatcher.notify(_event("started"))
    dispatcher.notify(_event("throttled"))
    assert fake.events == []

    dispatcher.flush()
    assert [e.type for e in fake.events] == ["started", "throttled"]

    dispatcher.flush()  # idempotent, nothing new
    assert len(fake.events) == 2


def test_digest_disabled_sends_immediately():
    fake = FakeNotifier()
    dispatcher = Dispatcher([fake], digest=False)

    dispatcher.notify(_event("started"))
    assert [e.type for e in fake.events] == ["started"]


def test_critical_event_flushes_before_itself():
    fake = FakeNotifier()
    dispatcher = Dispatcher([fake], digest=True)

    dispatcher.notify(_event("started"))
    dispatcher.notify(_event("error"))

    assert [e.type for e in fake.events] == ["started", "error"]


def test_webhook_notifier_posts_full_event(monkeypatch):
    calls = {}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)

    event = NotifyEvent(type="started", title="T", message="M", data={"k": "v"})
    notifier = WebhookNotifier("https://hook.example/generic")

    assert notifier.send(event) is True
    assert calls["url"] == "https://hook.example/generic"
    assert calls["json"] == event.as_dict()


def test_discord_notifier_posts_content(monkeypatch):
    calls = {}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)

    notifier = DiscordNotifier("https://discord.example/webhook")
    assert notifier.send(NotifyEvent("started", "Title", "Body")) is True
    assert calls["url"] == "https://discord.example/webhook"
    assert calls["json"] == {"content": "Title\n\nBody"}


def test_slack_notifier_posts_text(monkeypatch):
    calls = {}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)

    notifier = SlackNotifier("https://slack.example/webhook")
    assert notifier.send(NotifyEvent("started", "Title", "Body")) is True
    assert calls["url"] == "https://slack.example/webhook"
    assert calls["json"] == {"text": "Title\n\nBody"}


def test_requests_notifier_returns_false_on_network_exception(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "post", boom)

    for notifier in (
        WebhookNotifier("https://x.example"),
        DiscordNotifier("https://x.example"),
        SlackNotifier("https://x.example"),
    ):
        assert notifier.send(_event("started")) is False  # never raises


def test_requests_notifier_returns_false_on_bad_status(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(500))

    assert WebhookNotifier("https://x.example").send(_event("started")) is False


def test_telegram_notifier_sends_via_telebot(monkeypatch):
    sent = {}

    class FakeBot:
        def __init__(self, token):
            sent["token"] = token

        def send_message(self, uid, text):
            sent["uid"] = uid
            sent["text"] = text

    fake_module = type("telebot", (), {"TeleBot": FakeBot})
    monkeypatch.setitem(__import__("sys").modules, "telebot", fake_module)

    notifier = TelegramNotifier("real-token", "12345")
    assert notifier.send(NotifyEvent("started", "Title", "Body")) is True
    assert sent == {"token": "real-token", "uid": "12345", "text": "Title\n\nBody"}


def test_telegram_notifier_returns_false_on_failure(monkeypatch):
    class FakeBot:
        def __init__(self, token):
            pass

        def send_message(self, uid, text):
            raise RuntimeError("telegram down")

    fake_module = type("telebot", (), {"TeleBot": FakeBot})
    monkeypatch.setitem(__import__("sys").modules, "telebot", fake_module)

    assert TelegramNotifier("t", "u").send(_event("started")) is False


def test_build_dispatcher_skips_telegram_with_placeholder_credentials():
    config = NotifyConfig(
        channels=["telegram"],
        telegram_bot_token="xxxx",
        telegram_uid="xxxx",
    )
    dispatcher = build_dispatcher(config)
    assert dispatcher.notifiers == []


def test_build_dispatcher_builds_configured_channels():
    config = NotifyConfig(
        channels=["telegram", "webhook", "discord", "slack"],
        digest=True,
        telegram_bot_token="token",
        telegram_uid="uid",
        webhook_url="https://hook",
        discord_webhook_url="https://discord",
        slack_webhook_url="https://slack",
    )
    dispatcher = build_dispatcher(config)

    assert dispatcher.digest is True
    names = [n.name for n in dispatcher.notifiers]
    assert names == ["telegram", "webhook", "discord", "slack"]


def test_build_dispatcher_skips_channels_missing_urls():
    config = NotifyConfig(channels=["webhook", "discord", "slack"])
    dispatcher = build_dispatcher(config)
    assert dispatcher.notifiers == []


def test_build_dispatcher_ignores_unknown_channel():
    config = NotifyConfig(channels=["carrier-pigeon"])
    dispatcher = build_dispatcher(config)
    assert dispatcher.notifiers == []
