import sys
import types

import core.logging_setup as ls


class _FakeSettings:
    def __init__(self, dsn: str = "", environment: str = "test") -> None:
        self.sentry_dsn = dsn
        self.sentry_environment = environment


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.setattr(ls, "get_settings", lambda: _FakeSettings(dsn=""))
    # No DSN must neither raise nor require sentry-sdk to be importable.
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)
    ls.init_sentry()


def test_init_sentry_inits_with_dsn(monkeypatch):
    captured: dict = {}
    fake_sdk = types.SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(
        ls,
        "get_settings",
        lambda: _FakeSettings(dsn="https://k@o.ingest.sentry.io/1", environment="prod"),
    )

    ls.init_sentry()

    assert captured["dsn"] == "https://k@o.ingest.sentry.io/1"
    assert captured["environment"] == "prod"
    assert captured["send_default_pii"] is False
