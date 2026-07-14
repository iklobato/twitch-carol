"""Impersonation: only allowlisted logins can start it, the session then acts
as the target channel, and stopping returns to the admin."""

import pytest

from core.config import get_settings
from tests.conftest import login_as
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def _set_admins(monkeypatch, logins: str) -> None:
    monkeypatch.setenv("ADMIN_LOGINS", logins)
    get_settings.cache_clear()


def test_impersonate_requires_session(api_client) -> None:
    assert api_client.post("/api/admin/impersonate/someone").status_code == 401
    assert api_client.post("/api/admin/impersonate/stop").status_code == 401


def test_non_admin_cannot_impersonate(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    caller = make_channel(db, login="not_boss")
    make_channel(db, login="victim")
    login_as(api_client, caller)

    assert api_client.post("/api/admin/impersonate/victim").status_code == 403


def test_admin_impersonates_and_acts_as_target(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    target = make_channel(db, login="victim")
    login_as(api_client, admin)

    assert api_client.post("/api/admin/impersonate/victim").status_code == 204

    me = api_client.get("/api/me").json()
    assert me["login"] == "victim"
    assert me["twitch_user_id"] == target.twitch_user_id
    assert me["impersonating"] == {"as_login": "victim", "admin_login": "boss"}


def test_stop_returns_to_admin(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    make_channel(db, login="victim")
    login_as(api_client, admin)
    api_client.post("/api/admin/impersonate/victim")

    assert api_client.post("/api/admin/impersonate/stop").status_code == 204

    me = api_client.get("/api/me").json()
    assert me["login"] == "boss"
    assert me["impersonating"] is None


def test_stop_without_impersonation_is_rejected(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    login_as(api_client, admin)

    assert api_client.post("/api/admin/impersonate/stop").status_code == 400


def test_cannot_impersonate_while_impersonating(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    make_channel(db, login="victim")
    make_channel(db, login="other")
    login_as(api_client, admin)
    api_client.post("/api/admin/impersonate/victim")

    assert api_client.post("/api/admin/impersonate/other").status_code == 403


def test_impersonate_unknown_login_is_404(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    login_as(api_client, admin)

    assert api_client.post("/api/admin/impersonate/ghost").status_code == 404


def test_cannot_impersonate_self(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    login_as(api_client, admin)

    assert api_client.post("/api/admin/impersonate/boss").status_code == 400


def test_me_exposes_admin_flag(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    plain = make_channel(db, login="viewer")

    login_as(api_client, admin)
    assert api_client.get("/api/me").json()["is_admin"] is True

    login_as(api_client, plain)
    assert api_client.get("/api/me").json()["is_admin"] is False


def test_channels_list_requires_admin(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    plain = make_channel(db, login="viewer")
    login_as(api_client, plain)

    assert api_client.get("/api/admin/channels").status_code == 403


def test_admin_lists_other_channels(api_client, db, monkeypatch) -> None:
    _set_admins(monkeypatch, "boss")
    admin = make_channel(db, login="boss")
    make_channel(db, login="alice")
    make_channel(db, login="bob")
    login_as(api_client, admin)

    logins = [c["login"] for c in api_client.get("/api/admin/channels").json()]
    assert logins == ["alice", "bob"]  # ordered by login, admin excluded
