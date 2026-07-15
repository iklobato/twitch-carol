"""Local audio storage roundtrip and key layout."""

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from core.config import Settings
from core.storage import LocalAudioStorage, SpacesAudioStorage, audio_key


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


class _FakeLifecycleClient:
    def __init__(self, err_code: str | None) -> None:
        self._err_code = err_code
        self.called = False
        self.config: dict[str, object] | None = None

    def put_bucket_lifecycle_configuration(self, **kwargs) -> None:
        self.called = True
        self.config = kwargs.get("LifecycleConfiguration")
        if self._err_code is not None:
            raise ClientError(
                {"Error": {"Code": self._err_code, "Message": "x"}},
                "PutBucketLifecycleConfiguration",
            )


def _spaces_storage(
    err_code: str | None, retention_days: int = 365
) -> SpacesAudioStorage:
    storage = SpacesAudioStorage(
        Settings(
            spaces_bucket="b",
            spaces_key="k",
            spaces_secret="s",
            spaces_endpoint="https://e",
            spaces_region="r",
            audio_retention_days=retention_days,
        )
    )
    storage._client = _FakeLifecycleClient(err_code)
    return storage


def test_ensure_lifecycle_uses_configured_audio_retention() -> None:
    storage = _spaces_storage(None, retention_days=90)
    storage.ensure_lifecycle_rule()

    config = storage._client.config
    assert config is not None
    audio_rule = config["Rules"][0]
    assert audio_rule["Filter"]["Prefix"] == "audio/"
    assert audio_rule["Expiration"]["Days"] == 90
    assert audio_rule["ID"] == "expire-audio-90d"


def test_ensure_lifecycle_swallows_access_denied() -> None:
    storage = _spaces_storage("AccessDenied")
    storage.ensure_lifecycle_rule()  # scoped app key: expected, must not raise
    assert storage._client.called


def test_ensure_lifecycle_reraises_other_errors() -> None:
    storage = _spaces_storage("InternalError")
    with pytest.raises(ClientError):
        storage.ensure_lifecycle_rule()
