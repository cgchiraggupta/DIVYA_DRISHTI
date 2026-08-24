# Hardware integration plan

This is the implementation contract for connecting the polished companion app to the Divya Drishti
glasses once the hardware is available. It is separate from `deferred/`, because these are core
product features rather than optional future ideas.

## Connection model

1. **Bluetooth Low Energy (BLE)** handles nearby-device discovery, first-time pairing, and secure
   Wi-Fi provisioning.
2. **Wi-Fi + Supabase** handles normal day-to-day communication: live device status, alerts,
   history, settings, and commands. The app must not depend on a permanent Bluetooth connection.
3. The physical device displays or speaks a pairing code; the app claims that device after the user
   enters or scans the code.
4. **Wearer earbuds** are a separate Classic Bluetooth link on the Pi (not the phone). One
   remembered headset, auto-connect when the case opens. Not every consumer bud works — see
   [BLUETOOTH_EARBUDS.md](BLUETOOTH_EARBUDS.md).

## Wi-Fi setup

The app should guide a user through connecting the glasses to their home Wi-Fi over BLE. The Pi
receives the selected network credentials, attempts the connection, and reports success or a clear
failure state. A temporary device hotspot/captive portal is the fallback if BLE provisioning is not
available on the final hardware.

## App and device communication

The Pi will publish the following to Supabase after it is connected:

- Current status: battery, connectivity, ToF health, camera health, microphone health, sensing
  mode, latest alert, and timestamp.
- Event history: obstacle direction, uneven ground, distance, voice commands, faults, and
  connection changes.
- Command acknowledgements: self-test, settings applied, Wi-Fi setup result, and future actions.

The app will send settings and commands through an authenticated command channel. The exact
`device_commands` schema and Pi polling/acknowledgement behavior will be added when the hardware
team confirms its preferred transport.

## Automatic sensing startup

`divyadrishti-sensing.service` starts the device program automatically. It waits for a normal
`wlan0` Wi-Fi route before launching `/home/pi/divya_drishti_final.py`, so it does not run during
the temporary `DivyaDrishti-Setup` hotspot flow. It is supervised by systemd and restarts after
an unexpected crash. SSH is only needed for diagnostics or software updates.

## Vision and voice behavior

Current reported behavior is safety detection, not object recognition:

- “Obstacle ahead/right/left” and “uneven ground” come from ToF/CV safety logic.
- “What is ahead?” currently reports the detected hazard and its distance.
- It does **not** identify what the object is.

Planned upgrade: camera-based object/sign recognition and OCR. When confidence is high, “What is
ahead?” should answer with object name, direction, and distance, for example: “Chair ahead, about
one metre away.” When recognition is unavailable or uncertain, it must safely fall back to:
“Obstacle ahead, about 60 centimetres away.”

## Demo now, hardware later

The app's preview mode will simulate BLE pairing, Wi-Fi setup, live connection state, obstacle
alerts, object-recognition results, failures, and command acknowledgements. The user-facing app
will call the same data/command interface in both modes; only the simulated provider is replaced
when the Pi arrives.

## Information needed from the hardware team later

- Confirmation that the Pi exposes BLE and its GATT service/characteristic contract.
- The preferred Wi-Fi provisioning method: BLE or temporary hotspot.
- Pairing-code generation and display/speech behavior.
- A safe device-side authentication/provisioning design for Supabase.
- Final Pi status, event, command, and acknowledgement payload examples.
- The supported vision model/API and whether object recognition/OCR runs locally or in the cloud.

## BLE Wi-Fi provisioning (primary path)

The glasses run a BlueZ GATT peripheral so a phone can hand over Wi-Fi
credentials with no Wi-Fi, router, or internet present. The Wi-Fi hotspot path
below stays as a fallback.

On the affected Raspberry Pi kernel, BlueZ's D-Bus advertising registration
can report an active instance without transmitting an advertisement. GATT
registration remains on D-Bus; `divyadrishti-adv-helper.c` sends the legacy
Linux MGMT advertising command directly. The helper is supervised by the Python
provisioner and removes its advertising instance when the service stops.

### GATT contract

Advertised primary service and characteristics (keep in sync with
`src/services/bleProvisioning.js`). The current 31-byte legacy advertising
packet deliberately omits a local name, so the app scans by service UUID:

| Role   | UUID                                   | Access        | Payload |
| ------ | -------------------------------------- | ------------- | ------- |
| Service| `5f3e0001-2a11-4b0e-9c3a-1f2e3d4c5b6a` | —             | — |
| RX     | `5f3e0002-2a11-4b0e-9c3a-1f2e3d4c5b6a` | write         | credential JSON, chunked ≤18 bytes |
| Commit | `5f3e0003-2a11-4b0e-9c3a-1f2e3d4c5b6a` | write         | any 1 byte → validate + join |
| Status | `5f3e0004-2a11-4b0e-9c3a-1f2e3d4c5b6a` | read, notify  | `idle` / `connecting` / `connected` / `error:*` |

Reassembled RX payload: `{"code":"<pairing>","ssid":"<ssid>","password":"<psk>"}`.
The commit write validates the pairing code, SSID (1–32 bytes), and password
(8–63 chars), then runs the same `nmcli` join the HTTP provisioner uses.

**Security:** characteristics are unencrypted and unbonded; the pairing code is
the only gate and the link is sniffable. Acceptable for a private prototype
only. A public product must require BLE bonding + encrypted characteristics.

### Deploy on the Pi

```bash
gcc -O2 -Wall -o /tmp/divyadrishti-adv-helper divyadrishti-adv-helper.c
sudo install -m 755 /tmp/divyadrishti-adv-helper /usr/local/sbin/divyadrishti-adv-helper
sudo install -m 755 divyadrishti-ble-provisioner.py /usr/local/sbin/divyadrishti-ble-provisioner
sudo apt-get install -y python3-dbus python3-gi bluez   # usually already present
sudo systemctl restart divyadrishti-ble-provisioner.service
sudo journalctl -u divyadrishti-ble-provisioner.service -n 50 --no-pager
```

Set `DIVYADRISHTI_PAIRING_CODE` through a device-local systemd drop-in before
starting the service. Never put the pairing value in this repository.

### End-to-end test sequence

1. Confirm the Pi BLE service is `active (running)`.
2. On the phone, open Divya Drishti → Settings → Change Wi-Fi network.
3. Turn on the phone hotspot before starting provisioning.
4. Enter the target Wi-Fi/hotspot name and password, then tap Connect glasses.
5. Grant Bluetooth permission; the app scans by the provisioning service UUID,
   connects, writes credentials, and waits for `connected`.
6. Keep the hotspot on while the Pi joins it. Confirm on the Pi with
   `nmcli -t -f NAME,DEVICE connection show --active`.
