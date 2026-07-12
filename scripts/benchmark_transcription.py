"""Measures transcription speed against real time for the configured model.

    uv run python scripts/benchmark_transcription.py --audio data/sim/file.wav

Reports decode/VAD/whisper wall times and the x-realtime factor: how many
seconds of audio are processed per wall-clock second. A 4h live needs
x-realtime > 4h / (time until next live) to meet the queue deadline.
"""

import argparse
import time
from pathlib import Path

from core.config import get_settings
from workers.transcribe.pipeline import (
    SAMPLE_RATE,
    Transcriber,
    classify_regions,
    detect_speech_spans,
    rms_energy,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()

    from faster_whisper.audio import decode_audio

    settings = get_settings()
    print(
        f"model={settings.whisper_model} compute_type={settings.whisper_compute_type}"
    )

    started = time.perf_counter()
    audio = decode_audio(str(args.audio), sampling_rate=SAMPLE_RATE)
    decode_seconds = time.perf_counter() - started
    audio_seconds = len(audio) / SAMPLE_RATE
    print(
        f"audio: {audio_seconds:.1f}s | rms={rms_energy(audio):.4f} | decode {decode_seconds:.1f}s"
    )

    started = time.perf_counter()
    spans = detect_speech_spans(audio)
    vad_seconds = time.perf_counter() - started
    regions = classify_regions(audio, spans)
    by_kind: dict[str, float] = {}
    for region in regions:
        by_kind[region.kind.value] = (
            by_kind.get(region.kind.value, 0.0) + region.end - region.start
        )
    print(
        f"vad: {vad_seconds:.1f}s | regions: { {k: round(v, 1) for k, v in by_kind.items()} }"
    )

    transcriber = Transcriber()
    started = time.perf_counter()
    total_speech = 0.0
    total_segments = 0
    for region in regions:
        if region.kind.value != "speech":
            continue
        chunk = audio[int(region.start * SAMPLE_RATE) : int(region.end * SAMPLE_RATE)]
        total_segments += len(transcriber.transcribe(chunk))
        total_speech += region.end - region.start
    whisper_seconds = time.perf_counter() - started

    wall = decode_seconds + vad_seconds + whisper_seconds
    print(
        f"whisper: {whisper_seconds:.1f}s for {total_speech:.1f}s of speech "
        f"({total_segments} segments)"
    )
    print(
        f"TOTAL: {wall:.1f}s wall for {audio_seconds:.1f}s of audio "
        f"-> {audio_seconds / wall:.2f}x realtime"
    )


if __name__ == "__main__":
    main()
