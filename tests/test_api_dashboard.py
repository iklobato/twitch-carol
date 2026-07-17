"""DB-backed tests for every dashboard route: field correctness, ownership
isolation, parameter validation and failure paths."""

import pytest

from core.models import InsightType, JobStatus, SegmentKind, StreamStatus
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE
from tests.conftest import login_as
from tests.factories import (
    add_chat,
    add_event,
    add_insight,
    add_job,
    add_peak,
    add_segment,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_all_dashboard_routes_require_session(api_client) -> None:
    for path in (
        "/api/streams",
        "/api/streams/1",
        "/api/streams/1/timeline",
        "/api/streams/1/peaks/1",
        "/api/search?q=teste",
        "/api/queue",
    ):
        assert api_client.get(path).status_code == 401, path
    assert (
        api_client.post(
            "/api/insights/1/feedback", json={"feedback": "useful"}
        ).status_code
        == 401
    )


def test_streams_list_fields_and_isolation(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    stream = make_stream(db, mine, title="Minha live")
    add_chat(db, stream, 10, author="a1")
    add_chat(db, stream, 5, author="a2", offset_seconds=120)
    add_event(db, stream, "channel.follow")
    add_event(db, stream, "channel.raid", amount=50)
    add_viewer_samples(db, stream, [10, 80, 30])
    foreign = make_stream(db, other, title="Live alheia")
    add_chat(db, foreign, 3)

    login_as(api_client, mine)
    body = api_client.get("/api/streams").json()

    assert len(body) == 1
    item = body[0]
    assert item["title"] == "Minha live"
    assert item["messages"] == 15
    assert item["chatters"] == 2
    assert item["events"] == 2
    assert item["followers"] == 1
    assert item["peak_viewers"] == 80
    assert item["day"] == stream.started_at.date().isoformat()


def test_day_chatters_are_unique_across_lives(api_client, db) -> None:
    mine = make_channel(db)
    first = make_stream(db, mine, started_minutes_ago=90)
    second = make_stream(db, mine, started_minutes_ago=30)
    add_chat(db, first, 4, author="alice")
    add_chat(db, first, 4, author="bob")
    add_chat(db, second, 4, author="bob")  # same person, second live
    add_chat(db, second, 4, author="carol")
    other = make_channel(db)
    add_chat(db, make_stream(db, other), 3, author="alice")  # different channel

    login_as(api_client, mine)
    by_day = api_client.get("/api/streams/day-chatters").json()

    day = first.started_at.date().isoformat()
    # 4 per-live chatters (alice, bob, bob, carol) dedupe to 3 unique for the day
    assert by_day == {day: 3}


def test_stream_report_numbers_and_comparison(api_client, db) -> None:
    channel = make_channel(db)
    old = make_stream(db, channel, started_minutes_ago=2000, duration_minutes=30)
    add_chat(db, old, 10)
    add_viewer_samples(db, old, [10, 10])
    current = make_stream(db, channel, started_minutes_ago=60, duration_minutes=30)
    add_chat(db, current, 20)
    add_viewer_samples(db, current, [20, 20])

    login_as(api_client, channel)
    report = api_client.get(f"/api/streams/{current.id}").json()

    messages = report["numbers"]["messages"]
    assert messages["value"] == 20.0
    assert messages["previous_avg"] == 10.0
    assert messages["delta_pct"] == 100.0
    assert report["status"] == "ready"


def test_stream_report_404_for_foreign_stream(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    foreign = make_stream(db, other)
    login_as(api_client, mine)
    assert api_client.get(f"/api/streams/{foreign.id}").status_code == 404
    assert api_client.get(f"/api/streams/{foreign.id}/timeline").status_code == 404
    assert api_client.get("/api/streams/999999").status_code == 404


def test_report_resolves_cited_evidence_and_topic_engagement(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    messages = add_chat(db, stream, 30, offset_seconds=0, spread_seconds=300)
    segment_a = add_segment(db, stream, 10, "falando sobre python")
    segment_b = add_segment(db, stream, 600, "falando sobre deploy")
    add_insight(
        db,
        stream,
        InsightType.SUMMARY,
        "Resumo.",
        {"message_ids": [messages[0].id], "segment_ids": [segment_a.id]},
    )
    add_insight(
        db,
        stream,
        InsightType.TOPIC,
        "Python\nintro",
        {"segment_ids": [segment_a.id], "rank": 1},
    )
    add_insight(
        db,
        stream,
        InsightType.TOPIC,
        "Deploy\nfim",
        {"segment_ids": [segment_b.id], "rank": 2},
    )

    login_as(api_client, channel)
    report = api_client.get(f"/api/streams/{stream.id}").json()

    summary = next(i for i in report["insights"] if i["type"] == "summary")
    assert summary["cited_messages"][0]["text"] == "mensagem de teste"
    assert summary["cited_segments"][0]["text"] == "falando sobre python"
    topics = [i for i in report["insights"] if i["type"] == "topic"]
    assert all(t["engagement_pct"] is not None for t in topics)
    assert max(t["engagement_pct"] for t in topics) == 100.0


def test_timeline_shape(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, 12, spread_seconds=180)
    add_viewer_samples(db, stream, [5, 9])
    add_event(db, stream, "channel.cheer", amount=100)
    add_peak(db, stream)

    login_as(api_client, channel)
    timeline = api_client.get(f"/api/streams/{stream.id}/timeline").json()

    assert sum(point["value"] for point in timeline["chat"]) == 12
    assert [point["value"] for point in timeline["viewers"]] == [5, 9]
    assert timeline["events"][0]["type"] == "channel.cheer"
    assert timeline["events"][0]["amount"] == 100
    assert len(timeline["peaks"]) == 1


def test_peak_detail_window_and_404(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    peak = add_peak(db, stream, offset_seconds=60)
    add_chat(db, stream, 5, offset_seconds=70, spread_seconds=10)  # inside window
    add_chat(db, stream, 5, offset_seconds=300, spread_seconds=10)  # outside
    add_segment(db, stream, 65, "trecho dentro da janela")
    add_segment(db, stream, 400, "trecho fora")

    login_as(api_client, channel)
    detail = api_client.get(f"/api/streams/{stream.id}/peaks/{peak.id}").json()
    assert len(detail["messages"]) == 5
    assert len(detail["segments"]) == 1
    assert detail["segments"][0]["text"] == "trecho dentro da janela"

    other_stream = make_stream(db, channel)
    assert (
        api_client.get(f"/api/streams/{other_stream.id}/peaks/{peak.id}").status_code
        == 404
    )


def test_feedback_lifecycle_and_validation(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    insight = add_insight(db, stream)
    login_as(api_client, channel)

    assert (
        api_client.post(
            f"/api/insights/{insight.id}/feedback", json={"feedback": "useful"}
        ).status_code
        == 204
    )
    report = api_client.get(f"/api/streams/{stream.id}").json()
    assert report["insights"][0]["feedback"] == "useful"

    assert (
        api_client.post(
            f"/api/insights/{insight.id}/feedback", json={"feedback": None}
        ).status_code
        == 204
    )
    report = api_client.get(f"/api/streams/{stream.id}").json()
    assert report["insights"][0]["feedback"] is None

    assert (
        api_client.post(
            f"/api/insights/{insight.id}/feedback", json={"feedback": "invalido"}
        ).status_code
        == 422
    )
    assert (
        api_client.post(
            "/api/insights/999999/feedback", json={"feedback": "useful"}
        ).status_code
        == 404
    )


def test_feedback_denied_on_foreign_insight(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    foreign_insight = add_insight(db, make_stream(db, other))
    login_as(api_client, mine)
    response = api_client.post(
        f"/api/insights/{foreign_insight.id}/feedback", json={"feedback": "useful"}
    )
    assert response.status_code == 404


def test_search_matches_chat_and_transcript_with_isolation(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, 1, text="hoje vamos jogar muito")
    add_segment(db, stream, 10, "explicando o deploy da aplicação")
    other = make_channel(db)
    other_stream = make_stream(db, other)
    add_chat(db, other_stream, 1, text="jogar em outro canal")

    login_as(api_client, channel)
    hits = api_client.get("/api/search", params={"q": "jogar"}).json()
    assert len(hits) == 1
    assert hits[0]["source"] == "chat"
    assert hits[0]["stream_id"] == stream.id

    hits = api_client.get("/api/search", params={"q": "deploy"}).json()
    assert [h["source"] for h in hits] == ["transcript"]

    assert api_client.get("/api/search", params={"q": "x"}).status_code == 422
    assert api_client.get("/api/search").status_code == 422


def test_search_stream_filter(api_client, db) -> None:
    channel = make_channel(db)
    first = make_stream(db, channel)
    second = make_stream(db, channel, started_minutes_ago=300)
    add_chat(db, first, 1, text="assunto repetido")
    add_chat(db, second, 1, text="assunto repetido")

    login_as(api_client, channel)
    hits = api_client.get(
        "/api/search", params={"q": "repetido", "stream_id": first.id}
    ).json()
    assert {h["stream_id"] for h in hits} == {first.id}


def test_queue_position_ordered_by_next_live_urgency(api_client, db) -> None:
    # "soon" streams on today's weekday ~1h from now (next live today);
    # "later" streamed 3 days ago, so its weekday only recurs in 4 days
    soon = make_channel(db)
    for weeks in (1, 2):
        make_stream(db, soon, started_minutes_ago=weeks * 7 * 24 * 60 - 60)
    later = make_channel(db)
    make_stream(db, later, started_minutes_ago=3 * 24 * 60)

    soon_pending = make_stream(db, soon, StreamStatus.QUEUED_TRANSCRIPTION)
    later_pending = make_stream(db, later, StreamStatus.QUEUED_TRANSCRIPTION)
    add_job(db, soon_pending, JOB_TRANSCRIBE)
    add_job(db, later_pending, JOB_TRANSCRIBE)
    done = make_stream(db, soon, started_minutes_ago=500)
    add_job(
        db,
        done,
        JOB_TRANSCRIBE,
        JobStatus.DONE,
        started_minutes_ago=20,
        finished_minutes_ago=10,
    )

    login_as(api_client, later)
    items = api_client.get("/api/queue").json()
    assert len(items) == 1
    assert items[0]["job_type"] == "transcribe"
    assert items[0]["position"] == 2  # the soon channel's job is more urgent
    assert items[0]["eta_seconds"] == pytest.approx(2 * 600, rel=0.2)

    login_as(api_client, soon)
    mine = [
        i
        for i in api_client.get("/api/queue").json()
        if i["stream_id"] == soon_pending.id
    ]
    assert mine[0]["position"] == 1


def test_queue_running_job_has_no_position(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.ANALYZING)
    add_job(db, stream, JOB_ANALYZE, JobStatus.RUNNING, started_minutes_ago=1)
    login_as(api_client, channel)
    items = api_client.get("/api/queue").json()
    assert items[0]["status"] == "running"
    assert items[0]["position"] is None


def test_report_hides_music_lyrics_never_stored(api_client, db) -> None:
    """Music segments must come back kind=music with text null."""
    channel = make_channel(db)
    stream = make_stream(db, channel)
    peak = add_peak(db, stream, offset_seconds=60)
    add_segment(db, stream, 70, None, kind=SegmentKind.MUSIC)
    login_as(api_client, channel)
    detail = api_client.get(f"/api/streams/{stream.id}/peaks/{peak.id}").json()
    assert detail["segments"][0]["kind"] == "music"
    assert detail["segments"][0]["text"] is None


def test_chatters_stats_labels_and_isolation(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    # heavy chatter present the whole stream
    add_chat(db, stream, 12, author="fiel", offset_seconds=0, spread_seconds=1700)
    # light chatter concentrated in the peak window
    add_peak(db, stream, offset_seconds=300)
    add_chat(db, stream, 4, author="do_pico", offset_seconds=310, spread_seconds=30)
    # follow event carries the login of the light chatter
    follow = add_event(db, stream, "channel.follow", offset_seconds=100)
    follow.payload = {"user_login": "do_pico"}
    db.flush()

    login_as(api_client, channel)
    chatters = api_client.get(f"/api/streams/{stream.id}/chatters").json()

    assert [c["author_login"] for c in chatters] == ["fiel", "do_pico"]
    top = chatters[0]
    assert top["messages"] == 12
    assert top["pct_of_total"] == 75.0
    assert "nº 1 do chat" in top["labels"]
    assert "presente a live toda" in top["labels"]
    assert len(top["sample_messages"]) == 3

    light = chatters[1]
    assert light["peak_messages"] == 4
    assert "ativou nos picos" in light["labels"]
    assert light["followed_during_stream"] is True
    assert "seguiu durante a live" in light["labels"]

    other = make_channel(db)
    login_as(api_client, other)
    assert api_client.get(f"/api/streams/{stream.id}/chatters").status_code == 404


def test_chatters_empty_stream(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    login_as(api_client, channel)
    assert api_client.get(f"/api/streams/{stream.id}/chatters").json() == []


def test_topic_detail_window_stats_and_404s(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=20)
    segment = add_segment(db, stream, 300, "falando do assunto principal")
    # dense chat inside the topic window, sparse elsewhere
    add_chat(db, stream, 30, author="dentro", offset_seconds=290, spread_seconds=60)
    add_chat(db, stream, 6, author="fora", offset_seconds=900, spread_seconds=200)
    topic = add_insight(
        db,
        stream,
        InsightType.TOPIC,
        "Assunto\ndescrição",
        {"segment_ids": [segment.id], "message_ids": [], "rank": 1},
    )
    summary = add_insight(
        db, stream, InsightType.SUMMARY, "Resumo.", {"segment_ids": [segment.id]}
    )

    login_as(api_client, channel)
    detail = api_client.get(f"/api/streams/{stream.id}/topics/{topic.id}").json()

    assert detail["messages_in_window"] == 30
    assert detail["chat_rate_lift"] is not None and detail["chat_rate_lift"] > 1
    assert detail["top_chatters"][0]["author_login"] == "dentro"
    assert len(detail["sample_messages"]) == 8
    assert detail["cited_segments"][0]["text"] == "falando do assunto principal"

    # summary insight is not a topic
    assert (
        api_client.get(f"/api/streams/{stream.id}/topics/{summary.id}").status_code
        == 404
    )
    assert api_client.get(f"/api/streams/{stream.id}/topics/999999").status_code == 404
