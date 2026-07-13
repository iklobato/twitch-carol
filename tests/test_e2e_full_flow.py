"""End-to-end flow with FakeTwitch playing the Twitch API:
login -> capture -> transcription -> analysis -> dashboard visualization.

Everything inside the app is real (routes, crypto, HMAC verification, IRC
parsing, SQL, evidence validation); only the external borders are faked.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import core.eventsub
import core.twitch
import core.worker_loop
from core.channels import ensure_fresh_token
from core.crypto import decrypt_secret
from core.models import Channel, Stream, StreamStatus
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE, enqueue_job
from core.worker_loop import WorkerSpec, _run_job, pick_next_job
from tests.fake_twitch import FAKE_USER, FakeTwitch, http_seam, irc_line
from tests.test_analysis_e2e import PromptAwareFakeLLM
from workers.capture.collectors import ChatCollector, ViewerSampler
from workers.capture.session import build_audit
from workers.transcribe import pipeline as transcribe_pipeline
from workers.transcribe.pipeline import SAMPLE_RATE, process_stream

E2E_SECRET = "e2e-eventsub-secret"

SPEECH_SPANS = [(10.0, 40.0), (60.0, 90.0), (310.0, 340.0), (600.0, 630.0)]
SPEECH_SCRIPT = [
    "hoje vamos revisar o deploy da api na digital ocean",
    "o caddy renovou o certificado sozinho, que aula",
    "chegou a raid, bem-vindos, hype absurdo no chat",
    "resumo final: deploy fechado, amanhã tem mais live",
]
AUDIO_SECONDS = 720
CALM_MINUTES = 10
BURST_MINUTE = 5
BURST_MESSAGES = 30


@pytest.fixture
def e2e_env(
    monkeypatch: pytest.MonkeyPatch, fernet_key: None, twitch_env: None
) -> None:
    from core.config import get_settings

    monkeypatch.setenv("TWITCH_EVENTSUB_SECRET", E2E_SECRET)
    # https is required for the eventsub sync to run on login
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://e2e.test")
    get_settings.cache_clear()
    core.twitch._app_token.token = ""


@pytest.fixture
def fake_twitch(
    monkeypatch: pytest.MonkeyPatch, api_client, e2e_env: None
) -> FakeTwitch:
    fake = FakeTwitch(webhook_client=api_client, eventsub_secret=E2E_SECRET)
    seam = http_seam(fake)
    monkeypatch.setattr(core.twitch, "_http", seam)
    # eventsub binds _http at import time, so patch its copy too
    monkeypatch.setattr(core.eventsub, "_http", seam)
    return fake


class FakeStorage:
    def list_keys(self, prefix: str) -> list[str]:
        return [f"{prefix}000.ogg"]

    def fetch_file(self, key, destination) -> None:
        destination.write_bytes(b"fake")

    def save_file(self, key, local_path) -> None:  # pragma: no cover
        raise NotImplementedError


class ScriptedTranscriber:
    """Returns the scripted line for each speech region, in order."""

    def __init__(self) -> None:
        self._lines = iter(SPEECH_SCRIPT)

    def transcribe(self, audio) -> list[tuple[float, float, str]]:
        return [(0.0, 25.0, next(self._lines))]


def synthetic_audio(*args, **kwargs) -> np.ndarray:
    audio = np.zeros(AUDIO_SECONDS * SAMPLE_RATE, dtype=np.float32)
    # energy between 100s and 200s: the gap must classify as music
    t = np.arange(100 * SAMPLE_RATE) / SAMPLE_RATE
    audio[100 * SAMPLE_RATE : 200 * SAMPLE_RATE] = 0.2 * np.sin(2 * np.pi * 440 * t)
    return audio


def _login(api_client, fake_twitch: FakeTwitch, db) -> Channel:
    response = api_client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]

    code = fake_twitch.authorize()
    callback = api_client.get(
        "/auth/callback", params={"code": code, "state": state}, follow_redirects=False
    )
    assert callback.status_code == 307
    channel = db.scalar(select(Channel).where(Channel.login == FAKE_USER["login"]))
    assert channel is not None
    return channel


def _run_live(api_client, fake_twitch: FakeTwitch, db, channel: Channel) -> Stream:
    started_at = datetime.now(UTC) - timedelta(minutes=12)
    assert (
        fake_twitch.send_event(
            "stream.online",
            {
                "broadcaster_user_id": FAKE_USER["id"],
                "type": "live",
                "started_at": started_at.isoformat(),
            },
        )
        == 204
    )
    stream = db.scalar(select(Stream).where(Stream.channel_id == channel.id))
    assert stream is not None and stream.status == StreamStatus.CAPTURING

    collector = ChatCollector(stream, channel)
    for minute in range(CALM_MINUTES):
        for index in range(5):
            author = f"viewer_{index}"
            sent_at = stream.started_at + timedelta(minutes=minute, seconds=index * 10)
            collector._ingest(
                irc_line(channel.login, author, "falando de deploy e caddy", sent_at)
            )
    for index in range(BURST_MESSAGES):
        sent_at = stream.started_at + timedelta(minutes=BURST_MINUTE, seconds=index)
        collector._ingest(
            irc_line(
                channel.login, f"raider_{index % 6}", "POGGERS hype demais", sent_at
            )
        )
    collector._flush()

    sampler = ViewerSampler(stream, channel)
    for viewers in (50, 60, 120, 80, 55):
        fake_twitch.stream_info = {
            "viewer_count": viewers,
            "title": "Live e2e",
            "game_name": "Software and Game Development",
            "started_at": started_at.isoformat(),
        }
        sampler._sample_once()

    events: list[tuple[str, dict]] = [
        ("channel.raid", {"to_broadcaster_user_id": FAKE_USER["id"], "viewers": 60}),
        (
            "channel.follow",
            {"broadcaster_user_id": FAKE_USER["id"], "user_login": "raider_1"},
        ),
        ("channel.cheer", {"broadcaster_user_id": FAKE_USER["id"], "bits": 300}),
    ]
    for sub_type, event in events:
        assert fake_twitch.send_event(sub_type, event) == 204

    assert (
        fake_twitch.send_event(
            "stream.offline", {"broadcaster_user_id": FAKE_USER["id"]}
        )
        == 204
    )
    db.expire_all()
    assert stream.ended_at is not None

    # capture-finalize equivalent (the worker does this when collectors stop)
    stream.audit = build_audit(
        db, stream, collector.stats, sampler.stats, {"segments": 1}
    )
    stream.status = StreamStatus.QUEUED_TRANSCRIPTION

    enqueue_job(db, core.worker_loop.get_valkey(), JOB_TRANSCRIBE, stream.id)
    db.commit()
    return stream


def _process(db, stream: Stream, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcribe_pipeline, "get_audio_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        transcribe_pipeline, "detect_speech_spans", lambda audio: SPEECH_SPANS
    )
    import faster_whisper.audio

    monkeypatch.setattr(faster_whisper.audio, "decode_audio", synthetic_audio)

    transcriber = ScriptedTranscriber()
    transcribe_spec = WorkerSpec(
        job_type=JOB_TRANSCRIBE,
        running_status=StreamStatus.TRANSCRIBING,
        done_status=StreamStatus.QUEUED_ANALYSIS,
        next_job_type=JOB_ANALYZE,
    )
    job = pick_next_job(db, JOB_TRANSCRIBE, datetime.now(UTC))
    assert job is not None
    _run_job(
        db,
        transcribe_spec,
        job,
        # ScriptedTranscriber is a structural test double for Transcriber
        lambda handler_db, handler_stream: process_stream(
            handler_db, handler_stream, transcriber  # type: ignore[arg-type]
        ),
    )
    db.expire_all()
    assert stream.status == StreamStatus.QUEUED_ANALYSIS

    analyze_spec = WorkerSpec(
        job_type=JOB_ANALYZE,
        running_status=StreamStatus.ANALYZING,
        done_status=StreamStatus.READY,
    )
    job = pick_next_job(db, JOB_ANALYZE, datetime.now(UTC))
    assert job is not None
    backend = PromptAwareFakeLLM()
    from workers.analyze.pipeline import run_analysis

    _run_job(
        db,
        analyze_spec,
        job,
        lambda handler_db, handler_stream: run_analysis(
            handler_db, handler_stream, backend
        ),
    )
    db.expire_all()
    assert stream.status == StreamStatus.READY


def test_full_flow_login_processing_visualization(
    api_client,
    db,
    fake_twitch: FakeTwitch,
    fake_valkey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # collectors and the worker loop open their own sessions/valkey: bind
    # them to the test transaction and the fake broker
    bound = sessionmaker(
        bind=db.get_bind(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    import workers.capture.collectors as collectors

    monkeypatch.setattr(collectors, "session_factory", lambda: bound)
    monkeypatch.setattr(core.worker_loop, "get_valkey", lambda: fake_valkey)

    # ---- phase 1: login (oauth code flow against FakeTwitch) --------------
    channel = _login(api_client, fake_twitch, db)
    assert channel.access_token_encrypted is not None
    issued_access = decrypt_secret(channel.access_token_encrypted)
    assert issued_access in fake_twitch.user_tokens
    assert channel.scopes == core.twitch.OAUTH_SCOPES

    # eventsub sync ran on login: every subscription challenged and enabled
    assert len(fake_twitch.subscriptions) == len(core.eventsub.SUBSCRIPTION_SPECS)
    assert {s["status"] for s in fake_twitch.subscriptions} == {"enabled"}

    # token refresh rotates through the fake as well
    channel.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    new_access = ensure_fresh_token(db, channel)
    assert new_access != issued_access and new_access in fake_twitch.user_tokens

    # ---- phase 2: a full live is captured and processed --------------------
    stream = _run_live(api_client, fake_twitch, db, channel)
    _process(db, stream, monkeypatch)

    # ---- phase 3: everything is visible through the dashboard api ---------
    streams = api_client.get("/api/streams").json()
    assert len(streams) == 1
    item = streams[0]
    total_messages = CALM_MINUTES * 5 + BURST_MESSAGES
    assert item["messages"] == total_messages
    assert item["followers"] == 1
    assert item["peak_viewers"] == 120
    assert item["status"] == "ready"
    assert item["title"] == "Live e2e"

    report = api_client.get(f"/api/streams/{stream.id}").json()
    assert report["numbers"]["messages"]["value"] == total_messages
    assert len(report["peaks"]) >= 1
    types = {insight["type"] for insight in report["insights"]}
    assert {"summary", "peak_explanation", "topic"} <= types
    summary = next(i for i in report["insights"] if i["type"] == "summary")
    assert summary["cited_segments"], "summary must cite real transcript segments"

    timeline = api_client.get(f"/api/streams/{stream.id}/timeline").json()
    assert {event["type"] for event in timeline["events"]} == {
        "channel.raid",
        "channel.follow",
        "channel.cheer",
    }

    # "certificado" only appears in the streamer's speech, not in chat
    segments = api_client.get(
        "/api/search", params={"q": "certificado", "stream_id": stream.id}
    ).json()
    assert any(hit["source"] == "transcript" for hit in segments)
    # a chat word is found too
    chat_hits = api_client.get(
        "/api/search", params={"q": "poggers", "stream_id": stream.id}
    ).json()
    assert any(hit["source"] == "chat" for hit in chat_hits)

    chatters = api_client.get(f"/api/streams/{stream.id}/chatters").json()
    raider = next(c for c in chatters if c["author_login"] == "raider_1")
    assert raider["followed_during_stream"] is True
    assert "seguiu durante a live" in raider["labels"]

    community = api_client.get(f"/api/streams/{stream.id}/community").json()
    assert community["sentiment_overall"] is not None
    assert community["sentiment_overall"] > 0  # POGGERS/hype/aula corpus
    assert "deploy" in {w["word"] for w in community["words"]}
    assert sum(s["messages"] for s in community["share"]) == total_messages

    topic = next(i for i in report["insights"] if i["type"] == "topic")
    detail = api_client.get(f"/api/streams/{stream.id}/topics/{topic['id']}").json()
    assert detail["cited_segments"]

    assert api_client.get("/api/queue").json() == []
    jobs = db.execute(select(Stream).where(Stream.id == stream.id)).scalar_one()
    assert jobs.status == StreamStatus.READY


def test_full_flow_rejects_forged_webhooks(
    api_client, db, fake_twitch: FakeTwitch
) -> None:
    """A notification signed with the wrong secret must be refused."""
    forged = FakeTwitch(webhook_client=api_client, eventsub_secret="wrong-secret")
    status = forged.send_event(
        "stream.online",
        {
            "broadcaster_user_id": FAKE_USER["id"],
            "type": "live",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    assert status == 403


def test_login_with_invalid_code_fails(api_client, db, fake_twitch: FakeTwitch) -> None:
    response = api_client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    callback = api_client.get(
        "/auth/callback",
        params={"code": "codigo-invalido", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 502
    assert db.scalar(select(Channel).where(Channel.login == FAKE_USER["login"])) is None
