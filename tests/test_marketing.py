"""The /howto page is served by the API (App Platform static sites can't do
extensionless URLs), in the reader's language (pt default, en when asked)."""

import pytest

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_howto_defaults_to_portuguese(api_client) -> None:
    resp = api_client.get("/howto", headers={"Accept-Language": ""})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert 'lang="pt-BR"' in resp.text
    assert "Como funciona" in resp.text


def test_howto_serves_english_for_english_browser(api_client) -> None:
    resp = api_client.get("/howto", headers={"Accept-Language": "en-US,en;q=0.9"})

    assert resp.status_code == 200
    assert 'lang="en"' in resp.text
    assert "How it works" in resp.text


def test_portuguese_browser_gets_portuguese(api_client) -> None:
    resp = api_client.get("/howto", headers={"Accept-Language": "pt-BR,pt;q=0.9"})

    assert 'lang="pt-BR"' in resp.text


def test_lang_query_overrides_and_sets_cookie(api_client) -> None:
    # English browser, but the reader picked PT via the toggle.
    resp = api_client.get(
        "/howto?lang=pt", headers={"Accept-Language": "en-US,en;q=0.9"}
    )

    assert 'lang="pt-BR"' in resp.text
    assert "howto_lang=pt" in resp.headers.get("set-cookie", "")


def test_howto_html_path_also_served(api_client) -> None:
    # App Platform routes the whole /howto prefix to the API.
    resp = api_client.get("/howto.html", headers={"Accept-Language": "en"})

    assert resp.status_code == 200
    assert "How it works" in resp.text
