# Chat handoff — 19 Aug 2026 (morning)

Paste this into a **new Cursor chat**. Repo: `/Users/apple/Documents/divyadrishti`. Pi: `ssh pi@divyadrishti.local`. Owner: Chandar. Never deploy/restart/reboot Pi or edit `/home/pi/divya_drishti_final.py` without explicit go-ahead. Never log API keys.

## What this last chat did

### Gemini / describe (software, live on Pi)
- Key in `/home/pi/.divyadrishti/gemini.env` is **valid billed** (prefix `AQ.A…`, not free `AIzaSy`). Failures were **timeouts**, not 429.
- Switched model **`gemini-3.6-flash` → `gemini-3.5-flash`**. Live image timing: 3.6 ~23s, 3.5 ~6s.
- Manual describe (double-tap GPIO25) **works**: `describe_frame status=ok source=gemini took 8.65s`.
- Startup auto-describe **works**: first settled frame after camera ready, then every **5 min**. Confirmed `describe_scene_auto … took 5.03s`.
- Manual describe now **waits** for in-flight Gemini instead of instant `busy`.
- Phone speaks Hindi; distances stay English `cm`/`m`.
- **Uncommitted locally:** `gemini_describe.py`, `divyadrishti_control_button.py`, `divya_drishti_final.py` (repo copy), `patch_startup_auto_describe.py`. Pi already has the live copies.

### Button
- Double-tap = describe. Single tap = start sensing. Hold 3–7s poweroff, ≥8s reboot.
- Last proof: `DOUBLE TAP → local API` then `200 status=ok`.

### Branches (not fully in local `main`)
- `feature/auto-describe-interval` — 5 min ambient (on Pi).
- `feature/haptic-continuous-cap` — stop buzz after 3s same obstacle (**on Pi, not in local main**).
- `test/combined-haptic-autodescribe` — merge of those two.
- Local `main` still has old haptic restart (`haptic_quiet and approaching_now`). Next deploy of repo main could wipe the 3s cap unless merged.

### Walking / haptic plan (no code — plan only)
- Next product work: calmer haptics, corridor/wall false-alarm reduction, Hindi walking phrases. ToF+haptic stays instant; Gemini never gates safety.
- Suggested first merge: haptic 3s cap. Field walk (Phase 0) before more tuning.

### Speaker + mic — **handed to hardware engineer** (do not keep chasing in software)
**Speaker (MAX98357A):** L+/L− correct (not GND). Pi **does send I²S** (GPIO21/Pin 40 toggles with `max98357a` overlay). User hears **clicks/pops, not voice**. After reboot **no overlay in config.txt**. Voicehat overlay rapidly enables/disables amp (pops). Ask engineer: **SD → VIN**, then `dtoverlay=max98357a,no-sdmode`, swap module if still clicks.

**Mic (INMP441):** Wiring on paper is correct (SD Pin 38, L/R GND). After overlay, capture device exists but **`arecord` peak=0**. Voice loop cannot hear commands. Engineer: continuity Pin 38, 3.3V on VDD, or swap module.

**config.txt now:** all of `hifiberry-dac`, `googlevoicehat-soundcard`, `max98357a` are **commented**. Overlay load is lost on reboot unless engineer + Chandar approve writing one line + reboot.

Phone TTS (Sarvam) remains primary speech until glasses speaker is clear.

## Do next (software, not hardware)
1. Wait on engineer for speaker SD + mic SD continuity.
2. Merge haptic 3s cap into `main` so Pi and git match.
3. Commit Pi describe/timeout/model changes when Chandar asks.
4. Optional: walking haptic plan implementation after a field walk.

## Do not
- Don’t assume Gemini 429 — that’s old.
- Don’t enable both voicehat and max98357 overlays together.
- Don’t claim speaker or mic “fixed” until heard/recorded.
- Don’t reboot Pi to persist overlay without Chandar OK.
