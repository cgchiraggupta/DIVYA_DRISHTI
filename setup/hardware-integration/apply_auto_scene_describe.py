#!/usr/bin/env python3
"""Auto scene-describe: no button — the glasses notice a new scene on their own.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Today, describe_frame() ("what's in front of me") only ever runs when the
companion phone sends the "describe" HTTP command — i.e. a human has to tap
"Describe" first. Obstacle *naming* already runs on its own off the ToF
sensors; this patch gives scene description the same treatment, driven by
the camera instead of a distance sensor.

Each detection_loop tick already captures a camera frame for CV obstacle
analysis (`analyze_frame`). This patch reuses that same frame — no extra
camera capture — to do a cheap local (no-Gemini) "did the scene change"
check:

1. Downscale + grayscale the frame.
2. Track frame-to-frame difference to detect when motion has *settled*
   (person stopped walking/turning) for SCENE_SETTLE_SECONDS. Without this,
   walking alone would look like constant "scene change" and spam Gemini.
3. Once settled, compare against the frame from the *last* auto-description.
   If it differs enough (SCENE_CHANGE_MIN_DIFF), that's a genuinely new
   scene worth describing.
4. Skip while paused. If an obstacle alert is currently active, do NOT fire
   yet, but also don't forget it — the "changed" condition stays true on the
   next tick, so it fires right after the obstacle clears instead of being
   dropped (obstacle safety audio always wins in the moment).
5. Calls gemini_describe.describe_scene_auto(), which shares one in-flight
   lock with every other Gemini call in this app (obstacle naming, manual
   Describe). If Gemini is already busy with one of those, this backs off
   and retries for a while in the background instead of stacking a second
   concurrent call — that stacking is what caused "multiple calls to Gemini
   getting stuck".

All thresholds below are a starting point, NOT measured on the real glasses
camera — expect to retune SCENE_SETTLE_MAX_DIFF / SCENE_CHANGE_MIN_DIFF /
SCENE_SETTLE_SECONDS after a real walk-around test.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/pi/divya_drishti_final.py")
text = TARGET.read_text(encoding="utf-8")
original = text

if "describe_scene_auto" in text:
    print("No changes needed (auto scene-describe already applied).")
    sys.exit(0)

# --- 1. import describe_scene_auto alongside the existing Gemini imports ---
OLD_IMPORT = "from gemini_describe import describe_frame, describe_obstacle, frame_to_jpeg_bytes\n"
NEW_IMPORT = (
    "from gemini_describe import (\n"
    "    describe_frame,\n"
    "    describe_obstacle,\n"
    "    describe_scene_auto,\n"
    "    frame_to_jpeg_bytes,\n"
    ")\n"
)
if OLD_IMPORT not in text:
    print(
        "ERROR: could not find the gemini_describe import line to extend "
        "(expected exactly one line importing describe_frame, describe_obstacle, "
        "frame_to_jpeg_bytes). Apply apply_obstacle_phone_patch.py / "
        "apply_read_near_obstacle.py first, or update this script's anchor.",
        file=sys.stderr,
    )
    sys.exit(1)
text = text.replace(OLD_IMPORT, NEW_IMPORT, 1)

# --- 2. constants + local scene-change detector + background worker ---
HELPERS = '''
# ---- Auto scene-describe: no button, camera decides on its own ----
# Downscaled grayscale mean-abs-diff thresholds. NOT measured on the real
# glasses camera yet — tune these against an actual walk-around test.
SCENE_DIFF_SIZE = (80, 60)         # downscale target: cheap to diff, still enough signal
SCENE_SETTLE_MAX_DIFF = 6.0        # frame-to-frame diff at/below this = "not moving right now"
SCENE_SETTLE_SECONDS = 0.8         # must stay settled this long before we trust it
SCENE_CHANGE_MIN_DIFF = 18.0       # settled frame vs last-described frame must differ at least this much
AUTO_DESCRIBE_MAX_WAIT_SECONDS = 20.0  # give up retrying a "busy" (Gemini in use) attempt after this long

_auto_describe_lock = threading.Lock()
_auto_describe_state = {
    "ref_gray": None,
    "prev_gray": None,
    "settled_since": None,
    "attempt_in_flight": False,
}


def _scene_gray(frame):
    small = cv2.resize(frame, SCENE_DIFF_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)


def _mean_abs_diff(gray_a, gray_b):
    return cv2.mean(cv2.absdiff(gray_a, gray_b))[0]


def _auto_describe_worker(frame, gray_candidate):
    """Background: ask Gemini to describe this frame, retrying through a
    busy Gemini slot (e.g. an obstacle-naming call in progress) for a while
    instead of giving up immediately — this is what makes an obstacle event
    "win" in the moment without silently dropping the scene description."""
    try:
        deadline = time.monotonic() + AUTO_DESCRIBE_MAX_WAIT_SECONDS
        while True:
            with state_lock:
                if state["paused"]:
                    return
            result = describe_scene_auto(frame)
            status = result.get("status")
            if status == "busy" and time.monotonic() < deadline:
                time.sleep(1.0)
                continue
            if status == "ok":
                text_hi = (result.get("text_hi") or "").strip()
                if text_hi:
                    publish_phone_alert({
                        "kind": "auto_describe",
                        "event_type": "voice_command",
                        "speak_hi": text_hi,
                        "text_hi": text_hi,
                        "image_jpeg_b64": result.get("image_jpeg_b64") or "",
                        "source": result.get("source"),
                        "speak": True,
                    })
                    queue_event("voice_command", {
                        "command": "auto_describe",
                        "source": "glasses_auto",
                        "status": "ok",
                        "speak_hi": text_hi,
                    })
                    with _auto_describe_lock:
                        _auto_describe_state["ref_gray"] = gray_candidate
                    print("[DESCRIBE] Auto scene-describe spoken")
            return
    except Exception as error:
        print(f"[DESCRIBE] Auto scene-describe failed: {error}")
    finally:
        with _auto_describe_lock:
            _auto_describe_state["attempt_in_flight"] = False


def maybe_auto_describe(frame, obstacle_active):
    """Call once per detection_loop tick with the frame already captured for
    CV — free/local on every tick, only calls Gemini when the scene has
    genuinely settled on something new. See apply_auto_scene_describe.py."""
    if frame is None:
        return
    try:
        gray = _scene_gray(frame)
    except Exception as error:
        print(f"[DESCRIBE] Auto scene-describe frame check skipped: {error}")
        return

    now = time.monotonic()
    with _auto_describe_lock:
        scene = _auto_describe_state
        if scene["ref_gray"] is None:
            scene["ref_gray"] = gray
            scene["prev_gray"] = gray
            return
        if scene["attempt_in_flight"]:
            scene["prev_gray"] = gray
            return

        frame_diff = _mean_abs_diff(gray, scene["prev_gray"])
        scene["prev_gray"] = gray

        if frame_diff <= SCENE_SETTLE_MAX_DIFF:
            if scene["settled_since"] is None:
                scene["settled_since"] = now
        else:
            scene["settled_since"] = None
            return

        if now - scene["settled_since"] < SCENE_SETTLE_SECONDS:
            return

        if _mean_abs_diff(gray, scene["ref_gray"]) < SCENE_CHANGE_MIN_DIFF:
            return

        if obstacle_active:
            # Obstacle safety audio wins right now. Leave ref_gray alone so
            # "changed" stays true and this fires on a later tick instead,
            # right after the obstacle clears.
            return

        scene["attempt_in_flight"] = True

    threading.Thread(
        target=_auto_describe_worker,
        args=(frame.copy(), gray),
        daemon=True,
    ).start()


'''

if "def maybe_auto_describe" not in text:
    marker = "def local_status_snapshot():\n"
    if marker not in text:
        print(
            "ERROR: could not find 'def local_status_snapshot():' to anchor "
            "the new helpers before.",
            file=sys.stderr,
        )
        sys.exit(1)
    text = text.replace(marker, HELPERS + marker, 1)

# --- 3. call the checker once per tick, right after the existing CV pass ---
OLD_CV_PASS = (
    "            if picam2 is not None:\n"
    "                with camera_lock:\n"
    "                    frame = picam2.capture_array()\n"
    "                cv_densities = analyze_frame(frame)\n"
)
NEW_CV_PASS = (
    "            if picam2 is not None:\n"
    "                with camera_lock:\n"
    "                    frame = picam2.capture_array()\n"
    "                cv_densities = analyze_frame(frame)\n"
    "                maybe_auto_describe(frame, obstacle_active)\n"
)
if "maybe_auto_describe(frame, obstacle_active)" not in text:
    if OLD_CV_PASS not in text:
        print(
            "ERROR: could not find the detection_loop camera-capture + "
            "analyze_frame block to hook the scene-change check into.",
            file=sys.stderr,
        )
        sys.exit(1)
    text = text.replace(OLD_CV_PASS, NEW_CV_PASS, 1)

if text == original:
    print("No changes needed (already patched).")
    sys.exit(0)

backup = TARGET.with_name(
    TARGET.name + f".bak-before-auto-scene-describe-{datetime.now():%Y%m%d-%H%M%S}"
)
backup.write_text(original, encoding="utf-8")
TARGET.write_text(text, encoding="utf-8")
print("Patched", TARGET)
print("Backup at", backup)
print("Bytes:", len(original), "->", len(text))
print(
    "\nNext: scp the updated gemini_describe.py alongside this file, then "
    "restart the sensing service (e.g. sudo systemctl restart "
    "divyadrishti-sensing.service) and test by walking the glasses to a new "
    "scene and standing still for ~1s."
)
