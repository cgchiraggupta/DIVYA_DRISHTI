# Divya Drishti — Decisions, Problems, and Lessons

This is the "why" document. `PROJECT_CONTEXT.md` describes what the project is; this one records
**why it was built this way**, **what actually went wrong along the way**, and **what was changed
because of it**. Everything below is reconstructed from real artifacts in this repository —
commit history, patch scripts and their doc-comments, plan documents, and the security audit —
not invented for narrative effect. Where the repo doesn't fully spell out the reasoning, that's
noted rather than guessed at.

Each entry follows the same shape: **Situation → Decision/Fix → Why**.

---

## Part A — Product and architecture decisions

### A1. No accounts, no sign-in — pairing code is the only "login"

**Situation.** The codebase contains a more conventional ownership model: Clerk-based auth
(`AuthContext.jsx`, `Login.jsx`), an `owner_id` column, and a `claim_device` RPC that binds a
device to an authenticated user's JWT subject.

**Decision.** The shipped app bypasses all of that. It calls `claim_device_public` as the
anonymous Supabase role, and the only gate to using the app is knowing/scanning the six-character
pairing code the glasses speak on first boot.

**Why.** The product is meant to be usable immediately by a visually impaired user or a
companion/caregiver, with the lowest possible friction — no forms, no password, no email
verification loop. A prototype/early-access product for an accessibility use case benefits far
more from "just enter the code" than from a full account system. The cost of this decision is
tracked honestly in `SECURITY_AUDIT.md` (see A8 below) rather than hidden.

---

### A2. BLE only for pairing/Wi-Fi handoff; Wi-Fi + Supabase for everything else

**Situation.** Early design could have used a persistent BLE connection for all app↔glasses
communication (common in wearable products).

**Decision.** BLE is scoped narrowly: nearby-device discovery, first-time pairing, and one-time
Wi-Fi credential handoff (`setup/hardware-integration/README.md`, "Connection model"). Normal
operation — status, alerts, history, settings, commands — goes over Wi-Fi via Supabase (plus a
same-Wi-Fi local HTTP link for lower latency).

**Why.** BLE throughput and range are poor for continuous status/event/history traffic, and a
permanent BLE dependency would mean the app breaks the moment the phone walks a few meters from
the glasses. Wi-Fi + Supabase scales to normal day-to-day use; BLE only has to work for the short
window when there is no Wi-Fi yet.

---

### A3. Local demo mode exists as a first-class mode, not a hack

**Situation.** Hardware was not always available/reachable (Gemini billing blocked, phone
unplugged, Pi in the field) while app development needed to continue.

**Decision.** `VITE_DEMO_MODE=true` runs the entire app against local sample data
(`src/lib/demoData.js`) with a scripted, realistic simulated walk (clear path → object ahead →
side obstacle → uneven ground), updating the same live guidance card and history that real
Pi/Supabase data would.

**Why.** This decouples UI/UX iteration from hardware availability entirely, and — because it
drives the exact same code paths as production data — it also serves as a demo mode for showing
the product to people without a live Pi present.

---

### A4. Gemini vision is on-demand / event-triggered only — never continuous

**Situation.** It would be technically possible to run Gemini description continuously for richer
"always know what's around you" behavior.

**Decision.** Locked as: (1) on-demand only, triggered by a phone button press, with an 8s
server-side cooldown, and (2) a separate, short, event-triggered obstacle-naming narration with
its own cooldown after a ToF obstacle alert. `CONTEXT_HANDOFF.md` explicitly records this as a
**locked product decision**, and `PLAN_gemini_describe.md` lists "continuous background
description" under **explicitly out of scope**.

**Why.** Cost (API calls aren't free and quota is already a real constraint — see A6), latency
(a live obstacle alert cannot wait on a cloud round-trip), and safety (the ToF/vibration loop must
never be gated on network/AI availability). This is reinforced structurally: `apply_fast_obstacle_pass.py`
exists specifically so the obstacle photo reaches the phone **without waiting for Gemini**, and
`apply_obstacle_gemini_race_fix.py` treats a busy/failed Gemini call as equivalent to "cooldown/skipped" —
i.e. the safety path degrades gracefully, it never blocks.

---

### A5. Voice output moved from the glasses speaker to the phone (Sarvam TTS)

**Situation.** The glasses have their own speaker (driven via `espeak`), but it was unreliable —
tracked as a dual-I²S-driver conflict between two sound card overlays.

**Problem, specifically.** `/boot/firmware/config.txt` had both `hifiberry-dac` and
`googlevoicehat-soundcard` overlays active. Per `CONTEXT_HANDOFF.md`, `hifiberry-dac` was
commented out to leave only `googlevoicehat-soundcard`, but there was **no logged confirmation**
that a clean-file playback test (`aplay Front_Center.wav`) actually sounded clear afterward — the
config change alone was not treated as a confirmed fix.

**Decision.** `apply_phone_audio_only.py` flips every spoken line (obstacle announcements, "path
clear", voice-command replies) to a phone alert instead of calling `espeak` on the glasses, behind
a `GLASSES_SPEAKER_ENABLED = False` flag meant to be flipped back only once the speaker hardware is
replaced and verified. `TOMORROW_PLAN.md` frames this explicitly as a two-path decision
("(A) actually test and confirm the speaker fix, glasses speaker becomes secondary" vs.
"(B) formally accept phone TTS as primary and stop chasing the glasses speaker") — and the codebase
shows path (B) was taken.

**Why.** "Always show real evidence before claiming success" is a standing rule in this project —
a config change is not a fix until it's heard working. Rather than block product progress on
uncertain hardware, phone TTS (Sarvam, `hi-IN`) was accepted as the primary voice output for the
current phase, with the glasses speaker explicitly deferred to a future hardware swap, not
abandoned.

---

### A6. Gemini quota (HTTP 429) → formal "ToF-only" Phase 1 exit path, instead of blocking on billing

**Situation.** `gemini_describe.py` calls started returning `HTTP 429` (quota exceeded) on the Pi,
blocking on-demand Describe/Read and obstacle-naming enrichment. This was diagnosed as a
billing/quota issue on the API key, not a code bug — and the fix (attaching billing) belongs to a
different person ("billing person"), not to whoever is writing code that day.

**Decision.** Rather than let the whole project stall on a third party's billing action,
`DEMO_WALK_SCRIPT.md` and `TOMORROW_PLAN.md` define a **formal ToF-only exit path**: Phase 1 can be
called exited on proof of distance detection + obstacle photo + haptic feedback alone (checklist
items A1–A5, A8–A10), with the Gemini-dependent items (A6 on-demand Read, A7 AI obstacle naming)
explicitly allowed to stay deferred until billing clears.

**Why.** This is a specific instance of a broader lesson: don't let a blocker that isn't yours to
fix (third-party billing) become a blocker on everything else that *is* yours to fix. The
`TOMORROW_PLAN.md` "parallel work" table exists for exactly this — app polish, the button service,
and the demo script all kept moving while Gemini was blocked.

---

### A7. Obstacle photo is captured and shown "instantly" — Gemini is decoupled from the safety path

**Situation.** If obstacle photo delivery to the phone waited on a Gemini description call, a
slow/failed AI call would delay or hide a safety-relevant obstacle photo.

**Decision.** `apply_fast_obstacle_pass.py` pushes the obstacle photo to the phone/History alert
queue immediately on detection; any Gemini naming happens as a separate, later, best-effort
enrichment (`apply_read_near_obstacle.py`, `apply_obstacle_phone_patch.py`). `apply_live_snapshot.py`
further caps how many full images are queued to the phone (only the newest 3 get full images;
older queue entries are text-only), to avoid an unbounded backlog if alerts fire faster than the
phone can consume them.

**Why.** Safety-relevant information (there is an obstacle, here's a photo, here's the distance)
must never be gated on a cloud AI call that might be slow, quota-limited, or down.

---

### A8. Security posture is documented honestly as "not production-safe yet"

**Situation.** A dedicated audit (`SECURITY_AUDIT.md`) found that although RLS is enabled on every
table, the actual policies use `using (true)` / `with check (true)` — meaning RLS exists in name
but provides no real isolation between devices or users. Anyone with the public Supabase URL and
anon key can read/write across all devices, and pairing codes are globally readable.

**Decision.** Rather than either ignore the finding or panic-fix it live against a real database,
it was written up as a formal, severity-ranked audit (Critical/High/Medium/Informational) with
concrete recommended SQL fixes (e.g. binding `owner_id` to `auth.jwt() ->> 'sub'`) left as a
deliberate follow-up, not yet applied.

**Why.** This is accepted as a known, documented tradeoff for a private prototype stage, not a
silent risk. The audit explicitly frames dashboard-only settings (things not visible from
repository files) as "verification items," not assumptions — a "don't claim what you haven't
checked" discipline that shows up elsewhere too (see B7).

---

## Part B — Concrete bugs hit in the field, and how they were fixed

Each of these is a real patch script in `setup/hardware-integration/apply_*.py`, chosen as a
deliberate workflow (see B8) precisely so each fix has a written record of the bug it addresses.

### B1. A single noisy ToF zone could report "3 cm" for a target 1.5 m away

**Situation.** The old `read_tof()` kept every sensor zone with `distance > 0` and took the
minimum across all 16 zones. A single crosstalk/noise zone (e.g. a reflection off the sensor's
own cover glass) could "win" against a real 1.5 m target, so the wearer heard "3 cm" for empty
space ahead.

**Fix (`apply_tof_status_filter.py`).** Only trust zones the sensor's own `target_status` marks as
valid; drop sub-floor readings that are almost always cover-glass crosstalk; require a second
nearby zone to confirm before trusting a very-close reading.

**Lesson.** Taking `min()` across noisy multi-zone sensor data without validity filtering is
exactly the kind of bug that only shows up on real hardware, not in code review — hence the
project's emphasis on live verification over "looks correct" review (see B7).

---

### B2. Distance was mislabeled by 10x ("320 mm spoken as 3.2 m" instead of 32 cm)

**Situation.** A distance-label calculation had a units bug that could report a distance an order
of magnitude wrong.

**Fix (`apply_distance_label_fix.py`).** Corrected the mm→cm/m conversion and label formatting,
and gated ToF reporting on the sensitivity setting.

**Lesson.** Unit-conversion bugs in safety-relevant spoken output are especially dangerous — a
10x-wrong distance is worse than no distance at all, because it's confidently wrong.

---

### B3. "Both sides" branch was silently swallowing all left/right obstacle alerts

**Situation.** The condition `if tof_left and tof_right:` was almost always true (both sensors
nearly always return *some* reading), so the "both" branch fired on every alert. The dedicated
left/right branches were effectively unreachable — an obstacle on one side alone still buzzed
both motors and announced "directly ahead".

**Fix (`apply_directional_alert_fix.py`).** Changed the decision to compare which side is actually
within the configured Settings range, with "both/ahead" reserved for a genuinely wide obstacle
both sensors see at a similar distance (introducing `TOF_SIDE_DIFFERENCE_MM` as the discriminator).

**Lesson.** A boolean condition that's *almost always* true in practice is a common way for a
"correct-looking" branch structure to hide a real bug — this one shipped and worked "fine" until
someone checked whether the left/right paths ever actually ran.

---

### B4. Sensor dropouts caused false "path clear" flapping and repeated alert bursts

**Situation.** Measured on a stationary rig: the obstacle side stayed "right" for an entire 30s
window, yet five separate "opening burst" alerts fired. The cause wasn't the side flipping — a ToF
reading briefly dropped out, the loop declared "path clear", reset `obstacle_active`, and the next
valid reading was treated as a brand-new obstacle.

**Fix (`apply_burst_floor_and_clear_hysteresis.py`).** Added a hard floor between opening bursts (no
code path can buzz faster than that), a longer stable-clear requirement before declaring an
obstacle gone, and a longer sample hold so one dropped frame isn't treated as "clear". Also gated
the per-frame debug print behind an env var, because it was flooding `journald` and rate-limiting
real events out of the log — a debugging problem that was actively hiding the bug being debugged.

**Related (`apply_realert_rate_limit.py`).** A second, related flicker: either ToF module could
drop in/out of validity frame-to-frame, so the "chosen side" itself flipped
(right → both → left → right), and *every flip* counted as a direction change and fired a fresh
alert burst — felt by the wearer as one continuous buzz. Fixed with a minimum re-alert gap (2.5s
for a side change, 1.0s when the obstacle is genuinely escalating/closing in), while still
alerting immediately on a genuinely new obstacle.

**Lesson.** Flaky sensor validity (not sensor *value*) was the repeat root cause of several
distinct-looking symptoms (false-clear, repeated bursts, side-flicker) — worth checking sensor
validity/dropout behavior specifically whenever haptic timing looks wrong, rather than re-tuning
thresholds on the assumed-good data.

---

### B5. ToF left/right wiring vs. software mapping was mirrored — twice

**Situation.** Field check on 2026-08-11 found the module physically wired to bus 3 sat on the
wearer's **right**, while code assumed it was left (and vice versa for bus 4) — every directional
cue (haptic side, spoken "left"/"right") was mirrored.

**Fix 1 (`apply_tof_side_swap.py`, 2026-08-11).** Swapped the bus→side mapping so bus 4 = LEFT,
bus 3 = RIGHT, without touching thresholds or zone filtering.

**Fix 2 (`apply_tof_side_reswap.py`, 2026-08-14).** A field report three days later found the
mapping was **backwards again** — bus 3 driving right-side alerts and bus 4 driving left. This
swapped it back to bus3=LEFT / bus4=RIGHT. Notably, this patch's doc-comment is explicit that it
only changes the *software label*, not the physical `dtoverlay=i2c-gpio` wiring in
`/boot/firmware/config.txt` — i.e. the wiring itself never changed between the two fixes.

**Lesson.** Left/right sensor-to-software mapping for a wearable is easy to get backwards and easy
to *re*-get-backwards (e.g. after handling/reassembly, or simply from confusion about which
convention "left" refers to — wearer's left vs. observer's left). Worth verifying against the
actual worn orientation each time the hardware is physically handled, not trusting a mapping that
was correct once.

---

### B6. Gemini's own "flash" model alias silently became unreliable

**Situation.** `gemini-flash-latest` currently resolves to `gemini-3.7-flash`, which was observed
overloaded and returning `HTTP 503 "high demand"` on roughly 64% of calls (4/11 ok) in a live
stress test.

**Fix.** Pinned the model to `gemini-3.6-flash` instead of the "latest" alias, after it scored
15/15 successful across two back-to-back test rounds on the same key/network. Documented directly
in `gemini_describe.py` with a dated comment explaining the measurement and warning to re-check if
object naming starts silently falling back again, since Google's "latest" alias keeps moving to
newer, more-contested models.

**Lesson.** "Use the `-latest` alias" is not a safe default when the vendor can silently point it
at a newer, less-stable model — pin to a specific model version once you've measured it, and leave
a dated note explaining the measurement so a future re-check isn't guesswork.

---

### B7. BlueZ's D-Bus advertising path could report "active" without actually transmitting

**Situation.** On the affected Raspberry Pi kernel, BlueZ's D-Bus extended-advertising
registration could report an active instance while not actually broadcasting a BLE advertisement —
meaning the phone app would never discover the glasses over BLE, with no error surfaced anywhere
in the normal D-Bus-based flow.

**Fix (`divyadrishti-adv-helper.c`).** A minimal native helper that opens the Linux Bluetooth MGMT
control socket directly and issues the legacy `MGMT_OP_ADD_ADVERTISING` (0x003e) command, bypassing
`bluetoothd`'s broken extended-advertising D-Bus path entirely. GATT/characteristics stay in the
existing Python provisioner service, untouched; the helper is supervised by the Python service and
removes its advertising instance on stop. The current 31-byte legacy advertising packet
deliberately omits a local name (space-constrained), so the app scans by service UUID instead.

**Lesson.** When a high-level system service (`bluetoothd`/D-Bus) reports success but the observable
real-world behavior (an actual BLE scan) says otherwise, dropping to the lowest-level API that
still does the same job (raw MGMT socket) is a reasonable, contained way to route around a
platform bug — as long as the workaround is scoped as narrowly as possible (advertising only, not
reimplementing GATT).

---

### B8. Uncommitted, unrelated changes kept piling up in the working tree

**Situation.** `CONTEXT_HANDOFF.md` records that the working tree accumulated many long-standing
unrelated uncommitted changes at once (Dashboard/Diagnostics/Settings/History redesigns, BLE
files, Supabase schema, `.env.example`, hotspot scripts) alongside whatever the current task's
changes were.

**Decision.** A standing git-hygiene rule: **never `git add .` or `git add -A`.** Only stage
task-relevant files or hunks — patch-stage (`git add -p`) or manual index construction when a file
mixes relevant and unrelated changes, and verify the isolated result (via a temp worktree + lint)
before committing.

**Why.** Committing everything in the tree at once would bundle unrelated, possibly
half-finished work into a single commit, making it hard to review, bisect, or revert any one
change independently.

---

### B9. Vite was transforming ~1800 icon files just to use a handful of them

**Situation.** Importing from `lucide-react` normally pulls from a barrel that re-exports the
entire icon set, which Vite has to discover/transform in dev and bundle in build — a real cost for
using maybe 25 icons.

**Fix (`src/lib/lucide.js` + `vite.config.js` alias).** A hand-picked barrel file that re-exports
only the ~25 icons actually used in the app, each imported directly from its own `.mjs` file, with
a Vite `resolve.alias` redirecting all `lucide-react` imports to this narrow file.

**Lesson.** For icon libraries shipped as thousands of individual modules behind one barrel export,
a hand-maintained narrow barrel plus a bundler alias is a simple, low-risk way to avoid paying a
whole-library cost for a handful of icons — worth doing early rather than after dev-server startup
time becomes a visible problem.

---

### B10. Android APK installs were slow and sometimes broke the Gradle daemon

**Situation.** Per the project's Android build rule (`.cursor/rules/android-apk-install.mdc`),
installs used to feel slow for simple UI-only changes: `vite`/`cap sync` could hang in some
environments or on cold starts (taking minutes), `gradlew clean`/`gradlew --stop` killed a warm
Gradle daemon, a full Capacitor sync ran even when only JS/React changed, and stopping daemons
could cause a subsequent package-install timeout.

**Fix (`scripts/android-fast-install.sh`, `npm run android:install`).** For JS/React-only changes:
`vite build` → `rsync` the built `dist/` straight into
`android/app/src/main/assets/public` (skipping the slower `cap sync`) → incremental
`./gradlew assembleDebug` (keeping the daemon warm) → `adb install -r`. The slow path
(`npm run android:build` + manual install) is reserved for when native Android/Java/plugin/
`capacitor.config` actually changed.

**Lesson.** Generic "just run the full build" tooling defaults are often much slower than
necessary for the common case (JS-only change) — worth building a fast path once the slow path's
actual bottleneck (full Capacitor sync, cold Gradle daemon) is identified, rather than tolerating
minutes-long install loops during iterative UI work.

---

### B11. A Hindi wake-word listener was planned but gated on a chip-compatibility check first

**Situation.** The intended compute for the glasses is a Raspberry Pi Zero W — a single-core
ARM1176JZF-S (ARMv6, no NEON). There's a known open upstream issue
(`Picovoice/porcupine#1414`) where Picovoice's ARM11/ARMv6 build crashes with `SIGILL` because the
shipped binary contains NEON instructions, and Picovoice's own response says that chip family is
no longer officially supported.

**Decision.** `DEPLOY_WAKE_WORD.md` is written as a "do not run any of this until told to" reference
doc, with **Step 0** being a harmless, changes-nothing compatibility check (run `pvporcupine.create`
with a built-in test keyword) that must print `OK` before trusting a trained custom Hindi model. If
it crashes with `SIGILL`, the explicit instruction is to stop and move wake-word detection to the
phone instead of the glasses.

**Why.** This is a case of catching a likely hardware-incompatibility problem *before* investing in
training a custom model and wiring up a service, by front-loading the cheapest possible test. It's
also a concrete example of the project's "don't run/deploy without an explicit go-ahead" discipline
applied to a whole feature, not just a single risky command.

---

## Part C — Process rules that exist because of specific past risk, not habit

These aren't arbitrary process — each maps to a concrete risk of breaking a live, worn, safety-
relevant device.

| Rule | Why it exists |
| --- | --- |
| Never edit `divya_drishti_final.py` on the Pi without showing the exact diff and getting approval first | It's the live main sensing/alerts loop on a device someone may be wearing; an unreviewed edit risks the safety loop itself |
| Never stop/restart the sensing service, activate the speaker/motors, or reboot the Pi without an explicit **in-the-moment** go-ahead (not a standing permission) | These actions have physical, immediate effects (buzzing, sound, a wearer suddenly losing sensing) — timing matters, so a general "you may do this" isn't sufficient consent |
| Never deploy `divya_drishti_final.RECONSTRUCTED.py` or `recovered-*.partial.py.txt` | These are recovered/partial reference copies, not verified-complete scripts — deploying them risks running an incomplete or subtly wrong version of the safety loop |
| Patch scripts (`apply_*.py`) instead of direct file edits, each reviewed as a diff before running on the Pi, several also writing a timestamped `.bak-before-*` backup of the file they're about to change | Turns every hardware-affecting change into something reviewable and revertible, and gives each fix a permanent, greppable written record of *what bug it addressed and why* — this document leans heavily on exactly those doc-comments |
| Always show real evidence before claiming success (log line, command output, or explicit user confirmation) — don't infer a fix worked | Directly motivated by the speaker "fix" (A5): a config change was made, but without a heard test, "should be fixed" was correctly not treated as "is fixed" |
| Never echo/paste the Gemini API key, Wi-Fi passwords, pairing codes, or SSH key material into chat/logs | Standard secret-handling hygiene, made explicit because SSH/Pi work naturally involves reading files and env vars that may contain these |
| No `git add .` / `git add -A`, ever | See B8 — the working tree routinely has unrelated in-flight changes that must not be swept into an unrelated commit |
