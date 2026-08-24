# Wearer Bluetooth earbuds (glasses, not phone)

Collaborator note. Wearer hearing and “Hey Divya” on the live prototype go through **Bluetooth earbuds on the Raspberry Pi**, not through the phone speaker. The phone app only starts pairing. It does not stay connected to the buds.

Do not put pairing codes, Wi‑Fi passwords, or API keys in this file or in chat logs.

## What is actually implemented

The glasses remember **one** Classic Bluetooth headset (MAC + name) in:

`/home/pi/.divyadrishti/bt-earbuds.json`

Default if that file is missing: boat **Nirvana Ion**. After a successful **Pair new earbuds**, that file is overwritten. Auto-connect and sensing both read it. There is no per-brand driver and no in-app list of models to tap.

| Piece | Role |
|---|---|
| `divyadrishti_bt_config.py` | Load/save remembered MAC; scan/pair/trust/connect |
| `divyadrishti_bt_earbuds.py` + `divyadrishti-bt-earbuds.service` | Keep reconnecting the remembered headset (open the case → connect) |
| `divya_drishti_final.py` | Speak on A2DP; optional HFP mic; `pair_earbuds` nearby command |
| App Settings → **Glasses earbuds** | Sends `POST /v1/command` `{ "command": "pair_earbuds" }` on the same Wi‑Fi |

Audio on the Pi uses BlueALSA:

- Speaker: A2DP (`bluealsa:DEV=<mac>,PROFILE=a2dp`)
- Mic: HFP SCO, and only reliably if the codec is **CVSD 8 kHz** (mSBC/16 kHz has been silent on this stack)

## Everyday use (already-paired headset)

1. Power the glasses on.
2. Open the earbud case. Wait a few seconds.
3. Keep **phone Bluetooth off**. If the phone is scanning, it often steals the same buds and the glasses stay silent.

No extra tap in the app. This is the same idea as a phone remembering a headset, but only for the one MAC the glasses saved.

## First-time pair (new headset)

The app does **not** let anyone pick a device by name. Pairing is “scan, then keep one.”

1. Glasses on, phone and glasses on the **same Wi‑Fi**. Settings should show the earbuds card as linked nearby. If the Pair button never changes to **Scanning…**, the nearby link is down and nothing ran on the Pi.
2. Phone Bluetooth **off**.
3. Put **only** the new buds in pairing mode, case next to the glasses.
4. Settings → Glasses earbuds → **Pair new earbuds**. Wait ~15–20 seconds. The glasses speak the result.

Chooser logic (`pair_new_earbuds`): look for Classic devices that look like a headset (A2DP / Hands-Free UUIDs). Prefer **unpaired** audio devices. If several match, take the **strongest RSSI**. If none match, keep the current remembered headset (usually Nirvana Ion).

## Do we code each earbud?

**No**, not if the buds speak old-school Classic Bluetooth (A2DP speaker + HFP hands-free). One pair path, one saved MAC.

**Also no**, you cannot make every consumer bud work by adding another Settings button or a brand `if` in Python. This Pi is not a phone. It does not implement Apple/Google Fast Pair, LE Audio, or Auracast the way Android/iOS do.

### Compatibility (honest)

| Usually works (no extra code) | Usually will not, no matter what we write |
|---|---|
| boat Nirvana Ion (proven on this hardware) | AirPods / AirPods Pro |
| Other Classic TWS that a **laptop** pairs as a normal headset (other boat Nirvana / Rockerz / older Airdopes, many ₹1–3k TWS) | Pixel Buds Pro, Galaxy Buds2/3 Pro in LE Audio |
| Sony WH-CH / WH-1000XM, JBL Tune / Live, Soundcore Life / Space (as Classic headsets) | Newer OnePlus Buds 3-style / Fast Pair–only / Auracast-only |

**Field check before promising a model:** pair those same buds to a laptop. If the laptop never gets a normal **headset** connection (not just “LE audio” / manufacturer app), this Pi will not either.

Speaker (A2DP) is easier than mic (HFP). A set can play TTS and still fail wake-word capture.

## Why “I tapped Pair and nothing happened”

The Pair button is disabled until the phone can reach the glasses on Wi‑Fi (`/v1/command` on port 8765). Grey button + no **Scanning…** means the command never left the phone. Sitting buds next to the glasses is not enough.

Live Pi address on the current bench has been `192.168.1.39` (mDNS `divyadrishti.local` often drops). Confirm `curl` to `/v1/health` before debugging Bluetooth.

## Do not

- Leave the companion phone’s Bluetooth on while testing wearer audio.
- Assume a successful pair in the phone’s Bluetooth settings means the glasses own the buds.
- Commit `/home/pi/.divyadrishti/device.json`, `sarvam.env`, or pairing codes.
- Restart `divyadrishti-sensing.service` on a live wearer without a go-ahead.
