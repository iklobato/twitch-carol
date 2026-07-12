"""Database backup: pg_dump -> gzip -> Spaces (backups/ prefix, 30d
lifecycle) or the local data dir when Spaces is not configured.

Run inside worker-capture (it ships pg_dump/boto3 AND mounts /data,
which the api container does not):
    docker compose exec -T worker-capture python scripts/backup_db.py

Cron example (daily 09:00 UTC, on the droplet):
    0 9 * * * cd /opt/stream-intel/deploy && docker compose \
        -f docker-compose.yml -f docker-compose.prod.yml \
        exec -T worker-capture python scripts/backup_db.py \
        >> /var/log/stream-intel-backup.log 2>&1
"""

import gzip
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.storage import BACKUP_PREFIX, SpacesAudioStorage

LOCAL_BACKUP_KEEP = 7


def dump_database(destination: Path) -> None:
    settings = get_settings()
    # pg_dump takes a libpq URL; strip the SQLAlchemy driver suffix
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with gzip.open(destination, "wb") as compressed:
        process = subprocess.Popen(
            ["pg_dump", "--no-owner", "--no-privileges", url],
            stdout=subprocess.PIPE,
        )
        assert process.stdout is not None
        shutil.copyfileobj(process.stdout, compressed)
        if process.wait() != 0:
            raise RuntimeError(f"pg_dump exited with {process.returncode}")


def store(dump_path: Path, filename: str) -> str:
    settings = get_settings()
    if settings.spaces_key and settings.spaces_bucket:
        storage = SpacesAudioStorage(settings)
        storage.ensure_lifecycle_rule()
        key = f"{BACKUP_PREFIX}{filename}"
        storage.save_file(key, dump_path)
        return f"spaces://{settings.spaces_bucket}/{key}"

    local_dir = Path(settings.audio_local_dir).parent / "backups"
    local_dir.mkdir(parents=True, exist_ok=True)
    target = local_dir / filename
    shutil.copyfile(dump_path, target)
    _prune_local(local_dir)
    return str(target)


def _prune_local(local_dir: Path) -> None:
    backups = sorted(local_dir.glob("*.sql.gz"))
    for stale in backups[:-LOCAL_BACKUP_KEEP]:
        stale.unlink()


def main() -> None:
    filename = f"stream-intel-{datetime.now(UTC):%Y%m%d-%H%M%S}.sql.gz"
    with tempfile.NamedTemporaryFile(suffix=".sql.gz") as handle:
        dump_path = Path(handle.name)
        dump_database(dump_path)
        location = store(dump_path, filename)
        size_mb = dump_path.stat().st_size / (1024 * 1024)
    print(f"backup ok: {location} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
