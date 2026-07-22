"""Twitch Create Clip (POST /helix/clips)."""

import httpx
import pytest

from core.twitch import CreatedClip, TwitchAuthError, create_clip


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_create_clip_posts_broadcaster_and_parses() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            202,
            json={
                "data": [
                    {"id": "AbCd12", "edit_url": "https://clips.twitch.tv/AbCd12/edit"}
                ]
            },
        )

    out = create_clip(123, "tok-abc", client=_client(handler))

    assert isinstance(out, CreatedClip)
    assert out.id == "AbCd12"
    assert out.edit_url.endswith("/edit")
    assert seen["method"] == "POST"
    assert "/clips" in str(seen["url"])
    assert "broadcaster_id=123" in str(seen["url"])
    assert seen["auth"] == "Bearer tok-abc"


def test_create_clip_raises_on_error() -> None:
    with pytest.raises(TwitchAuthError, match="401"):
        create_clip(1, "tok", client=_client(lambda r: httpx.Response(401, json={})))
