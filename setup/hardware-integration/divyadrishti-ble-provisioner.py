#!/usr/bin/env python3
"""Offline first-time Wi-Fi provisioning over Bluetooth Low Energy.

Runs a BlueZ GATT peripheral that a paired phone connects to on the very first
setup, with no Wi-Fi, router, or internet present. The phone writes the chosen
home Wi-Fi (or phone-hotspot) credentials, and the Pi joins that network.

Design notes:
  * Uses BlueZ over D-Bus via python3-dbus + python3-gi only. Both ship with
    Raspberry Pi OS, so there is nothing to pip-install on an offline Pi.
  * The credential payload is written in small MTU-safe chunks (works even at
    the 23-byte default MTU) and assembled here, then a single commit write
    triggers the join.
  * SECURITY: characteristics are open (no BLE bonding/encryption). A shared
    pairing code gates writes, but the link itself is sniffable. This is
    acceptable for a private prototype only. A public product must bond and
    require encrypted characteristics.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

# Custom 128-bit UUIDs for the provisioning service. Keep these in sync with
# src/services/bleProvisioning.js on the app side.
SERVICE_UUID = "5f3e0001-2a11-4b0e-9c3a-1f2e3d4c5b6a"
RX_CHRC_UUID = "5f3e0002-2a11-4b0e-9c3a-1f2e3d4c5b6a"  # write: credential chunks
COMMIT_CHRC_UUID = "5f3e0003-2a11-4b0e-9c3a-1f2e3d4c5b6a"  # write: begin join
STATUS_CHRC_UUID = "5f3e0004-2a11-4b0e-9c3a-1f2e3d4c5b6a"  # read/notify: state
PAIRING_CODE_CHRC_UUID = "5f3e0005-2a11-4b0e-9c3a-1f2e3d4c5b6a"  # read: device claim code

PAIRING_CODE = os.environ.get("DIVYADRISHTI_PAIRING_CODE", "").upper()
# Unrelated to PAIRING_CODE above (which only gates Wi-Fi credential writes,
# a manufacturing-time secret): this is the device's own Supabase claim
# code, written by divya_drishti_final.py's register_device_if_needed(). The
# Pi has no speaker, so this characteristic is how the phone learns it.
DEVICE_FILE = Path.home() / ".divyadrishti" / "device.json"


def _read_claim_code() -> str:
    try:
        return json.loads(DEVICE_FILE.read_text()).get("pairing_code", "").upper()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
HOSTAPD_CONFIG = "/etc/hostapd/hostapd.conf"
MAX_PAYLOAD_BYTES = 512  # generous cap for a small JSON credential blob
# If GATT/advert registration does not produce ActiveInstances>=1 within this
# window, exit non-zero so systemd restarts us instead of hanging forever.
REGISTER_TIMEOUT_SEC = 30


def _log(message: str) -> None:
    # Always print so systemd's journal can capture it; also append to a file
    # because journal association for this unit has been unreliable on the Pi
    # under heavy load.
    print(message, flush=True)
    try:
        with open("/var/log/divyadrishti-ble.log", "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass
    subprocess.run(("logger", "-t", "divyadrishti-ble", message), check=False)


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class FailedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.Failed"


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


# --------------------------------------------------------------------------- #
# GATT application / service / characteristic scaffolding (BlueZ D-Bus API)    #
# --------------------------------------------------------------------------- #
class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/com/divyadrishti/ble"
        self.services = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.characteristics:
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = "/com/divyadrishti/ble/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = f"{self.PATH_BASE}{index}"
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, chrc):
        self.characteristics.append(chrc)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    [c.get_path() for c in self.characteristics], signature="o"
                ),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = f"{service.path}/char{index}"
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.notifying = False
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    # Default no-op handlers; overridden where relevant.
    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        raise NotPermittedException()

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        raise NotPermittedException()

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False


# --------------------------------------------------------------------------- #
# Provisioning characteristics                                                 #
# --------------------------------------------------------------------------- #
class ProvisioningState:
    """Shared credential buffer and connection status across characteristics."""

    def __init__(self):
        self.buffer = bytearray()
        self.status = "idle"
        self.busy = False
        self.status_chrc = None  # set once StatusCharacteristic is built

    def reset_buffer(self):
        self.buffer = bytearray()

    def set_status(self, status: str):
        self.status = status
        if self.status_chrc is not None:
            self.status_chrc.push(status)


class RxCharacteristic(Characteristic):
    """Accumulates the credential JSON in MTU-safe chunks."""

    def __init__(self, bus, index, service, state):
        super().__init__(bus, index, RX_CHRC_UUID, ["write", "write-without-response"], service)
        self.state = state

    def WriteValue(self, value, options):
        if self.state.busy:
            raise NotPermittedException()
        # A fresh session starts whenever the buffer was cleared after a commit.
        if len(self.state.buffer) + len(value) > MAX_PAYLOAD_BYTES:
            self.state.reset_buffer()
            raise FailedException()
        self.state.buffer.extend(bytes(value))


class CommitCharacteristic(Characteristic):
    """A single write validates the buffered JSON and starts the Wi-Fi join."""

    def __init__(self, bus, index, service, state):
        super().__init__(bus, index, COMMIT_CHRC_UUID, ["write"], service)
        self.state = state

    def WriteValue(self, value, options):
        if self.state.busy:
            raise NotPermittedException()
        raw = bytes(self.state.buffer)
        self.state.reset_buffer()
        try:
            data = json.loads(raw.decode("utf-8"))
            code = str(data.get("code", "")).upper()
            ssid = str(data["ssid"]).strip()
            password = str(data["password"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.state.set_status("error:bad-request")
            raise FailedException()

        if not PAIRING_CODE or code != PAIRING_CODE:
            self.state.set_status("error:pairing")
            raise NotPermittedException()
        if not 1 <= len(ssid.encode()) <= 32 or any(ord(c) < 32 for c in ssid):
            self.state.set_status("error:ssid")
            raise FailedException()
        if not 8 <= len(password) <= 63:
            self.state.set_status("error:password")
            raise FailedException()

        self.state.busy = True
        self.state.set_status("connecting")
        threading.Thread(
            target=_join_wifi, args=(self.state, ssid, password), daemon=True
        ).start()


class StatusCharacteristic(Characteristic):
    """Read + notify the current provisioning state string."""

    def __init__(self, bus, index, service, state):
        super().__init__(bus, index, STATUS_CHRC_UUID, ["read", "notify"], service)
        self.state = state
        state.status_chrc = self

    def ReadValue(self, options):
        return [dbus.Byte(b) for b in self.state.status.encode("utf-8")]

    def push(self, status: str):
        if not self.notifying:
            return
        value = [dbus.Byte(b) for b in status.encode("utf-8")]
        self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": dbus.Array(value, signature="y")}, [])


class PairingCodeCharacteristic(Characteristic):
    """Read-only: the device's Supabase claim code (empty until
    divya_drishti_final.py has registered once). Same trust level as
    StatusCharacteristic above — no separate gate, matching this file's
    documented "private prototype only" security posture."""

    def __init__(self, bus, index, service):
        super().__init__(bus, index, PAIRING_CODE_CHRC_UUID, ["read"], service)

    def ReadValue(self, options):
        return [dbus.Byte(b) for b in _read_claim_code().encode("utf-8")]


def _join_wifi(state: ProvisioningState, ssid: str, password: str) -> None:
    """Persist and bring up the chosen network, then report status via notify.

    Mirrors the nmcli flow used by the HTTP provisioner so both transports save
    the profile before tearing down any active setup hotspot.
    """
    def run(*command: str) -> None:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        profile = f"DivyaDrishti-{ssid}"[:64]
        subprocess.run(("nmcli", "connection", "delete", profile), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run(
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", profile, "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password,
            "connection.autoconnect", "yes",
        )
        # Tear down any concurrent setup hotspot (present only when the AP
        # fallback is also running); harmless no-ops in BLE-only mode.
        subprocess.run(("pkill", "-TERM", "-f", f"/usr/sbin/hostapd {HOSTAPD_CONFIG}"), check=False)
        subprocess.run(("systemctl", "stop", "dnsmasq"), check=False)
        subprocess.run(("ip", "addr", "flush", "dev", "wlan0"), check=False)
        run("nmcli", "device", "set", "wlan0", "managed", "yes")
        run("nmcli", "connection", "up", profile)
        GLib.idle_add(state.set_status, "connected")
        _log(f"joined Wi-Fi network via BLE provisioning: {profile}")
    except subprocess.CalledProcessError:
        GLib.idle_add(state.set_status, "error:join-failed")
        _log("BLE provisioning could not join the requested Wi-Fi network")
    finally:
        state.busy = False


# --------------------------------------------------------------------------- #
# LE advertisement                                                             #
# --------------------------------------------------------------------------- #
# The helper sends the legacy MGMT Add Advertising command directly. GATT stays
# registered through BlueZ D-Bus below; the two registrations are independent.
ADVERT_HELPER = "/usr/local/sbin/divyadrishti-adv-helper"
ADVERT_STOP_TIMEOUT_SEC = 10
_advert_process: subprocess.Popen | None = None


def start_advertising_via_helper() -> None:
    """Start the native legacy-MGMT helper and fail if it exits immediately."""
    global _advert_process
    if _advert_process is not None and _advert_process.poll() is None:
        _log("legacy advertisement helper already running")
        return

    _advert_process = subprocess.Popen(
        (ADVERT_HELPER, "add"),
    )
    time.sleep(0.5)
    exit_code = _advert_process.poll()
    if exit_code is not None:
        _advert_process = None
        raise RuntimeError(f"legacy advertisement helper exited early (status={exit_code})")
    _log("legacy provisioning advertisement helper started (instance=1)")


def stop_advertising_via_helper() -> None:
    """Ask the helper to remove its advertising instance, then wait for exit."""
    global _advert_process
    if _advert_process is None:
        return
    if _advert_process.poll() is None:
        _advert_process.terminate()  # SIGTERM triggers the helper's clean removal.
        try:
            _advert_process.wait(timeout=ADVERT_STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            _log("legacy advertisement helper did not stop within 10 seconds")
            return
    _advert_process = None
    _log("legacy provisioning advertisement helper stopped")


# --------------------------------------------------------------------------- #
# Bring-up                                                                     #
# --------------------------------------------------------------------------- #
def find_adapter(bus):
    remote = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE
    )
    for path, interfaces in remote.GetManagedObjects().items():
        if GATT_MANAGER_IFACE in interfaces and LE_ADVERTISING_MANAGER_IFACE in interfaces:
            return path
    return None


def wait_for_adapter(bus, timeout_sec=30):
    """Poll until BlueZ exposes a GATT + LE-advertising adapter, then power it."""
    deadline = time.monotonic() + timeout_sec
    last_err = "no adapter"
    _log(f"waiting up to {timeout_sec}s for Bluetooth adapter")
    while time.monotonic() < deadline:
        try:
            adapter = find_adapter(bus)
            if adapter is None:
                last_err = "adapter not listed yet"
                time.sleep(0.5)
                continue
            props = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, adapter), DBUS_PROP_IFACE
            )
            props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            supported = int(props.Get(LE_ADVERTISING_MANAGER_IFACE, "SupportedInstances"))
            if supported < 1:
                last_err = f"SupportedInstances={supported}"
                time.sleep(0.5)
                continue
            active = int(props.Get(LE_ADVERTISING_MANAGER_IFACE, "ActiveInstances"))
            _log(f"adapter {adapter} Powered supported={supported} active={active}")
            return adapter, props
        except dbus.exceptions.DBusException as exc:
            last_err = str(exc)
            time.sleep(0.5)
    raise SystemExit(f"Bluetooth adapter not ready: {last_err}")


def main():
    import signal

    _log("divyadrishti-ble-provisioner starting")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter, adapter_props = wait_for_adapter(bus)
    _log(f"adapter ready at {adapter}")

    state = ProvisioningState()

    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, True)
    service.add_characteristic(RxCharacteristic(bus, 0, service, state))
    service.add_characteristic(CommitCharacteristic(bus, 1, service, state))
    service.add_characteristic(StatusCharacteristic(bus, 2, service, state))
    service.add_characteristic(PairingCodeCharacteristic(bus, 3, service))
    app.add_service(service)

    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE
    )

    loop = GLib.MainLoop()
    reg = {"gatt": False, "advert": False, "failure": None, "stopping": False}

    def fail(message: str):
        if reg["stopping"]:
            return
        reg["failure"] = message
        _log(f"BLE registration failed: {message}")
        loop.quit()

    def active_instances() -> int:
        return int(adapter_props.Get(LE_ADVERTISING_MANAGER_IFACE, "ActiveInstances"))

    def start_advert():
        # Run outside the D-Bus reply context so helper startup cannot stall
        # BlueZ callbacks.
        def _do():
            try:
                start_advertising_via_helper()
                reg["advert"] = True
                _log("advertising provisioning UUID through native legacy MGMT helper")
            except Exception as exc:  # noqa: BLE001 - surface any advert failure
                fail(f"advert: {exc}")

        threading.Thread(target=_do, daemon=True).start()

    def on_gatt_ok():
        reg["gatt"] = True
        _log(f"GATT provisioning service registered on {adapter}")
        start_advert()

    def on_watchdog():
        if reg["advert"] or reg["failure"] or reg["stopping"]:
            return False
        try:
            active = active_instances()
        except dbus.exceptions.DBusException:
            active = -1
        fail(
            f"timeout after {REGISTER_TIMEOUT_SEC}s "
            f"(gatt={reg['gatt']} advert={reg['advert']} ActiveInstances={active})"
        )
        return False

    def cleanup(*_args):
        reg["stopping"] = True
        _log("shutting down BLE provisioning peripheral")
        stop_advertising_via_helper()
        try:
            gatt_manager.UnregisterApplication(app.get_path())
        except dbus.exceptions.DBusException:
            pass
        if loop.is_running():
            loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, cleanup)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, cleanup)
    GLib.timeout_add_seconds(REGISTER_TIMEOUT_SEC, on_watchdog)

    gatt_manager.RegisterApplication(
        app.get_path(),
        {},
        reply_handler=on_gatt_ok,
        error_handler=lambda e: fail(f"gatt: {e}"),
    )

    loop.run()

    if reg["failure"] is not None or not reg["advert"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
