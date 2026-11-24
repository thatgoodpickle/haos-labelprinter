"""A fake ``org.bluez`` on a PRIVATE dbus-daemon, for tests only.

Never touches the real system bus or radio: ``FakeBlueZ.start()`` spawns its own
``dbus-daemon --session`` and exports Adapter1/Device1/AgentManager1/ProfileManager1
objects with dbus-fast. Tests pass ``fake.address`` as ``bus_address``.
"""
import asyncio
import os
import socket
import subprocess
import threading
import time

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError
from dbus_fast.service import PropertyAccess, ServiceInterface, dbus_property, method

ADAPTER_PATH = "/org/bluez/hci0"


def dev_path(address, adapter=ADAPTER_PATH):
    return f"{adapter}/dev_{address.replace(':', '_')}"


class Dev:
    """Mutable state and behaviour of one fake remote device."""

    def __init__(self, address, name="", *, paired=False, trusted=False, rssi=None, alias=None,
                 visible=True, pair_mode="ok", pair_flow="just_works", pin="0000", connect=("ok",),
                 pair_delay=0.0):
        self.address, self.name, self.alias = address, name, alias
        self.paired, self.trusted, self.connected = paired, trusted, False
        self.rssi = rssi
        self.visible = visible          # False: only appears once discovery starts
        self.pair_mode = pair_mode      # "ok" | ("error", name, text) | "hang"
        self.pair_flow = pair_flow      # just_works | pin | passkey | confirm | authorize | service
        self.pin = pin
        self.pair_delay = pair_delay
        self.connect = list(connect)    # per attempt: "ok" | ("error", name, text) | "hang"; last repeats
        self.connect_times = []
        self.pair_calls = 0
        self.disconnects = 0
        self.peers = []                 # printer-side ends of the RFCOMM socketpairs
        self.agent_results = []
        self.iface = None
        self.exported = False


class DeviceBase(ServiceInterface):
    def __init__(self, fake, st):
        super().__init__("org.bluez.Device1")
        self.fake, self.st = fake, st

    @dbus_property(access=PropertyAccess.READ)
    def Address(self) -> "s":  # noqa: N802,F821
        return self.st.address

    @dbus_property(access=PropertyAccess.READ)
    def Name(self) -> "s":  # noqa: N802,F821
        return self.st.name

    @dbus_property(access=PropertyAccess.READ)
    def Alias(self) -> "s":  # noqa: N802,F821
        return self.st.alias or self.st.name or self.st.address.replace(":", "-")

    @dbus_property(access=PropertyAccess.READ)
    def Paired(self) -> "b":  # noqa: N802,F821
        return self.st.paired

    @dbus_property()
    def Trusted(self) -> "b":  # noqa: N802,F821
        return self.st.trusted

    @Trusted.setter
    def Trusted(self, v: "b"):  # noqa: N802,F821
        self.st.trusted = v

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> "b":  # noqa: N802,F821
        return self.st.connected

    @dbus_property(access=PropertyAccess.READ)
    def Adapter(self) -> "o":  # noqa: N802,F821
        return ADAPTER_PATH

    @method()
    async def Pair(self):  # noqa: N802
        await self.fake._pair(self.st)

    @method()
    def CancelPairing(self):  # noqa: N802
        self.fake.calls.append(("CancelPairing", self.st.address))

    @method()
    async def ConnectProfile(self, uuid: "s"):  # noqa: N802,F821
        await self.fake._connect_profile(self.st, uuid)

    @method()
    def Disconnect(self):  # noqa: N802
        self.st.disconnects += 1
        self.st.connected = False
        self.fake.calls.append(("Disconnect", self.st.address))


class DeviceWithRssi(DeviceBase):
    @dbus_property(access=PropertyAccess.READ)
    def RSSI(self) -> "n":  # noqa: N802,F821
        return self.st.rssi


class AdapterIface(ServiceInterface):
    def __init__(self, fake):
        super().__init__("org.bluez.Adapter1")
        self.fake = fake

    @dbus_property(access=PropertyAccess.READ)
    def Address(self) -> "s":  # noqa: N802,F821
        return "00:11:22:33:44:55"

    @dbus_property(access=PropertyAccess.READ)
    def Name(self) -> "s":  # noqa: N802,F821
        return "fakehost"

    @dbus_property(access=PropertyAccess.READ)
    def Alias(self) -> "s":  # noqa: N802,F821
        return "fakehost"

    @dbus_property()
    def Powered(self) -> "b":  # noqa: N802,F821
        return self.fake.powered

    @Powered.setter
    def Powered(self, v: "b"):  # noqa: N802,F821
        self.fake.powered = v
        self.fake.calls.append(("Powered", v))

    @method()
    def SetDiscoveryFilter(self, props: "a{sv}"):  # noqa: N802,F821
        self.fake.discovery_filter = {k: v.value for k, v in props.items()}
        self.fake.calls.append(("SetDiscoveryFilter", self.fake.discovery_filter))

    @method()
    async def StartDiscovery(self):  # noqa: N802
        self.fake.calls.append(("StartDiscovery",))
        if not self.fake.powered:
            raise DBusError("org.bluez.Error.NotReady", "Resource Not Ready")
        if self.fake.discovering:
            raise DBusError("org.bluez.Error.InProgress", "Operation already in progress")
        self.fake.discovering = True
        for st in list(self.fake.devs.values()):
            if not st.exported:
                await self.fake._export_dev(st)

    @method()
    def StopDiscovery(self):  # noqa: N802
        self.fake.calls.append(("StopDiscovery",))
        self.fake.discovering = False

    @method()
    def RemoveDevice(self, device: "o"):  # noqa: N802,F821
        self.fake.calls.append(("RemoveDevice", device))
        for addr, st in list(self.fake.devs.items()):
            if dev_path(addr) == device:
                st.paired = st.trusted = False
                if st.iface is not None:
                    self.fake.bus.unexport(device)
                    st.exported = False
                del self.fake.devs[addr]


class AgentManager(ServiceInterface):
    def __init__(self, fake):
        super().__init__("org.bluez.AgentManager1")
        self.fake = fake

    @method()
    def RegisterAgent(self, agent: "o", capability: "s"):  # noqa: N802,F821
        self.fake.calls.append(("RegisterAgent", capability))
        if self.fake.register_agent_error:
            raise DBusError(*self.fake.register_agent_error)
        self.fake.agent = (self.fake.senders.get("RegisterAgent"), agent, capability)

    @method()
    def UnregisterAgent(self, agent: "o"):  # noqa: N802,F821
        self.fake.calls.append(("UnregisterAgent", agent))
        self.fake.agent = None

    @method()
    def RequestDefaultAgent(self, agent: "o"):  # noqa: N802,F821
        self.fake.calls.append(("RequestDefaultAgent", agent))


class ProfileManager(ServiceInterface):
    def __init__(self, fake):
        super().__init__("org.bluez.ProfileManager1")
        self.fake = fake

    @method()
    def RegisterProfile(self, profile: "o", uuid: "s", options: "a{sv}"):  # noqa: N802,F821
        self.fake.calls.append(("RegisterProfile", uuid))
        if self.fake.profile_taken:
            raise DBusError("org.bluez.Error.NotPermitted", "UUID already registered")
        self.fake.profile = (self.fake.senders.get("RegisterProfile"), profile, uuid)

    @method()
    def UnregisterProfile(self, profile: "o"):  # noqa: N802,F821
        self.fake.calls.append(("UnregisterProfile", profile))
        self.fake.profile = None


class FakeBlueZ:
    def __init__(self, *, powered=True, with_adapter=True):
        self.powered = powered
        self.with_adapter = with_adapter
        self.devs = {}
        self.calls = []
        self.agent = None
        self.profile = None
        self.senders = {}
        self.agent_calls = []
        self.discovering = False
        self.discovery_filter = None
        self.register_agent_error = None
        self.profile_taken = False   # another program holds the SPP profile
        self.address = None
        self.bus = None
        self._daemon = None
        self._loop = None
        self._thread = None

    # -- lifecycle -------------------------------------------------------------
    def start(self):
        self._daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                                        stdout=subprocess.PIPE, text=True)
        self.address = self._daemon.stdout.readline().strip()
        ready = threading.Event()

        def main():
            self._loop = asyncio.new_event_loop()
            self._loop.run_until_complete(self._setup())
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=main, daemon=True)
        self._thread.start()
        assert ready.wait(10), "fake bluez did not start"
        return self

    def stop(self):
        if self._loop is not None:
            async def shutdown():
                for t in asyncio.all_tasks():
                    if t is not asyncio.current_task():
                        t.cancel()
                await asyncio.sleep(0.05)
                self._loop.stop()
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop)
            self._thread.join(5)
        if self._daemon is not None:
            self._daemon.terminate()
            self._daemon.wait(5)

    async def _setup(self):
        self.bus = await MessageBus(bus_address=self.address, negotiate_unix_fd=True).connect()

        def on_msg(msg):
            if msg.message_type == MessageType.METHOD_CALL and msg.member in ("RegisterAgent", "RegisterProfile"):
                self.senders[msg.member] = msg.sender
        self.bus.add_message_handler(on_msg)
        self.bus.export("/org/bluez", AgentManager(self))
        self.bus.export("/org/bluez", ProfileManager(self))
        self.adapter_iface = AdapterIface(self)
        if self.with_adapter:
            self.bus.export(ADAPTER_PATH, self.adapter_iface)
        await self.bus.request_name("org.bluez")

    def _sync(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(10)

    # -- configuration from tests -------------------------------------------------
    def add_device(self, address, name="", **kw):
        st = Dev(address, name, **kw)
        self.devs[address] = st
        if st.visible:
            self._sync(self._export_dev(st))
        return st

    async def _export_dev(self, st):
        st.iface = DeviceWithRssi(self, st) if st.rssi is not None else DeviceBase(self, st)
        self.bus.export(dev_path(st.address), st.iface)
        st.exported = True

    def set_powered(self, value):
        self.powered = value
        self._loop.call_soon_threadsafe(lambda: self.adapter_iface.emit_properties_changed({"Powered": value}))

    # -- behaviour -----------------------------------------------------------------
    async def _agent_call(self, st, member, signature, body):
        sender, path, _cap = self.agent
        reply = await self.bus.call(Message(destination=sender, path=path, interface="org.bluez.Agent1",
                                            member=member, signature=signature, body=body))
        self.agent_calls.append(member)
        if reply.message_type == MessageType.ERROR:
            raise DBusError("org.bluez.Error.AuthenticationRejected", "agent said no")
        return reply.body

    async def _pair(self, st):
        st.pair_calls += 1
        self.calls.append(("Pair", st.address))
        if st.pair_delay:
            await asyncio.sleep(st.pair_delay)
        if st.pair_mode == "hang":
            await asyncio.sleep(3600)
        if isinstance(st.pair_mode, tuple):
            raise DBusError(st.pair_mode[1], st.pair_mode[2])
        if st.paired:
            raise DBusError("org.bluez.Error.AlreadyExists", "Already Exists")
        if self.agent is None:
            raise DBusError("org.bluez.Error.AuthenticationFailed", "no agent")
        path = dev_path(st.address)
        flow = st.pair_flow
        if flow == "pin":
            body = await self._agent_call(st, "RequestPinCode", "o", [path])
            st.agent_results.append(body[0])
            if body[0] != st.pin:
                raise DBusError("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
        elif flow == "passkey":
            body = await self._agent_call(st, "RequestPasskey", "o", [path])
            st.agent_results.append(body[0])
            if body[0] != int(st.pin):
                raise DBusError("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
        elif flow == "confirm":
            await self._agent_call(st, "RequestConfirmation", "ou", [path, 123456])
        elif flow == "authorize":
            await self._agent_call(st, "RequestAuthorization", "o", [path])
        elif flow == "service":
            await self._agent_call(st, "AuthorizeService", "os", [path, "00001101-0000-1000-8000-00805f9b34fb"])
        elif flow == "display":
            await self._agent_call(st, "DisplayPinCode", "os", [path, "123456"])
            await self._agent_call(st, "DisplayPasskey", "ouq", [path, 123456, 0])
            await self._agent_call(st, "Cancel", "", [])
        st.paired = True
        st.iface.emit_properties_changed({"Paired": True})

    async def _connect_profile(self, st, uuid):
        st.connect_times.append(time.monotonic())
        self.calls.append(("ConnectProfile", st.address))
        n = len(st.connect_times) - 1
        action = st.connect[min(n, len(st.connect) - 1)]
        if action == "hang":
            await asyncio.sleep(3600)
        if isinstance(action, tuple):
            raise DBusError(action[1], action[2])
        if self.profile is None:
            raise DBusError("org.bluez.Error.NotAvailable", "no profile")
        sender, path, _u = self.profile
        mine, theirs = socket.socketpair()
        st.peers.append(theirs)
        await self.bus.call(Message(destination=sender, path=path, interface="org.bluez.Profile1",
                                    member="NewConnection", signature="oha{sv}",
                                    body=[dev_path(st.address), 0, {}], unix_fds=[mine.fileno()]))
        mine.close()
        st.connected = True
        st.iface.emit_properties_changed({"Connected": True})


def available():
    from shutil import which
    return which("dbus-daemon") is not None
