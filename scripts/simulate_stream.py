"""Simulates a full live stream against the running compose stack.

Everything flows through the real code paths: stream lifecycle and events go
through the EventSub webhook (HMAC-signed), chat goes as raw IRC lines that
the capture worker parses with the real parser, viewers and audio come from
the same collector code reading the sim sources.

Run from the repo root with the stack up and SIMULATION=1 on worker-capture:
    uv run python scripts/simulate_stream.py --minutes 3

The channel is created the way production creates one: served in English. What
--idioma picks is what the fake streamer SPEAKS and what the fake chat types, so
it must match the audio file you pass. That mismatch is the realistic case: a
Brazilian streamer on an English product.
    uv run python scripts/simulate_stream.py --idioma pt --audio fala.mp3
"""

import argparse
import json
import math
import random
import shutil
import struct
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import redis
from sqlalchemy import select
from sqlalchemy.engine import make_url

from core.channels import SIGNUP_LANGUAGE
from core.config import get_settings
from core.db import session_factory
from core.eventsub import compute_signature
from core.models import Channel, Stream, StreamStatus

SIM_LOGIN = "sim_streamer"
SIM_TWITCH_USER_ID = 990000001
# Must match deploy/sim.env, which the api container loads as a dev default.
DEV_EVENTSUB_SECRET = "dev-simulation-secret"

DATA_DIR = Path("data/sim")
CONTAINER_DATA_DIR = Path("/data/sim")

BASE_RATE_HZ = 2.0
BURST_RATE_HZ = 20.0
BURST_DURATION_SECONDS = 30
BASE_VIEWERS = 50
BURST_VIEWERS = 120
# below this, a single burst: with few 60s buckets, two bursts drag the
# median up and no bucket clears the peak-detection lift threshold
TWO_BURSTS_MIN_SECONDS = 360

CHAT_USERS = [f"viewer_{i:02d}" for i in range(40)]


@dataclass(frozen=True)
class ChatCorpus:
    """What the fake chat types, in one language. The three pieces live in one
    object so a language can never be half added: a missing burst list would
    only blow up minutes into a run, right at the peak it was meant to test."""

    calm: list[str]
    burst: list[str]
    cheer: str


# One corpus per language, because the two things this harness exists to prove
# are language-bound: the stopword list has to leave real subjects standing,
# and the sentiment lexicon has to match actual words. English chat scored with
# the Portuguese lexicon comes back empty, which is the bug worth catching here.
CORPORA: dict[str, ChatCorpus] = {
    "pt": ChatCorpus(
        calm=[
            "boa noite pessoal",
            "esse framework parece bom",
            "alguém sabe o link do repo?",
            "primeira vez aqui na live",
            "o que é injeção de dependência?",
            "streamer joga muito",
            "faz um tutorial disso depois",
            "LUL",
            "esse bug tá difícil hein",
            "concordo com o chat",
            "usa docker pra isso?",
            "qual teclado você usa?",
        ],
        burst=[
            "KKKKKKKK",
            "NÃO ACREDITO",
            "CLIPA ISSO",
            "GG GG GG",
            "que jogada absurda",
            "POGGERS",
            "melhor momento da live",
            "vai dar certo vai dar certo",
        ],
        cheer="toma esses bits",
    ),
    "en": ChatCorpus(
        calm=[
            "good evening everyone",
            "this framework looks nice",
            "anyone got the repo link?",
            "first time here on stream",
            "what is dependency injection?",
            "streamer is cracked at this game",
            "make a tutorial about this later",
            "LUL",
            "that bug looks annoying",
            "chat is right about this",
            "do you use docker for this?",
            "what keyboard do you use?",
        ],
        burst=[
            "LMAOOOO",
            "NO WAY",
            "CLIP IT",
            "GG GG GG",
            "that play was insane",
            "POGGERS",
            "best moment of the stream",
            "lets go lets go",
        ],
        cheer="take these bits",
    ),
}


def irc_line(author: str, text: str, sent_at: datetime) -> str:
    ts_ms = int(sent_at.timestamp() * 1000)
    uid = 100000 + CHAT_USERS.index(author) if author in CHAT_USERS else 999999
    tags = (
        f"badges=;display-name={author};emotes=;id={uuid.uuid4()};"
        f"tmi-sent-ts={ts_ms};user-id={uid}"
    )
    return f"@{tags} :{author}!{author}@{author}.tmi.twitch.tv PRIVMSG #{SIM_LOGIN} :{text}"


class WebhookPoster:
    def __init__(self, base_url: str, secret: str) -> None:
        self._url = f"{base_url}/eventsub/callback"
        self._secret = secret
        self._client = httpx.Client(timeout=10.0)

    def post(self, sub_type: str, event: dict, version: str = "1") -> None:
        body = json.dumps(
            {
                "subscription": {
                    "id": str(uuid.uuid4()),
                    "type": sub_type,
                    "version": version,
                },
                "event": event,
            }
        ).encode()
        message_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = self._client.post(
            self._url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Twitch-Eventsub-Message-Id": message_id,
                "Twitch-Eventsub-Message-Timestamp": timestamp,
                "Twitch-Eventsub-Message-Type": "notification",
                "Twitch-Eventsub-Message-Signature": compute_signature(
                    self._secret, message_id, timestamp, body
                ),
            },
        )
        response.raise_for_status()
        print(f"  event {sub_type} -> {response.status_code}")


def ensure_sim_channel() -> int:
    """The sim channel, created on first use exactly like a real sign-up: served
    in English, with no spoken language yet. The spoken one is left blank on
    purpose, because watching the transcriber fill it in from the audio is part
    of what this harness exists to check."""
    with session_factory()() as db:
        channel = db.scalar(
            select(Channel).where(Channel.twitch_user_id == SIM_TWITCH_USER_ID)
        )
        if channel is None:
            channel = Channel(
                twitch_user_id=SIM_TWITCH_USER_ID,
                login=SIM_LOGIN,
                display_name="Sim Streamer",
                scopes=[],
                language=SIGNUP_LANGUAGE,
            )
            db.add(channel)
            db.commit()
        return channel.id


def generate_tone_wav(path: Path, seconds: int) -> None:
    """Stdlib-only test audio: a wandering sine so the file is not silence."""
    sample_rate = 16000
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        frames = bytearray()
        for i in range(sample_rate * seconds):
            freq = 220 + 110 * math.sin(2 * math.pi * i / (sample_rate * 10))
            value = int(12000 * math.sin(2 * math.pi * freq * i / sample_rate))
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


def reset_sim_state(valkey: redis.Redis) -> None:
    # The chat collector replays sim:irc from id 0: leftovers from previous
    # runs would be ingested into the new stream with their old timestamps.
    valkey.delete(f"sim:irc:{SIM_LOGIN}")


def prepare_audio(valkey: redis.Redis, source: Path | None, seconds: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if source is None:
        target = DATA_DIR / "generated_tone.wav"
        generate_tone_wav(target, seconds)
    else:
        target = DATA_DIR / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
    container_path = CONTAINER_DATA_DIR / target.name
    valkey.set(f"sim:audio:{SIM_LOGIN}", str(container_path), ex=3600)
    print(f"audio source ready: {target} (container: {container_path})")


def burst_windows(total_seconds: int) -> list[range]:
    first = int(total_seconds * 0.45)
    windows = [range(first, first + BURST_DURATION_SECONDS)]
    if total_seconds >= TWO_BURSTS_MIN_SECONDS:
        second = int(total_seconds * 0.75)
        windows.append(range(second, second + BURST_DURATION_SECONDS))
    return windows


def run_chat_and_viewers(
    valkey: redis.Redis, poster: WebhookPoster, total_seconds: int, language: str
) -> int:
    bursts = burst_windows(total_seconds)
    sent = 0
    started = time.monotonic()
    fired_events: set[str] = set()
    while True:
        elapsed = int(time.monotonic() - started)
        if elapsed >= total_seconds:
            return sent
        in_burst = any(elapsed in window for window in bursts)
        rate = BURST_RATE_HZ if in_burst else BASE_RATE_HZ
        viewers = BURST_VIEWERS if in_burst else BASE_VIEWERS
        valkey.set(f"sim:viewers:{SIM_LOGIN}", viewers, ex=300)

        author = random.choice(CHAT_USERS)
        corpus = CORPORA[language]
        messages = corpus.burst if in_burst else corpus.calm
        line = irc_line(author, random.choice(messages), datetime.now(UTC))
        valkey.xadd(f"sim:irc:{SIM_LOGIN}", {"line": line})
        sent += 1

        _fire_scheduled_events(
            poster, elapsed, total_seconds, in_burst, fired_events, language
        )
        time.sleep(1.0 / rate)


def _fire_scheduled_events(
    poster: WebhookPoster,
    elapsed: int,
    total: int,
    in_burst: bool,
    fired: set[str],
    language: str,
) -> None:
    broadcaster = {"broadcaster_user_id": str(SIM_TWITCH_USER_ID)}
    schedule = {
        "follow_early": (
            int(total * 0.15),
            "channel.follow",
            {
                **broadcaster,
                "user_id": "42",
                "user_login": "novo_fa",
                "followed_at": datetime.now(UTC).isoformat(),
            },
            "2",
        ),
        "sub": (
            int(total * 0.4),
            "channel.subscribe",
            {
                **broadcaster,
                "user_id": "43",
                "user_login": "sub_novo",
                "tier": "1000",
                "is_gift": False,
            },
            "1",
        ),
        "cheer": (
            int(total * 0.35),
            "channel.cheer",
            {
                **broadcaster,
                "user_id": "44",
                "user_login": "generoso",
                "bits": 500,
                "message": CORPORA[language].cheer,
            },
            "1",
        ),
        "raid": (
            int(total * 0.65),
            "channel.raid",
            {
                "to_broadcaster_user_id": str(SIM_TWITCH_USER_ID),
                "from_broadcaster_user_id": "555",
                "from_broadcaster_user_login": "canal_amigo",
                "viewers": 80,
            },
            "1",
        ),
        "follow_late": (
            int(total * 0.8),
            "channel.follow",
            {
                **broadcaster,
                "user_id": "45",
                "user_login": "outro_fa",
                "followed_at": datetime.now(UTC).isoformat(),
            },
            "2",
        ),
    }
    for key, (at_second, sub_type, event, version) in schedule.items():
        if key not in fired and elapsed >= at_second:
            poster.post(sub_type, event, version)
            fired.add(key)


def wait_for_finalize(timeout_seconds: int = 180) -> Stream | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with session_factory()() as db:
            channel_id = ensure_sim_channel()
            stream = db.scalar(
                select(Stream)
                .where(Stream.channel_id == channel_id)
                .order_by(Stream.started_at.desc())
            )
            if (
                stream is not None
                and stream.status == StreamStatus.QUEUED_TRANSCRIPTION
            ):
                return stream
        time.sleep(3)
    return None


LOCAL_HOSTS = (None, "", "localhost", "127.0.0.1", "postgres", "valkey")


def _refuse_remote_services() -> None:
    """This script writes a fake channel, fake chat and fake events straight
    into whatever database and Valkey core.config resolves. Those come from the
    repo's .env, which on this machine points at the managed cluster and the
    managed Valkey, so the harness checks where it is aiming before it invents
    a single message."""
    settings = get_settings()
    for name, url, fix in (
        (
            "DATABASE_URL",
            settings.database_url,
            "postgresql+psycopg://app:app@localhost:5433/app",
        ),
        ("VALKEY_URL", settings.valkey_url, "redis://localhost:6380/0"),
    ):
        host = make_url(url).host
        if host not in LOCAL_HOSTS:
            raise SystemExit(
                f"refusing to simulate against {host}: the harness writes fake "
                f"data and only ever runs on the local compose stack. "
                f"Set {name}={fix}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=3.0)
    parser.add_argument(
        "--audio", type=Path, default=None, help="mp3/ogg/wav input file"
    )
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument(
        "--idioma",
        choices=sorted(CORPORA),
        default="pt",
        help="what the streamer speaks: picks the chat corpus, must match --audio",
    )
    args = parser.parse_args()

    _refuse_remote_services()
    secret = get_settings().twitch_eventsub_secret or DEV_EVENTSUB_SECRET
    poster = WebhookPoster(args.base_url, secret)
    valkey = redis.Redis.from_url(get_settings().valkey_url, decode_responses=True)
    total_seconds = int(args.minutes * 60)

    ensure_sim_channel()
    reset_sim_state(valkey)
    prepare_audio(valkey, args.audio, total_seconds)

    print("stream.online ->")
    poster.post(
        "stream.online",
        {
            "broadcaster_user_id": str(SIM_TWITCH_USER_ID),
            "broadcaster_user_login": SIM_LOGIN,
            "type": "live",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )

    sent = run_chat_and_viewers(valkey, poster, total_seconds, args.idioma)
    print(f"chat finished: {sent} messages sent")

    print("stream.offline ->")
    poster.post("stream.offline", {"broadcaster_user_id": str(SIM_TWITCH_USER_ID)})

    stream = wait_for_finalize()
    if stream is None:
        raise SystemExit("stream was not finalized in time; check worker-capture logs")
    print(f"\nstream {stream.id} finalized with status {stream.status.value}")
    print("audit:", json.dumps(stream.audit, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
