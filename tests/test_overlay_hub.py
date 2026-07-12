from __future__ import annotations

from alerts import AlertKind, StreamAlert


def make_alert() -> StreamAlert:
    return StreamAlert(kind=AlertKind.GIFT, headline="h", detail="d")


async def test_connect_accepts_and_registers(hub, fake_socket_factory):
    socket = fake_socket_factory()
    await hub.connect(socket)
    assert socket.accepted is True
    assert socket in hub._connections


async def test_disconnect_removes_and_is_idempotent(hub, fake_socket_factory):
    socket = fake_socket_factory()
    await hub.connect(socket)
    hub.disconnect(socket)
    assert socket not in hub._connections
    hub.disconnect(socket)  # must not raise


async def test_broadcast_sends_payload_dict_to_all(hub, fake_socket_factory):
    sockets = [fake_socket_factory(), fake_socket_factory()]
    for socket in sockets:
        await hub.connect(socket)
    alert = make_alert()
    await hub.broadcast(alert)
    for socket in sockets:
        assert socket.sent == [alert.to_payload()]


async def test_broadcast_with_no_connections_is_noop(hub):
    await hub.broadcast(make_alert())


async def test_dead_socket_removed_and_survivors_receive(
    hub, fake_socket_factory, dead_socket_error
):
    dead = fake_socket_factory(fail_with=dead_socket_error)
    alive = fake_socket_factory()
    await hub.connect(dead)
    await hub.connect(alive)
    await hub.broadcast(make_alert())
    assert dead not in hub._connections
    assert alive in hub._connections
    assert len(alive.sent) == 1


async def test_runtime_error_socket_removed(hub, fake_socket_factory):
    dead = fake_socket_factory(fail_with=RuntimeError("send after close"))
    alive = fake_socket_factory()
    await hub.connect(dead)
    await hub.connect(alive)
    await hub.broadcast(make_alert())
    assert dead not in hub._connections
    assert len(alive.sent) == 1


async def test_unexpected_error_does_not_abort_broadcast(hub, fake_socket_factory):
    exploding = fake_socket_factory(fail_with=ValueError("boom"))
    alive = fake_socket_factory()
    await hub.connect(exploding)
    await hub.connect(alive)
    await hub.broadcast(make_alert())
    assert exploding not in hub._connections
    assert len(alive.sent) == 1
