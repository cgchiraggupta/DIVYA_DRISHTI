# Phase 1 demo walk script — ToF only (≈5 min)

**Mode:** Distance + photo + haptic. **No Gemini required.**

Use this when billing/quota blocks AI Read and obstacle naming. Pass = walk proves the wearable safety loop without any cloud vision call.

---

## Before you start (30–60 s)

| Check | Pass |
| --- | --- |
| Phone and glasses (Pi) on the **same Wi-Fi** | [ ] |
| App connected (live status / not “offline”) | [ ] |
| Sensing **unpaused** (pause control off / sensing active) | [ ] |
| Glasses wearable on body; phone in pocket or hand nearby | [ ] |
| Optional: Settings → set obstacle range with slider → tap **Apply** → confirm synced (“on glasses now” or equivalent) | [ ] |

If any of the first three fail, stop — fix Wi-Fi / connection / pause before walking.

---

## Walk (≈3–4 min)

Walk a short indoor path with at least one clear obstacle (chair, wall, closed door).

| Expect | Pass |
| --- | --- |
| **Buzz / vibration** when obstacle enters range (urgency may change with distance) | [ ] |
| **Photo** appears under **History → Obstacles** after an alert | [ ] |
| **Distance** shown in **cm** or **m** (not blank / not only AI label) | [ ] |
| Sensing stays up for the whole walk (**no crash** / service still active) | [ ] |

Do one Settings tweak mid-demo if useful: move slider → **Apply** → walk again and confirm vibe timing still matches the new range.

---

## What NOT to expect (Gemini billing blocked)

Do **not** fail the demo for these while quota/billing is blocked:

- No **Read / Describe** OCR or scene text from Gemini
- No **AI object names** / Hinglish obstacle labels from Gemini
- No requirement that History show a Gemini caption — photo + distance is enough

If someone asks for Read mid-demo: say “AI Read is waiting on billing; this walk is ToF safety only.”

---

## Pass / fail

**PASS** — all of:

- [ ] Same Wi-Fi + sensing unpaused
- [ ] Vibration fired on obstacle
- [ ] Obstacle photo in History → Obstacles
- [ ] Distance in cm/m visible
- [ ] No crash during walk

**FAIL** — any of:

- [ ] No buzz on a clear in-range obstacle
- [ ] No photo in History → Obstacles after alert
- [ ] Distance missing / wrong units (not cm or m)
- [ ] Sensing died or app lost connection for the walk
- [ ] Demo depended on Gemini Read / AI names to look “done”

---

## After the walk (optional 30 s)

- [ ] Note pass/fail and one sentence of evidence (e.g. “vibe at ~1.2 m, photo in Obstacles”)
- [ ] If PASS: Phase 1 may use the **formal ToF-only exit** (see `TOMORROW_PLAN.md`) without waiting on Gemini
- [ ] If FAIL: fix the failing row before re-running; do not burn time on Gemini until ToF path is green
