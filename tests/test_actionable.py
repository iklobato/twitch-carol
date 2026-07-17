"""Actionable insights: retention, viewer dips, clip suggestions from peaks,
and unanswered chat questions."""

import pytest

from apps.api.actionable import _offset_label
from core.models import SegmentKind
from tests.conftest import login_as
from tests.factories import (
    add_chat,
    add_event,
    add_peak,
    add_segment,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_offset_label() -> None:
    assert _offset_label(90) == "1m30s"
    assert _offset_label(3725) == "1h02m05s"
    assert _offset_label(5) == "0m05s"


def test_retention_and_dips(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=6)
    # viewers: climb to 100, then crash to 40, recover a bit, end at 50
    add_viewer_samples(db, stream, [50, 80, 100, 40, 45, 50])
    db.flush()

    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/actionable").json()

    retention = body["retention"]
    assert retention["peak_viewers"] == 100
    assert retention["final_viewers"] == 50
    assert retention["retained_pct"] == 50.0
    assert retention["biggest_drop_at"] is not None

    dips = body["dips"]
    assert len(dips) >= 1
    biggest = dips[0]
    assert biggest["viewers_before"] == 100
    assert biggest["viewers_after"] == 40
    assert biggest["pct_drop"] == 60.0


def test_dip_carries_speech_context(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=4)
    # biggest drop is at minute 1 (100 -> 40), where the speech sits
    add_viewer_samples(db, stream, [80, 100, 40, 40])
    add_segment(db, stream, 60, "vou ler os termos de uso agora", duration_seconds=59)
    db.flush()

    login_as(api_client, channel)
    dips = api_client.get(f"/api/streams/{stream.id}/actionable").json()["dips"]
    assert dips[0]["speech_context"] == "vou ler os termos de uso agora"


def test_dip_context_cause_recovery_offset_and_chat(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=5)
    # biggest drop is at minute 1 (100 -> 40); recovers to 60 at minute 4
    add_viewer_samples(db, stream, [60, 100, 40, 40, 60])
    add_event(
        db, stream, event_type="channel.ad_break.begin", offset_seconds=30, amount=90
    )
    add_chat(
        db, stream, count=2, offset_seconds=60, text="cadê o jogo", spread_seconds=5
    )
    db.flush()

    login_as(api_client, channel)
    dip = api_client.get(f"/api/streams/{stream.id}/actionable").json()["dips"][0]

    assert dip["cause"] == "anúncio de 90s"
    assert dip["viewers_delta"] == -60
    assert dip["offset_label"] == "1m00s"
    assert dip["recovered_to"] == 60
    assert dip["recovered_in_minutes"] == 3.0
    assert any("cadê o jogo" in line for line in dip["chat_context"])


def test_dip_scene_when_music_plays_instead_of_speech(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=4)
    add_viewer_samples(db, stream, [60, 100, 40, 40])
    add_segment(db, stream, 60, text=None, kind=SegmentKind.MUSIC, duration_seconds=59)
    db.flush()

    login_as(api_client, channel)
    dip = api_client.get(f"/api/streams/{stream.id}/actionable").json()["dips"][0]
    assert dip["speech_context"] is None
    assert dip["scene"] == "tocando música"


def test_dip_category_change_is_a_cause(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=4)
    add_viewer_samples(db, stream, [60, 100, 40, 40])
    add_event(
        db,
        stream,
        event_type="channel.update",
        offset_seconds=45,
        payload={"category_name": "Just Chatting"},
    )
    db.flush()

    login_as(api_client, channel)
    dip = api_client.get(f"/api/streams/{stream.id}/actionable").json()["dips"][0]
    assert dip["cause"] == "troca para Just Chatting"


def test_clip_suggestions_from_peaks(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    add_peak(db, stream, offset_seconds=125, score=4.5)
    add_peak(db, stream, offset_seconds=600, score=2.1)
    db.flush()

    login_as(api_client, channel)
    clips = api_client.get(f"/api/streams/{stream.id}/actionable").json()["clips"]
    assert [c["score"] for c in clips] == [4.5, 2.1]  # ranked
    assert clips[0]["offset_seconds"] == 125
    assert clips[0]["offset_label"] == "2m05s"


def test_unanswered_questions(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    # question at 30s while streamer is speaking -> answered
    add_chat(db, stream, 1, author="a", text="qual editor você usa?", offset_seconds=30)
    add_segment(db, stream, 20, "eu uso o neovim", duration_seconds=40)
    # question at 300s in silence -> unanswered
    add_chat(db, stream, 1, author="b", text="e o teclado, qual é?", offset_seconds=300)
    # a non-question message must be ignored
    add_chat(db, stream, 1, author="c", text="massa demais", offset_seconds=305)
    db.flush()

    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/actionable").json()
    assert body["unanswered_questions_count"] == 1
    assert body["unanswered_questions"][0]["text"] == "e o teclado, qual é?"


def test_actionable_empty_stream(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/actionable").json()
    assert body["retention"] is None
    assert body["dips"] == []
    assert body["clips"] == []
    assert body["unanswered_questions_count"] == 0


def test_actionable_ownership(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    foreign = make_stream(db, other)
    login_as(api_client, mine)
    assert api_client.get(f"/api/streams/{foreign.id}/actionable").status_code == 404
