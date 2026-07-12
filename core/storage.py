"""Audio storage: DigitalOcean Spaces (S3-compatible) or a local directory
when Spaces is not configured (dev/simulation)."""

import logging
import shutil
from pathlib import Path
from typing import Protocol

import boto3

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

AUDIO_RETENTION_DAYS = 7
AUDIO_PREFIX = "audio/"
LIFECYCLE_RULE_ID = f"expire-audio-{AUDIO_RETENTION_DAYS}d"


class AudioStorage(Protocol):
    def save_file(self, key: str, local_path: Path) -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def fetch_file(self, key: str, destination: Path) -> None: ...


class LocalAudioStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def save_file(self, key: str, local_path: Path) -> None:
        target = self._base_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)

    def list_keys(self, prefix: str) -> list[str]:
        root = self._base_dir / prefix
        if not root.is_dir():
            return []
        return sorted(
            str(p.relative_to(self._base_dir)) for p in root.rglob("*") if p.is_file()
        )

    def fetch_file(self, key: str, destination: Path) -> None:
        shutil.copyfile(self._base_dir / key, destination)


class SpacesAudioStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.spaces_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.spaces_endpoint,
            region_name=settings.spaces_region,
            aws_access_key_id=settings.spaces_key,
            aws_secret_access_key=settings.spaces_secret,
        )

    def save_file(self, key: str, local_path: Path) -> None:
        self._client.upload_file(str(local_path), self._bucket, key)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def fetch_file(self, key: str, destination: Path) -> None:
        self._client.download_file(self._bucket, key, str(destination))

    def ensure_lifecycle_rule(self) -> None:
        """Idempotent: audio objects expire after AUDIO_RETENTION_DAYS."""
        self._client.put_bucket_lifecycle_configuration(
            Bucket=self._bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": LIFECYCLE_RULE_ID,
                        "Status": "Enabled",
                        "Filter": {"Prefix": AUDIO_PREFIX},
                        "Expiration": {"Days": AUDIO_RETENTION_DAYS},
                    }
                ]
            },
        )


def audio_key(channel_id: int, stream_id: int, sequence: int) -> str:
    return f"{AUDIO_PREFIX}{channel_id}/{stream_id}/{sequence:03d}.ogg"


def get_audio_storage() -> AudioStorage:
    settings = get_settings()
    if settings.spaces_key and settings.spaces_bucket:
        storage = SpacesAudioStorage(settings)
        storage.ensure_lifecycle_rule()
        return storage
    logger.info("spaces not configured, using local audio storage")
    return LocalAudioStorage(Path(settings.audio_local_dir))
