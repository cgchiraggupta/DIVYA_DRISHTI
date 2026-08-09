# Divya Drishti — Companion App

A companion app for the Divya Drishti assistive glasses: pair a device, watch live status,
review alert history, and tune how it alerts you. Built as a React web app (Vite + Tailwind +
Supabase), packaged for Android with Capacitor.

## Stack

- **Vite + React** — app shell
- **Tailwind CSS v4** — styling, via a small design-token theme in `src/index.css`
- **React Router** — navigation
- **Supabase** — Postgres database and Realtime for live device status
- **Capacitor** — Android app shell (`com.divyadrishti.app`)

## Getting started

```bash
npm install
cp .env.example .env   # fill in Supabase public configuration
npm run dev
```

### Local demo mode (no authentication)

For UI testing without Supabase or authentication, set `VITE_DEMO_MODE=true` in `.env` and restart
the dev server. The app opens with a local sample device, status, and alert history; no account or
remote data is used. Set it back to `false` before connecting a real device or building for release.

Preview mode is a consumer-facing simulated walk, not a developer console. It includes realistic
guidance outcomes such as a clear path, an object ahead with distance, right-side obstacles, and
uneven ground. Each choice updates the live guidance card and saved activity history so the same
experience can later be driven by Pi/Supabase data.

### Android development

The Android Capacitor project is in `android/`. Build and copy the current web app into it with:

```bash
npm run android:sync
```

To create a debug APK on a machine with the Android SDK configured:

```bash
npm run android:build
```

## Access model

There is no account, sign-in, or Google authentication. Anyone can use the app: enter the
six-character pairing code spoken by the glasses to open that device's dashboard. The code is
also used for the nearby same-Wi-Fi link between the phone and the glasses.

## Supabase setup

1. Create a Supabase project.
2. Run `supabase/schema.sql`, then the migrations in `supabase/migrations/` in order.
3. Copy your Supabase project URL and anon key into `.env`, and set `VITE_DEMO_MODE=false`.

## Pairing model

Each physical device is expected to insert its own row into `devices` on first boot
(with a pairing code). The app stores that code on the phone after pairing. The Pi script also
provides a nearby same-Wi-Fi status endpoint on port `8765`; its setup-only test service lives in
`setup/hardware-integration/divyadrishti_local_link.py`.

## Project structure

```
src/
  components/   Layout, BottomNav, Card, Button, StatusPulse (signature live-sensing indicator)
  context/      DeviceContext (paired device + Realtime status/events)
  lib/          supabaseClient.js, format.js (labels/timestamps), demoData.js (demo-mode sample data)
  pages/        Pairing, WifiSetup, Dashboard, History, Settings, Diagnostics
supabase/
  schema.sql    Full database schema + RLS policies
```

## Roadmap

Short version of the phased plan:

- [x] Foundation — scaffold, pairing-first routing, Supabase schema, and local demo mode
- [x] Companion UI — dashboard, history, settings, diagnostics, and pairing screens
- [x] Android shell — Capacitor configured and synced to an Android native project
- [ ] Now — complete the polished preview experience: simulated pairing, Wi-Fi setup, connection
  state, alerts, object-recognition outcomes, and command acknowledgements
- [x] Nearby Wi-Fi link — direct phone-to-Pi availability verified on Android
- [ ] Hardware integration — BLE pairing/Wi-Fi provisioning and Pi-side status, event, command,
  and pairing integration; see `setup/hardware-integration/`
- [ ] Vision upgrade — object/sign recognition and OCR, with safe obstacle-and-distance fallback
  for “What is ahead?”
- [ ] Deferred only — push notifications; see `deferred/push-notifications/`

## Design notes

Palette and type system are defined as CSS variables in `src/index.css` (`@theme` block) —
a deep "night navigation" palette (indigo background, amber signal accent, green/red for
safe/hazard states) with Space Grotesk for headings, Inter for body text, and JetBrains Mono
for data readouts (distances, timestamps, IDs). The signature UI element is the pulse ring
around the connection indicator (`StatusPulse` component), echoing the device's own ToF
sensing behaviour; it respects `prefers-reduced-motion`.
