"""No channel may read or write another channel's data.

The per-endpoint ownership tests live next to each feature. This file is the
net under all of them: it walks the routes the app actually registers, so a new
endpoint that takes a `{stream_id}` is covered the day it is written, instead of
the day someone remembers to add a test for it.

Every one of these must answer 404, not 403: telling a stranger that a stream id
exists but is not theirs is already leaking which ids are real.
"""

import re

import pytest

from core.models import TwitchClip
from tests.conftest import login_as
from tests.factories import make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

OTHER_ID_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")


def stream_id_routes() -> list[tuple[str, str]]:
    """Read from the OpenAPI schema, not `app.routes`: FastAPI wraps included
    routers, so walking `app.routes` finds the four doc endpoints and nothing
    else. An empty list here would make this whole file pass without testing a
    single route, which is why the count is asserted below."""
    from apps.api.main import app

    found = [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{stream_id}" in path
        for method in operations
        if method.upper() in METHODS
    ]
    return sorted(found)


@pytest.mark.parametrize("method,path", stream_id_routes())
def test_no_route_serves_another_channels_stream(method, path, api_client, db) -> None:
    """A nested id (peak, insight) is filled with a number that does not exist:
    ownership of the stream has to be refused before anything else is looked at,
    so the answer must be 404 whatever the rest of the path says."""
    mine = make_channel(db)
    foreign = make_stream(db, make_channel(db))
    login_as(api_client, mine)

    url = OTHER_ID_PLACEHOLDER.sub(
        "999999", path.replace("{stream_id}", str(foreign.id))
    )
    response = api_client.request(method, url, json={})

    assert (
        response.status_code == 404
    ), f"{method} {path} devolveu {response.status_code}"


def test_the_sweep_actually_found_routes() -> None:
    """The sweep above is parametrized from a function. If it ever returns
    nothing, every case silently disappears and the file reports success while
    testing nothing at all, which is worse than having no test."""
    assert len(stream_id_routes()) >= 8


def test_a_clip_cannot_be_curated_by_another_channel(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    stream = make_stream(db, other)
    clip = TwitchClip(
        stream_id=stream.id,
        channel_id=other.id,
        clip_id="alheio-1",
        edit_url="https://clips.twitch.tv/edit/alheio-1",
    )
    db.add(clip)
    db.flush()
    login_as(api_client, mine)

    response = api_client.patch(f"/api/clips/{clip.id}", json={"title": "meu agora"})

    assert response.status_code == 404
    db.refresh(clip)
    assert clip.title is None
