"""BlueZTransport against the fake org.bluez on a private dbus-daemon."""
import time

import pytest

from fake_bluez import FakeBlueZ, available as dbus_daemon_available
from ptouch import TransportError, _bluez_common as common
from ptouch.bluez import BlueZTransport

pytestmark = pytest.mark.skipif(not dbus_daemon_available(), reason="dbus-daemon not installed")

A = "AA:BB:CC:00:00:01"
ERR = lambda text, name="org.bluez.Error.Failed": ("error", name, text)  # noqa: E731


@pytest.fixture
def fake():
    f = FakeBlueZ().start()
    yield f
    f.stop()


def transport(fake, wake=None):
    t = BlueZTransport(A, bus_address=fake.address)
    if wake is not None:
        t.wake_timeout = wake
    return t


def test_terror_backward_compatible():
    e = TransportError("plain")
    assert str(e) == "plain" and e.reason == "error"
    e = TransportError("x", reason="asleep")
    assert str(e) == "x" and e.reason == "asleep"


def test_returns_rfcomm_socket(fake):
    st = fake.add_device(A, "PT-P710BT", paired=True)
    t = transport(fake)
    t._open()
    try:
        assert t._sock is not None
        t._sock.sendall(b"hello")
        assert st.peers[0].recv(10) == b"hello"
        st.peers[0].sendall(b"back")
        t._sock.settimeout(2)
        assert t._sock.recv(10) == b"back"
    finally:
        t._close()
    assert fake.profile is None and t._sock is None


def test_profile_taken_falls_back_to_socket(fake, monkeypatch):
    from ptouch.transport import RFCOMMTransport
    fake.add_device(A, "PT-P300BT", paired=True)
    fake.profile_taken = True
    opened = []
    monkeypatch.setattr(RFCOMMTransport, "_open", lambda self: opened.append((self._address, self._channel)))
    t = BlueZTransport(A, bus_address=fake.address, channel=3)
    t._open()
    assert opened == [(A, 3)] and t._loop is None and fake.profile is None


def test_make_transport_passes_channel():
    from ptouch import make_transport
    assert make_transport("bluetooth", address=A, channel=3, backend="dbus")._channel == 3


def test_not_paired_reason(fake):
    t = transport(fake)
    with pytest.raises(TransportError) as e:
        t._open()
    assert e.value.reason == "not_paired" and "paired" in str(e.value)


def test_no_dbus_reason():
    t = BlueZTransport(A, bus_address="unix:path=/nonexistent/bus")
    with pytest.raises(TransportError) as e:
        t._open()
    assert e.value.reason == "no_dbus"


@pytest.mark.parametrize("text,name,reason", [
    ("br-connection-page-timeout", "org.bluez.Error.Failed", "asleep"),
    ("host-down", "org.bluez.Error.Failed", "asleep"),
    ("br-connection-busy", "org.bluez.Error.Failed", "busy"),
    ("x", "org.bluez.Error.InProgress", "busy"),
    ("x", "org.bluez.Error.AuthenticationFailed", "not_paired"),
    ("x", "org.bluez.Error.NotReady", "bluetooth_off"),
    ("Input/output error", "org.bluez.Error.Failed", "error"),
])
def test_reason_mapping_and_plain_messages(fake, text, name, reason):
    fake.add_device(A, "PT-P710BT", paired=True, connect=(ERR(text, name),))
    t = transport(fake, wake=0.8)
    with pytest.raises(TransportError) as e:
        t._open()
    assert e.value.reason == reason
    msg = str(e.value)
    assert msg and "org.bluez" not in msg and "br-connection" not in msg and "host-down" not in msg
    assert fake.profile is None


def test_wake_timeout_bounds_retry_loop(fake):
    st = fake.add_device(A, "PT-P710BT", paired=True, connect=(ERR("br-connection-page-timeout"),))
    t = transport(fake, wake=1.6)
    t0 = time.monotonic()
    with pytest.raises(TransportError) as e:
        t._open()
    took = time.monotonic() - t0
    assert e.value.reason == "asleep"
    # retries happened (0.75 s, 1.5 s back-offs) but stopped by the deadline
    assert 2 <= len(st.connect_times) <= 3
    assert 1.5 <= took < 3.2
    assert st.connect_times[-1] - st.connect_times[0] <= 1.7


def test_wake_timeout_default_is_12_and_zero_means_single_attempt(fake, monkeypatch):
    assert common.DEFAULT_WAKE_TIMEOUT == 12.0
    st = fake.add_device(A, "PT-P710BT", paired=True, connect=(ERR("br-connection-page-timeout"),))
    t = transport(fake, wake=0)
    t0 = time.monotonic()
    with pytest.raises(TransportError):
        t._open()
    assert len(st.connect_times) == 1 and time.monotonic() - t0 < 2


def test_wake_timeout_hang_is_bounded(fake, monkeypatch):
    monkeypatch.setattr(common, "MIN_ATTEMPT", 0.1)
    fake.add_device(A, "PT-P710BT", paired=True, connect=("hang",))
    t = transport(fake, wake=1.0)
    t0 = time.monotonic()
    with pytest.raises(TransportError) as e:
        t._open()
    assert e.value.reason == "asleep" and 0.9 < time.monotonic() - t0 < 3


def test_retry_then_success_with_wake_timeout(fake):
    st = fake.add_device(A, "PT-P710BT", paired=True, connect=(ERR("br-connection-busy"), "ok"))
    t = transport(fake, wake=5)
    t._open()
    try:
        assert t._sock is not None and len(st.connect_times) == 2
    finally:
        t._close()


def test_get_status_end_to_end(fake):
    """Whole StreamTransport path (status request) over the fake RFCOMM socketpair."""
    import threading
    from test_core import status_bytes
    st = fake.add_device(A, "PT-P710BT", paired=True)
    t = transport(fake)

    def printer():
        while not st.peers:
            time.sleep(0.01)
        p = st.peers[0]
        p.settimeout(3)
        p.recv(64)
        p.sendall(status_bytes(width=12))
    threading.Thread(target=printer, daemon=True).start()
    status = t.get_status()
    assert status.media_width == 12
