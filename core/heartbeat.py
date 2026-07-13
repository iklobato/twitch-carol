"""Worker liveness heartbeat. Each worker refreshes a TTL'd Valkey key from a
background thread, so a worker busy on a long job still reports alive (a
between-jobs beat would expire mid-transcription). redis_exporter --check-keys
exposes the keys and the monitoring box alerts when one stops refreshing.
"""

import logging
import threading
import time

import redis

from core.queues import get_valkey

logger = logging.getLogger(__name__)

TTL_SECONDS = 120
INTERVAL_SECONDS = 30
KEY_PREFIX = "worker:heartbeat:"


def start_heartbeat(worker: str) -> None:
    key = f"{KEY_PREFIX}{worker}"

    def _beat() -> None:
        valkey = get_valkey()
        while True:
            try:
                valkey.set(key, int(time.time()), ex=TTL_SECONDS)
            except redis.RedisError:
                # Transient Valkey blip: keep the thread alive so the heartbeat
                # resumes; a real outage lets the key expire and fires the alert.
                logger.warning("heartbeat write failed for %s", worker, exc_info=True)
            time.sleep(INTERVAL_SECONDS)

    threading.Thread(target=_beat, name=f"heartbeat-{worker}", daemon=True).start()
