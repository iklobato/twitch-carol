import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import numpy as np

from core.models import Channel, SegmentKind, Stream
from workers.transcribe.pipeline import (
    SAMPLE_RATE,
    Region,
    Transcription,
    _persist_region,
    _remember_spoken_language,
    classify_regions,
    merge_speech_spans,
    rms_energy,
)


def _seconds(n: float) -> int:
    return int(n * SAMPLE_RATE)


def _audio(total_seconds: float) -> np.ndarray:
    return np.zeros(_seconds(total_seconds), dtype=np.float32)


def _with_tone(audio: np.ndarray, start: float, end: float) -> np.ndarray:
    t = np.arange(_seconds(end - start)) / SAMPLE_RATE
    audio[_seconds(start) : _seconds(end)] = 0.2 * np.sin(2 * np.pi * 440 * t)
    return audio


def test_merge_speech_spans_joins_small_gaps() -> None:
    assert merge_speech_spans([(0.0, 2.0), (2.5, 4.0), (10.0, 12.0)]) == [
        (0.0, 4.0),
        (10.0, 12.0),
    ]


def test_silence_gap_is_marked_silence() -> None:
    audio = _audio(30.0)
    regions = classify_regions(audio, [(0.0, 10.0), (20.0, 30.0)])
    kinds = [(round(r.start), round(r.end), r.kind) for r in regions]
    assert kinds == [
        (0, 10, SegmentKind.SPEECH),
        (10, 20, SegmentKind.SILENCE),
        (20, 30, SegmentKind.SPEECH),
    ]


def test_energetic_gap_is_marked_music() -> None:
    audio = _with_tone(_audio(30.0), 10.0, 20.0)
    regions = classify_regions(audio, [(0.0, 10.0), (20.0, 30.0)])
    assert regions[1].kind == SegmentKind.MUSIC


def test_short_gaps_are_not_segmented() -> None:
    regions = classify_regions(_audio(20.0), [(0.0, 9.0), (11.0, 20.0)])
    assert [r.kind for r in regions] == [SegmentKind.SPEECH, SegmentKind.SPEECH]


def test_trailing_music_is_captured() -> None:
    audio = _with_tone(_audio(30.0), 10.0, 30.0)
    regions = classify_regions(audio, [(0.0, 10.0)])
    assert regions[-1].kind == SegmentKind.MUSIC
    assert round(regions[-1].end) == 30


def test_rms_energy_of_silence_is_zero() -> None:
    assert rms_energy(_audio(5.0)) == 0.0
    assert rms_energy(np.array([], dtype=np.float32)) == 0.0


def _stream() -> Stream:
    return Stream(
        id=7,
        channel_id=3,
        started_at=datetime(2026, 7, 11, 20, 0, tzinfo=UTC),
    )


def test_music_region_is_stored_without_text_and_never_transcribed() -> None:
    db = Mock()
    transcriber = Mock()

    added, heard = _persist_region(
        db,
        _stream(),
        transcriber,
        _audio(30.0),
        Region(10.0, 20.0, SegmentKind.MUSIC),
        600.0,
    )

    assert added == 1
    assert heard is None
    transcriber.transcribe.assert_not_called()
    segment = db.add.call_args[0][0]
    assert segment.kind == SegmentKind.MUSIC
    assert segment.text is None
    # absolute timestamps: stream start + file offset (600s) + region start
    assert segment.started_at == datetime(2026, 7, 11, 20, 10, 10, tzinfo=UTC)


def test_speech_region_uses_transcriber_with_absolute_times() -> None:
    db = Mock()
    transcriber = Mock()
    transcriber.transcribe.return_value = Transcription(
        language="pt",
        segments=[(0.5, 2.5, "olá pessoal"), (3.0, 5.0, "bem-vindos")],
    )

    added, heard = _persist_region(
        db,
        _stream(),
        transcriber,
        _audio(30.0),
        Region(10.0, 20.0, SegmentKind.SPEECH),
        0.0,
    )

    assert added == 2
    # nothing is told to the model, and what it heard comes back out: that is
    # what the channel's chat lexicon is later chosen with
    assert heard == "pt"
    assert transcriber.transcribe.call_args[0][1:] == ()
    first = db.add.call_args_list[0][0][0]
    assert first.text == "olá pessoal"
    assert first.kind == SegmentKind.SPEECH
    base = datetime(2026, 7, 11, 20, 0, tzinfo=UTC)
    assert first.started_at == base + timedelta(seconds=10.5)
    assert first.ended_at == base + timedelta(seconds=12.5)


def test_first_detection_names_the_spoken_language(db) -> None:
    """Whisper reports per chunk and a noisy chunk can come back as another
    language. Letting every chunk rewrite the channel would flip the chat
    lexicon between lives, so only the first answer is kept."""
    channel = Channel(twitch_user_id=1, login="sim", display_name="Sim", language="en")
    db.add(channel)
    db.flush()

    _remember_spoken_language(db, channel.id, "pt")
    assert channel.spoken_language == "pt"

    _remember_spoken_language(db, channel.id, "en")
    assert channel.spoken_language == "pt"


def test_a_chunk_with_no_speech_leaves_the_language_alone(db) -> None:
    channel = Channel(twitch_user_id=2, login="sim2", display_name="Sim", language="en")
    db.add(channel)
    db.flush()

    _remember_spoken_language(db, channel.id, None)

    assert channel.spoken_language is None


def test_a_declared_language_is_never_overwritten(db, caplog) -> None:
    """The streamer said what they speak on the way in. Whisper hearing
    otherwise on one noisy chunk is not grounds to overrule them, but it is
    worth saying out loud."""
    channel = Channel(
        twitch_user_id=3,
        login="sim3",
        display_name="Sim",
        language="en",
        spoken_language="pt",
    )
    db.add(channel)
    db.flush()

    with caplog.at_level(logging.WARNING):
        _remember_spoken_language(db, channel.id, "en")

    assert channel.spoken_language == "pt"
    assert "disagrees" in caplog.text
