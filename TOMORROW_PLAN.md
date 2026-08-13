# Divya Drishti — Resume Plan (as of Aug 10, 2026)

## Where things actually stand

Static code review says feature-complete. Live runtime check says Gemini is still blocked; everything ToF/haptic/photo-side is already proven live:

- **Gemini API HTTP 429 (quota)** — **blocked waiting on billing person** (not a code task right now). Blocks Read (A6) and AI obstacle naming (A7).
- **Phone / latest APK** — still needed for final Android polish verification when the device is available.

Everything else (ToF, vibration, pause/resume, settings sync, photo→History, portable walk-test) is confirmed working live, not just present in code.

---

## Gemini status (do not block the day on this)

- [ ] **Owner:** billing person — attach billing / raise quota on the Gemini API key
- [ ] **When unblocked:** re-run `gemini_describe_probe.py` on the Pi (log to temp file — don't rely on SSH echo)
- [ ] Only after probe succeeds: retest Describe/Read end-to-end from the phone

Until billing clears, treat A6/A7 as **out of the critical path**. Do not sit idle waiting.

---

## Parallel work (do this while Gemini is blocked)

| Track | What | Notes |
| --- | --- | --- |
| **App polish** | History/Obstacles clarity, Settings Apply UX, connection status | No Gemini dependency |
| **GPIO25 button (repo)** | Button service / docs already in flight — continue from `PLAN_button_service.md` | Hardware confirmed; software polish in repo |
| **Demo script** | Use `DEMO_WALK_SCRIPT.md` — 5 min ToF-only walk checklist | Same Wi-Fi, unpaused, Apply after slider |
| **ToF-only exit path** | Prove distance + photo + haptic without AI Read | Formal exit option below |

Suggested order while blocked:

1. Run / rehearse `DEMO_WALK_SCRIPT.md` (ToF-only)
2. App polish + APK install when phone is available
3. GPIO25 button work in repo (per button plan)
4. Speaker decision (Step below) if still open
5. Resume Gemini only when billing person confirms quota is live

---

## Formal Phase 1 exit option (no Gemini)

**Accepted exit without AI Read:** wearable walk proves **distance (cm/m) + obstacle photo in History → Obstacles + haptic vibration**, with sensing unpaused and phone+glasses on the same Wi-Fi.

That maps to **A1–A5 + A8–A10** green. **A6 / A7** stay deferred until billing, not required to call Phase 1 exited under this option.

Checklist: follow pass/fail in `DEMO_WALK_SCRIPT.md`.

---

## Phone / APK (when device is back)

- [ ] Plug phone in, confirm ADB sees it (`adb devices` → `0015935A7000905`)
- [ ] Build + install latest APK (`npm run android:build` → install)
- [ ] Re-check History tab refresh and Settings "on glasses now" sync

---

## One decision still owed (not a code task)

**Is the glasses speaker required for Phase 1, or is phone TTS (Sarvam) the accepted primary audio output?**

Context: the `hifiberry-dac`/`googlevoicehat-soundcard` I²S conflict was addressed in `config.txt`, but there's no confirmed clean-audio test result yet. Two honest paths:

- **A)** Test the speaker fix properly (5 min), and if it's clear, glasses speaker is secondary/backup
- **B)** Accept phone TTS (Sarvam) as primary Phase 1 audio and stop chasing the glasses speaker until the hardware swap

Either is fine — just pick one so it stops being an open question.

---

## Phase 1 exit checklist (reference)

**A — must be green to exit (ToF-only option):**
A1 Dual ToF detect · A2 Vibration urgency patterns · A3 Settings 1.0–2.5m to hardware · A4 Pause/resume from phone · A5 Instant obstacle photo → History · A6 On-demand Read (**blocked — billing person**) · A7 Obstacle Gemini naming (**blocked — billing person**) · A8 Android app tabs (**needs APK install**) · A9 Portable wearable walk · A10 No crash during walk

**Exit gate (formal ToF-only):** A1–A5 + A8–A10 green via `DEMO_WALK_SCRIPT.md`. A6/A7 optional until billing.

**Exit gate (full AI):** same plus A6 working after Gemini quota is fixed.

**B — must-fix before calling it closed:** demo script discipline (unpaused sensing, same Wi-Fi, Apply after slider) · latest APK when phone available · speaker decision above · Gemini billing handoff tracked (not self-unblocked).

---

## After Phase 1 closes — enrichment backlog (not blocking)

You're already ahead of brief on some of this — `describe_obstacle()` with its own cooldown and Hinglish obstacle narration is built and live, which technically belongs to this list, not Phase 1.

**Near-term enrichment (C-tier, low effort):**
- Battery % surfaced in app (currently often missing)
- Cleaner History view for demos (hide noisy "All cloud" entries)
- Stronger OpenCV path/edge guidance as a non-Gemini fallback (currently thin)

**Bigger/later (explicitly future):**
- Wake word ("Hey Divya Drishti") — phone mic first, glasses mic later
- Glasses speaker as primary output (post hardware swap)
- Color ID / object memory (up to 1k objects)
- GPS / maps / destination routing
- Continuous always-on Gemini (deliberately rejected — keep it that way)
- Miniaturization, custom PCB, casing, certification, mass manufacture

---

## Rules that still apply (carrying over, don't relitigate)

- Never edit `/home/pi/divya_drishti_final.py` without showing the diff and getting approval first
- Never stop/restart `divyadrishti-sensing.service`, activate speaker/motors, or reboot the Pi without explicit in-the-moment go-ahead
- Never `git add .` / `-A` — patch-stage only, task-relevant hunks
- Don't push unless asked
- Gemini key stays in terminal/env, never in chat
- Always show real evidence before claiming something's fixed
