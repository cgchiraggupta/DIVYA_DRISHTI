# Divya Drishti — Project Context (0 → A → Z)

This is the single "start here" document for the project. It exists so anyone — a new
contributor, or a fresh AI session — can understand the whole thing without reading six other
files first. For *why* things are built the way they are (decisions, problems, fixes), see
`DECISIONS_AND_LESSONS.md`. This file is about *what* the project is and how it fits together.

---

## 1. What this project is

**Divya Drishti** ("divine sight" in Hindi) is a pair of assistive glasses for visually impaired
users, plus a phone app that pairs with them. In user-facing conversation the product is called
**"DeepGear TST"**; the repository and backend are named Divya Drishti.

The glasses (a wearable built around a Raspberry Pi) do the real-time safety sensing —
detecting obstacles and uneven ground and turning that into vibration and spoken alerts — while
the phone app is the display, settings, and history surface, and (currently) the primary voice
output.

Two halves of one system:

1. **Hardware / Pi side** — `setup/hardware-integration/` — Python service(s) running on a
   Raspberry Pi, driving two Time-of-Flight (ToF) distance sensors, a camera, two vibration
   motors, a physical control button, BLE Wi-Fi provisioning, and (on demand) Google Gemini for
   scene/object description.
2. **App side** — `src/` — a React web app (bundled for Android via Capacitor) that pairs with a
   glasses unit, shows live status, alert history, and settings, and speaks guidance out loud.

They are connected through **Supabase** (Postgres + Realtime) for day-to-day data, and through a
**local HTTP link + BLE** for setup and same-Wi-Fi low-latency commands.

---

## 2. Who it's for and the core interaction model

- The user is visually impaired and wears the glasses. They do not necessarily operate the phone
  screen directly during a walk — audio and haptic feedback come from the glasses/phone, and the
  phone app is also usable by a sighted companion/caregiver for setup and monitoring.
- **No accounts, no sign-in, no Google/Clerk login in the running app.** Anyone can use the app:
  the glasses speak a six-character pairing code, the user enters/scans it in the app, and that
  claims the device for that phone. This was a deliberate simplification (see decisions doc) —
  there are leftover Clerk-based ownership pieces in the codebase from an earlier direction, but
  they are not wired into the current app.
- Because there's no auth, the pairing code is the only access boundary today. That has real
  security implications, tracked in `SECURITY_AUDIT.md` (see §8 below).

---

## 3. System architecture

```
┌─────────────────────────┐        BLE (pairing/Wi-Fi credentials only)
│   Raspberry Pi (glasses) │◄───────────────────────────────────┐
│                          │                                     │
│  divya_drishti_final.py  │        Wi-Fi + Supabase (status,    │
│  - ToF x2 (I2C, VL53L5CX)│         events, settings, commands) │
│  - camera (Picamera2)    │◄───────────────┐                    │
│  - vibration motors x2   │                 │                    │
│  - GPIO25 control button │                 │                    │
│  - gemini_describe.py    │                 │                    │
│    (on-demand + event-   │                 │                    │
│     triggered narration) │                 │                    │
│  - local HTTP :8765/:8080│◄──same-Wi-Fi────┼───────────┐        │
└───────────┬──────────────┘   (nearby link) │           │        │
            │                                 ▼           ▼        │
            │                          ┌─────────────────────┐    │
            └────────publishes────────►│      Supabase        │    │
                                        │ devices / status /   │    │
                                        │ events / settings /  │    │
                                        │ device_commands      │    │
                                        └───────────┬───────────┘    │
                                                     │ Realtime       │
                                                     ▼                │
                                        ┌─────────────────────┐      │
                                        │   Phone app (React,  │◄─────┘
                                        │   Capacitor/Android) │  BLE (bleProvisioning.js)
                                        │ Dashboard/History/    │
                                        │ Settings/Diagnostics  │
                                        │ Sarvam TTS (hi-IN)    │
                                        └─────────────────────┘
```

Two communication paths exist on purpose:

- **BLE** — only for first-time pairing and handing the glasses Wi-Fi credentials when there is no
  Wi-Fi/router yet. Not used for anything else; the app must not depend on a permanent Bluetooth
  connection.
- **Wi-Fi + Supabase** (plus a same-Wi-Fi local HTTP link for lower latency) — everything else:
  live status, alerts/events, settings changes, commands (like "describe what's ahead"), and
  command acknowledgements.

---

## 4. Tech stack, and why each piece is there

| Layer | Choice | Why |
| --- | --- | --- |
| App shell | Vite + React 19 | Fast dev loop, standard SPA tooling |
| Styling | Tailwind CSS v4 | Small design-token theme (`@theme` block in `src/index.css`); fast to iterate on a "night navigation" visual style |
| Routing | React Router v7 | Pairing-first route guards (can't reach Dashboard/History/Settings without a paired device) |
| Backend / data | Supabase (Postgres + Realtime) | One hosted service gives Postgres, row-level security, and live subscriptions without standing up custom infra |
| Mobile packaging | Capacitor (Android) | Ship the same React app as a native Android app; access Bluetooth LE, haptics, and text-to-speech plugins |
| Device-side language | Python on Raspberry Pi | Standard for GPIO/I2C/camera work on Pi; direct access to `picamera2`, `gpiozero`/`lgpio`, ToF sensor libraries |
| On-demand vision/description | Google Gemini (`gemini-3.6-flash`, currently) | Cloud vision model for scene/object description and Hinglish/Hindi narration, called only on demand or with a strict per-event cooldown — never continuously |
| Voice output | Sarvam TTS (`hi-IN`) on the phone | Chosen as the **primary** voice output after the glasses' own speaker turned out to be unreliable (see decisions doc) |

---

## 5. Repository map

```
src/
  App.jsx                     Route table + guards (pairing-first)
  components/
    Layout.jsx, BottomNav.jsx Shared app chrome
    Card.jsx, Button.jsx      Small design-system primitives
    StatusPulse.jsx           Signature live-sensing pulse ring (echoes the glasses' own ToF sensing)
  context/
    DeviceContext.jsx         Paired device + Realtime status/events/settings state
    AuthContext.jsx           Leftover from an earlier Clerk-based direction; not the active access model
  lib/
    supabaseClient.js         Supabase client + anon key wiring
    format.js                 Label/timestamp formatting helpers
    demoData.js               Local demo-mode sample device/status/history
    lucide.js                 Hand-picked icon barrel (see decisions doc — perf fix)
  pages/
    Pairing.jsx, WifiSetup.jsx, Dashboard.jsx, History.jsx, Settings.jsx, Diagnostics.jsx, Login.jsx
  services/
    bleProvisioning.js        BLE GATT client for Wi-Fi credential handoff
    localDeviceLink.js        Same-Wi-Fi local HTTP link to the Pi (nearby mode)
    backgroundGuardian.js     Keeps guidance alerts flowing while app is backgrounded (Android)
    sarvamTts.js               Sarvam text-to-speech integration
    sensoryFeedback.js         Haptic/audio alert dispatch on the phone
    obstacleHistory.js         Client-side obstacle event/history handling

supabase/
  schema.sql                  Full table definitions, RLS policies, RPCs, Realtime publication
  migrations/                 Ordered schema migrations (see README for apply order)

setup/hardware-integration/
  divya_drishti_final.py      (lives on the Pi, not in this repo verbatim) main sensing/alerts loop
  divya_drishti_final.RECONSTRUCTED.py, recovered-*.partial.py.txt
                               Recovered/partial reference copies — NEVER deploy these directly
  gemini_describe.py          Shared Gemini helper (on-demand describe + event-triggered obstacle narration)
  gemini_describe_probe.py    Standalone Gemini connectivity/quota probe
  divyadrishti_control_button.py + .service
                               GPIO25 tap/hold-to-shutdown/hold-to-reboot button daemon
  divyadrishti-ble-provisioner.py/.service, divyadrishti-adv-helper.c
                               BLE GATT Wi-Fi provisioning + native BLE advertising workaround
  divyadrishti-wifi-provisioner.py, divyadrishti-hotspot*.{sh,md,service}, dnsmasq-*.conf, hostapd.conf
                               Fallback hotspot-based Wi-Fi setup path
  divyadrishti_local_link.py + .service
                               Same-Wi-Fi local status/command HTTP link (nearby mode)
  divyadrishti_wake_word.py + .service, DEPLOY_WAKE_WORD.md
                               Not deployed yet — Hindi wake-word listener, gated on a chip-compatibility check
  apply_*.py                   One-off, reviewable patch scripts against the Pi's main script
                               (see decisions doc — this is the deliberate workflow, not a mess)
  DEPLOY_BUTTON.md, README.md  Deployment steps and the hardware-integration contract/plan

deferred/
  push-notifications/          Explicitly out of scope for now

Root docs:
  README.md                   Setup/run instructions, stack, roadmap
  CONTEXT_HANDOFF.md           Point-in-time handoff snapshot (superseded by this file over time)
  TOMORROW_PLAN.md             Point-in-time resume plan / phase-exit checklist
  PLAN_button_service.md       Implementation plan for the GPIO25 control button
  PLAN_gemini_describe.md      Implementation plan for phone-first Gemini describe/read
  DEMO_WALK_SCRIPT.md          5-minute ToF-only demo pass/fail script
  SECURITY_AUDIT.md            Supabase/RLS/pairing security findings
  PROJECT_CONTEXT.md           This file
  DECISIONS_AND_LESSONS.md     The "why" companion to this file
```

---

## 6. Pairing and demo-mode model

- Every physical glasses unit inserts its own row into the `devices` table on first boot, with a
  generated pairing code.
- The app's only "login" step is entering/scanning that code (`Pairing.jsx` → `claim_device_public`
  RPC). No email, password, or OAuth.
- **Local demo mode** (`VITE_DEMO_MODE=true` in `.env`) runs the whole app against local sample
  data (`src/lib/demoData.js`) with no Supabase or hardware required — used for UI development and
  for showing the product without a live Pi. It also runs a consumer-facing simulated walkthrough
  (clear path, object ahead with distance, side obstacles, uneven ground) that updates the live
  guidance card and saved history exactly like a real device would, so the same UI code path can
  later be driven by real Pi/Supabase data.
- **Nearby same-Wi-Fi link**: independent of Supabase, the Pi also exposes a local HTTP status/command
  endpoint on port `8765` (`divyadrishti_local_link.py`) so the app can talk to the glasses directly
  when both are on the same network, which is lower-latency than round-tripping through Supabase.

---

## 7. What the glasses actually do today (current behavior, not aspirational)

- **Two ToF sensors** (independent I2C buses) continuously watch for obstacles left/right/ahead
  and for uneven ground.
- **Two vibration motors** fire directional haptic patterns based on which side is actually
  blocked and how close it is (1.0–2.5 m configurable range). Urgent alerts never drop below 85%
  motor strength.
- **A photo is captured instantly** on obstacle detection and pushed to the phone/History —
  this never waits on Gemini.
- **Gemini description is on demand** (phone "Describe" button → Hinglish scene/text description,
  spoken via Sarvam) **or event-triggered with its own cooldown** (short obstacle-naming narration
  after an obstacle alert) — it is explicitly never continuous and never gates the ToF/haptic loop.
- **Voice output is currently phone-first**: the glasses' own speaker is unreliable, so spoken
  guidance goes to the phone (Sarvam TTS) rather than the glasses' onboard speaker. See decisions
  doc for why.
- **A physical GPIO25 button** on the glasses: tap starts/resumes sensing, hold 3–7s triggers a
  safe shutdown, hold 8s+ triggers a reboot.
- **"What is ahead?"** currently reports the detected hazard and distance (safety detection), not
  full object identity — general object/sign recognition is a planned upgrade, not current
  behavior, with Gemini description as the interim, on-demand answer to that question.

---

## 8. Current project state and roadmap

From `README.md` and `TOMORROW_PLAN.md`, in order:

- [x] **Foundation** — scaffold, pairing-first routing, Supabase schema, local demo mode
- [x] **Companion UI** — dashboard, history, settings, diagnostics, pairing screens
- [x] **Android shell** — Capacitor configured and synced to a native Android project
- [x] **Nearby Wi-Fi link** — direct phone-to-Pi availability verified on Android
- [ ] **Polished preview experience** — simulated pairing, Wi-Fi setup, connection state, alerts,
  object-recognition outcomes, command acknowledgements (in progress)
- [ ] **Hardware integration** — BLE pairing/Wi-Fi provisioning and Pi-side status/event/command/
  pairing integration (in progress; see `setup/hardware-integration/`)
- [ ] **Vision upgrade** — object/sign recognition and OCR, with safe obstacle-and-distance
  fallback for "What is ahead?" (not started; Gemini describe is the interim stopgap)
- [ ] **Deferred only** — push notifications (`deferred/push-notifications/`) — intentionally not
  being worked on

**"Phase 1" exit criteria** (from `TOMORROW_PLAN.md`), at a glance — A1–A5 and A8–A10 (ToF detect,
vibration patterns, settings sync, pause/resume, instant obstacle photo, Android app tabs,
portable wearable walk, no crash) must be green; A6/A7 (on-demand Gemini Read, AI obstacle naming)
are allowed to stay blocked pending Gemini API billing, per a deliberate formal decision to not let
a third-party billing delay block the whole project (see decisions doc).

**Explicitly out of scope right now** (do not start building these until Phase 1 formally exits):
wake word ("Hey Divya Drishti"), color ID/object memory, GPS/maps/routing, continuous
always-on Gemini (deliberately rejected, not just "not done yet"), miniaturization/custom
PCB/casing/manufacturing, push notifications.

---

## 9. Security posture (current, honest state)

`SECURITY_AUDIT.md` is a real audit of the Supabase/RLS/pairing setup, not a checklist that's been
resolved yet. Headline finding: **RLS is enabled on all tables but the current policies use
`using (true)` / `with check (true)`**, meaning anyone with the public Supabase URL and anon key
can read/write across all devices, not just their paired one — the pairing code is currently a
UX-level filter, not a real authorization boundary. This is acceptable for the current
private-prototype stage but is called out explicitly as **not safe for production multi-user use**
yet. See the audit for the specific findings (DD-01 through DD-08) and recommended fixes.

---

## 10. How to run it

```bash
npm install
cp .env.example .env      # fill in Supabase URL + anon key, or set VITE_DEMO_MODE=true
npm run dev
```

Android:

```bash
npm run android:sync      # build web + sync into the Capacitor Android project
npm run android:build     # build a debug APK (needs Android SDK configured)
npm run android:install   # fast path: build + rsync + incremental gradle + adb install (see below)
```

Supabase (real device mode, `VITE_DEMO_MODE=false`):

1. Create a Supabase project.
2. Run `supabase/schema.sql`, then the migrations in `supabase/migrations/` in order.
3. Put the project URL and anon key into `.env`.

Pi-side deployment is manual/SSH-based per script (`DEPLOY_BUTTON.md`, `DEPLOY_WAKE_WORD.md`, and
the `apply_*.py` patch-and-review workflow) — there is no CI/CD to the Pi.

---

## 11. Design language

Defined as CSS variables in `src/index.css` (`@theme` block): a "night navigation" palette
(indigo background, amber signal accent, green/red for safe/hazard states), Space Grotesk for
headings, Inter for body text, JetBrains Mono for data readouts (distances, timestamps, IDs). The
signature UI element is the pulse ring around the connection indicator (`StatusPulse.jsx`),
deliberately echoing the glasses' own ToF sensing behavior, and it respects
`prefers-reduced-motion`.

---

## 12. Who's involved / how work happens

Per `CONTEXT_HANDOFF.md`: the project owner ("Chandar") orchestrates work conversationally, with
actual code and hardware execution happening through Cursor (this environment) and, for some
history, Codex. Communication is casual/Hinglish; direct execution is expected but hardware state
changes (restarting the sensing service, activating the speaker/motors, rebooting the Pi) require
explicit in-the-moment go-ahead every time, not a standing permission. See
`DECISIONS_AND_LESSONS.md` for the operating rules this produced.
