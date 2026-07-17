"""The /howto page is served by the API (App Platform static sites can't do
extensionless URLs). No auth, returns HTML."""

import pytest

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_howto_served_without_extension_and_without_auth(api_client) -> None:
    resp = api_client.get("/howto")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Como funciona" in resp.text
    # screenshots must point under /previews, outside the /howto route prefix
    assert "/previews/stream-report.png" in resp.text


def test_howto_html_also_served(api_client) -> None:
    # App Platform routes the whole /howto prefix here, so /howto.html lands on
    # the API too and must not 404.
    resp = api_client.get("/howto.html")

    assert resp.status_code == 200
    assert "Como funciona" in resp.text
