import time
from unittest.mock import MagicMock, patch

import redis

import core.heartbeat as hb


def test_start_heartbeat_writes_key_with_ttl():
    fake = MagicMock()
    with patch.object(hb, "get_valkey", return_value=fake):
        hb.start_heartbeat("analyze")
        time.sleep(0.1)  # first beat fires before the interval sleep
    fake.set.assert_called()
    args, kwargs = fake.set.call_args
    assert args[0] == "worker:heartbeat:analyze"
    assert kwargs["ex"] == hb.TTL_SECONDS


def test_heartbeat_survives_valkey_error():
    fake = MagicMock()
    fake.set.side_effect = redis.RedisError("down")
    with patch.object(hb, "get_valkey", return_value=fake):
        # A transient error must not kill the daemon thread.
        hb.start_heartbeat("capture")
        time.sleep(0.1)
    fake.set.assert_called()
