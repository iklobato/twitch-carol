"""Seeds the database with mocked streams in every pipeline state, so the
processing stepper and the report UI can be seen without waiting for a live.

The rich stream gets realistic chat (with a burst), PT speech segments and
events, plus a REAL queued analyze job: the running worker picks it up and
the local LLM generates insights over the mocked data while you watch.

Static-state streams get no queued jobs (running/failed job rows only), so
active workers never consume them and the states hold for inspection.

Usage:
    python scripts/seed_pipeline_states.py                  # mock channel
    python scripts/seed_pipeline_states.py --login iklobat  # existing channel

Re-running wipes only streams previously created by this script (matched by
the seed titles), never real captured lives.
"""

import argparse
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from core.db import ensure_chat_partition, session_factory
from core.models import (
    Channel,
    ChatMessage,
    Event,
    Insight,
    InsightType,
    Job,
    JobStatus,
    SegmentKind,
    Stream,
    StreamStatus,
    TranscriptSegment,
    ViewerSample,
)
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE, QUEUE_KEYS, get_valkey

MOCK_LOGIN = "mock_streamer"
MOCK_TWITCH_USER_ID = 990000002

HISTORY_TITLES = [
    "Setup inicial do projeto",
    "Modelando o banco de dados",
    "Primeira API no ar",
    "Testes e CI",
]
SEED_TITLES = {
    "AO VIVO: configurando deploy",
    "Deploy na DigitalOcean",
    "DNS e certificados",
    "Caddy do zero",
    "Live com falha de análise",
    "Deploy completo com raid",
    *HISTORY_TITLES,
}
# a few loyal regulars that appear across the historical streams
LOYAL_REGULARS = ["mockviewer_11", "mockviewer_04", "fiel_carlos", "fiel_ana"]

SPEECH_SCRIPT = [
    "fala pessoal, hoje a gente vai configurar o deploy da nossa api na digital ocean",
    "primeiro passo é criar o droplet e apontar o dns do domínio",
    "olha esse erro de certificado, vou mostrar como o caddy resolve isso sozinho",
    "agora sim, o site está no ar com https funcionando",
    "chegou uma raid! bem-vindos pessoal do canal parceiro, estamos subindo uma api em produção",
    "esse momento foi incrível, obrigado pela energia no chat",
    "pra fechar, vamos revisar o que aprendemos sobre deploy e dns hoje",
    "amanhã tem mais, vamos implementar o backup automático do banco",
]
CALM_CHAT = [
    "boa noite!",
    "que aula",
    "deploy na veia",
    "esse caddy é mágico",
    "qual o custo desse droplet?",
    "ansioso pelo backup automático",
    "dns propagou rápido hein",
]
BURST_CHAT = ["RAID HYPE", "CHEGAMOS", "POGGERS", "que recepção", "GG", "melhor live"]


def _wipe_seeded_streams(db, channel: Channel) -> None:
    """Removes only streams this script created before (matched by title)."""
    stream_ids = list(
        db.scalars(
            select(Stream.id)
            .where(Stream.channel_id == channel.id)
            .where(Stream.title.in_(SEED_TITLES))
        )
    )
    if not stream_ids:
        return
    from core.models import Peak

    for model in (
        ChatMessage,
        Event,
        TranscriptSegment,
        ViewerSample,
        Job,
        Insight,
        Peak,
    ):
        db.execute(delete(model).where(model.stream_id.in_(stream_ids)))
    db.execute(delete(Stream).where(Stream.id.in_(stream_ids)))


def target_channel(db, login: str | None) -> Channel:
    if login is not None:
        channel = db.scalar(select(Channel).where(Channel.login == login))
        if channel is None:
            raise SystemExit(f"channel '{login}' not found; connect it first")
        _wipe_seeded_streams(db, channel)
        return channel
    channel = db.scalar(
        select(Channel).where(Channel.twitch_user_id == MOCK_TWITCH_USER_ID)
    )
    if channel is None:
        channel = Channel(
            twitch_user_id=MOCK_TWITCH_USER_ID,
            login=MOCK_LOGIN,
            display_name="Mock Streamer",
            scopes=[],
        )
        db.add(channel)
        db.flush()
    _wipe_seeded_streams(db, channel)
    return channel


def make_stream(
    db, channel, status, started_min_ago, duration_min=None, title=None
) -> Stream:
    started = datetime.now(UTC) - timedelta(minutes=started_min_ago)
    stream = Stream(
        channel_id=channel.id,
        started_at=started,
        ended_at=started + timedelta(minutes=duration_min) if duration_min else None,
        status=status,
        title=title,
    )
    db.add(stream)
    db.flush()
    return stream


def add_job(db, stream, job_type, status, error=None):
    now = datetime.now(UTC)
    db.add(
        Job(
            type=job_type,
            stream_id=stream.id,
            status=status,
            attempts=1 if status != JobStatus.QUEUED else 0,
            started_at=(
                now - timedelta(minutes=2) if status != JobStatus.QUEUED else None
            ),
            finished_at=now if status in (JobStatus.DONE, JobStatus.FAILED) else None,
            error=error,
        )
    )


def fill_rich_stream(db, channel, stream) -> None:
    """Chat with a burst, PT speech segments, viewers and events: enough for
    peaks + real LLM analysis over mocked data."""
    random.seed(42)
    start = stream.started_at
    end = stream.ended_at
    total_seconds = int((end - start).total_seconds())
    burst_start = total_seconds // 2
    burst_end = burst_start + 90
    ensure_chat_partition(db, start.date())

    for second in range(0, total_seconds, 2):
        in_burst = burst_start <= second < burst_end
        per_tick = 6 if in_burst else 1
        for _ in range(per_tick):
            author = f"mockviewer_{random.randint(0, 25):02d}"
            db.add(
                ChatMessage(
                    stream_id=stream.id,
                    channel_id=channel.id,
                    sent_at=start + timedelta(seconds=second + random.random()),
                    message_id=str(uuid.uuid4()),
                    author_id=author,
                    author_login=author,
                    text=random.choice(BURST_CHAT if in_burst else CALM_CHAT),
                )
            )

    segment_gap = total_seconds // len(SPEECH_SCRIPT)
    for index, text in enumerate(SPEECH_SCRIPT):
        seg_start = start + timedelta(seconds=index * segment_gap + 5)
        db.add(
            TranscriptSegment(
                stream_id=stream.id,
                started_at=seg_start,
                ended_at=seg_start + timedelta(seconds=25),
                kind=SegmentKind.SPEECH,
                text=text,
            )
        )

    for minute in range(0, total_seconds // 60):
        sampled = start + timedelta(minutes=minute)
        in_burst = burst_start <= minute * 60 < burst_end
        db.add(
            ViewerSample(
                stream_id=stream.id,
                sampled_at=sampled,
                viewer_count=180 if in_burst else 70 + minute,
            )
        )

    db.add(
        Event(
            stream_id=stream.id,
            channel_id=channel.id,
            occurred_at=start + timedelta(seconds=burst_start),
            type="channel.raid",
            payload={"from_broadcaster_user_login": "canal_parceiro", "viewers": 95},
            amount=95,
        )
    )
    db.add(
        Event(
            stream_id=stream.id,
            channel_id=channel.id,
            occurred_at=start + timedelta(seconds=burst_start + 40),
            type="channel.follow",
            payload={"user_login": "novo_fa_mock"},
        )
    )
    # money events during the raid window -> demonstrates the finance section
    for offset, etype, amount, payload in [
        (
            burst_start + 10,
            "channel.cheer",
            1000,
            {"user_login": "mockviewer_11", "bits": 1000},
        ),
        (
            burst_start + 25,
            "channel.cheer",
            300,
            {"user_login": "fiel_carlos", "bits": 300},
        ),
        (
            burst_start + 50,
            "channel.subscribe",
            2000,
            {"user_login": "fiel_ana", "tier": "2000"},
        ),
        (
            burst_start + 70,
            "channel.subscription.gift",
            5,
            {"user_login": "mockviewer_11", "tier": "1000"},
        ),
    ]:
        db.add(
            Event(
                stream_id=stream.id,
                channel_id=channel.id,
                occurred_at=start + timedelta(seconds=offset),
                type=etype,
                payload=payload,
                amount=amount,
            )
        )


def seed_history(db, channel) -> None:
    """Finished (READY) past streams sharing loyal regulars, so the channel
    overview shows real cross-live loyalty and growth."""
    for index, title in enumerate(HISTORY_TITLES):
        days_ago = (len(HISTORY_TITLES) - index) * 7
        stream = make_stream(
            db, channel, StreamStatus.READY, days_ago * 24 * 60, 90, title
        )
        ensure_chat_partition(db, stream.started_at.date())
        # regulars grow their message count each stream; audience grows too
        for regular_index, regular in enumerate(LOYAL_REGULARS):
            for msg in range(3 + index * 2 + regular_index):
                db.add(
                    ChatMessage(
                        stream_id=stream.id,
                        channel_id=channel.id,
                        sent_at=stream.started_at + timedelta(minutes=msg),
                        message_id=str(uuid.uuid4()),
                        author_id=regular,
                        author_login=regular,
                        text=random.choice(CALM_CHAT),
                    )
                )
        for minute in range(90):
            db.add(
                ViewerSample(
                    stream_id=stream.id,
                    sampled_at=stream.started_at + timedelta(minutes=minute),
                    viewer_count=40 + index * 25 + (minute % 20),
                )
            )
        db.add(
            Event(
                stream_id=stream.id,
                channel_id=channel.id,
                occurred_at=stream.started_at + timedelta(minutes=10),
                type="channel.follow",
                payload={"user_login": f"seguidor_{index}"},
            )
        )
        # a regular cheers each stream, growing all-time contributions
        db.add(
            Event(
                stream_id=stream.id,
                channel_id=channel.id,
                occurred_at=stream.started_at + timedelta(minutes=15),
                type="channel.cheer",
                payload={"user_login": "fiel_carlos", "bits": 200 + index * 100},
                amount=200 + index * 100,
            )
        )
        db.add(
            Insight(
                stream_id=stream.id,
                type=InsightType.TOPIC,
                content="Deploy\nassunto recorrente",
                evidence={"message_ids": [], "segment_ids": [], "rank": 1},
                model_used="seed",
                tokens_in=0,
                tokens_out=0,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--login", default=None, help="seed an existing channel by login"
    )
    args = parser.parse_args()

    with session_factory()() as db:
        channel = target_channel(db, args.login)
        seed_history(db, channel)

        capturing = make_stream(
            db,
            channel,
            StreamStatus.CAPTURING,
            12,
            None,
            "AO VIVO: configurando deploy",
        )
        # queued state WITHOUT a queued job row: running workers would consume
        # it; the status alone drives the stepper display
        queued_t = make_stream(
            db,
            channel,
            StreamStatus.QUEUED_TRANSCRIPTION,
            120,
            45,
            "Deploy na DigitalOcean",
        )
        transcribing = make_stream(
            db, channel, StreamStatus.TRANSCRIBING, 180, 50, "DNS e certificados"
        )
        add_job(db, transcribing, JOB_TRANSCRIBE, JobStatus.RUNNING)
        analyzing = make_stream(
            db, channel, StreamStatus.ANALYZING, 240, 40, "Caddy do zero"
        )
        add_job(db, analyzing, JOB_ANALYZE, JobStatus.RUNNING)
        failed = make_stream(
            db, channel, StreamStatus.FAILED, 300, 35, "Live com falha de análise"
        )
        add_job(
            db,
            failed,
            JOB_ANALYZE,
            JobStatus.FAILED,
            error="MockError: llm backend crashed",
        )

        rich = make_stream(
            db,
            channel,
            StreamStatus.QUEUED_ANALYSIS,
            60,
            20,
            "Deploy completo com raid",
        )
        fill_rich_stream(db, channel, rich)
        analyze_job = Job(type=JOB_ANALYZE, stream_id=rich.id, status=JobStatus.QUEUED)
        db.add(analyze_job)
        db.flush()
        get_valkey().xadd(
            QUEUE_KEYS[JOB_ANALYZE],
            {"job_id": str(analyze_job.id), "stream_id": str(rich.id)},
        )
        db.commit()

        print(f"channel id: {channel.id}")
        print(f"capturing:            stream {capturing.id}")
        print(f"queued_transcription: stream {queued_t.id}")
        print(f"transcribing:         stream {transcribing.id}")
        print(f"analyzing:            stream {analyzing.id}")
        print(f"failed:               stream {failed.id}")
        print(f"rich queued_analysis: stream {rich.id} (analyze job {analyze_job.id})")


if __name__ == "__main__":
    main()
