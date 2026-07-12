"""Local audio storage roundtrip and key layout."""

from pathlib import Path

from core.storage import LocalAudioStorage, audio_key


def test_audio_key_layout() -> None:
    assert audio_key(3, 42, 7) == "audio/3/42/007.ogg"


def test_local_storage_save_list_fetch_roundtrip(tmp_path: Path) -> None:
    storage = LocalAudioStorage(tmp_path / "store")
    source = tmp_path / "segment.ogg"
    source.write_bytes(b"opus-bytes")

    storage.save_file(audio_key(1, 2, 0), source)
    storage.save_file(audio_key(1, 2, 1), source)
    storage.save_file(audio_key(1, 99, 0), source)

    keys = storage.list_keys("audio/1/2/")
    assert keys == ["audio/1/2/000.ogg", "audio/1/2/001.ogg"]

    destination = tmp_path / "fetched.ogg"
    storage.fetch_file(keys[0], destination)
    assert destination.read_bytes() == b"opus-bytes"


def test_local_storage_list_missing_prefix_is_empty(tmp_path: Path) -> None:
    storage = LocalAudioStorage(tmp_path / "store")
    assert storage.list_keys("audio/9/9/") == []
