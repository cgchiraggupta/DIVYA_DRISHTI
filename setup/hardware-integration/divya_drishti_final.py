#!/usr/bin/env python3
"""
DIVYA DRISHTI - Phase 1 Final Integration
Hardware: RPi Zero, Dual VL53L5CX ToF (separate I2C buses),
          Camera, INMP441 Mic, MAX98357A Amp + Speaker,
          Dual Vibration Motors (Left/Right directional)
"""

import RPi.GPIO as GPIO
import cv2
import time
import threading
import subprocess
import os
import json
import queue
import random
import string
import sys
import hmac
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import smbus2
import speech_recognition as sr
import requests
from picamera2 import Picamera2
import base64
from gemini_describe import (
    describe_frame,
    describe_obstacle,
    describe_scene_auto,
    frame_to_jpeg_bytes,
)

try:
    from vl53l5cx_ctypes import VL53L5CX
    TOF_LIB_AVAILABLE = True
except ImportError:
    TOF_LIB_AVAILABLE = False

# ══════════════════════════════════════════
#  PIN CONFIGURATION
# ══════════════════════════════════════════
MOTOR_LEFT  = 12   # Pin 32
MOTOR_RIGHT = 13   # Pin 33

GPIO.setmode(GPIO.BCM)
GPIO.setup(MOTOR_LEFT,  GPIO.OUT)
GPIO.setup(MOTOR_RIGHT, GPIO.OUT)
GPIO.output(MOTOR_LEFT,  GPIO.LOW)
GPIO.output(MOTOR_RIGHT, GPIO.LOW)

# ══════════════════════════════════════════
#  THRESHOLDS
# ══════════════════════════════════════════
TOF_URGENT_MM   = 500
TOF_WARNING_MM  = 1000
TOF_CAUTION_MM  = 2000

# Persistent obstacles repeat as haptic-only guidance only while the wearer
# is still closing distance. Standing still after the opening burst stays quiet.
# Each interval is longer than its vibration pattern so motor requests cannot build up.
HAPTIC_REPEAT_SECONDS = {
    "single": 2.5,
    "double": 1.5,
    "rapid": 0.9,
}
# Motion heuristics from ToF (no IMU): cm-scale deltas over a short window.
HAPTIC_STATIONARY_TOLERANCE_MM = 80
HAPTIC_APPROACH_DELTA_MM = 50
HAPTIC_MOTION_WINDOW_S = 1.0
HAPTIC_OPENING_BURST_COUNT = 2
# Same-obstacle reminder buzz hard-stops this long after the opening burst.
# A genuinely new event (closer, more urgent, or a new side) still re-alerts
# through should_alert, independent of this cap. Live on the Pi since 2026-08-18.
HAPTIC_MAX_CONTINUOUS_SECONDS = 3.0
# Minimum gap before the opening burst may fire again for the same obstacle.
# Without this, a flickering sensor restarts the burst every few frames.
SIDE_REALERT_SECONDS = 2.5
# Side-only (left/right) caution/warning chatter is softer than ahead ("both").
# Urgent range (< TOF_URGENT_MM) never uses these — close calls stay as fast as today.
SIDE_ONLY_REALERT_SECONDS = 4.0
SIDE_ONLY_MOVED_CLOSER_MM = 450
URGENT_REALERT_SECONDS = 1.0
# No code path may restart the opening burst faster than this.
MIN_BURST_GAP_SECONDS = 2.0
# A dropped reading is not a clear path — require this much steady clear first.
CLEAR_CONFIRM_SECONDS = 3.0

# Both sensors within this spread means one wide obstacle straight ahead.
# A bigger gap means one side is genuinely nearer, so only that motor fires.
TOF_SIDE_DIFFERENCE_MM = 250

CV_HIGH = 0.020
CV_MED  = 0.010

# ══════════════════════════════════════════
#  SHARED STATE
# ══════════════════════════════════════════
state = {
    "running":         True,
    "paused":          False,
    "last_scene":      "starting up",
    "frame_count":     0,
    "tof_ok":          False,
    "last_alert_side": None,
    "last_alert_zone": None,
    "tof_left_ok":     False,
    "tof_right_ok":    False,
    "camera_ok":       False,
    "mic_ok":          True,
    "haptics_muted":   False,
    "device_id":       None,
    "pairing_code":    None,
}

state_lock = threading.Lock()
motor_lock = threading.Lock()
camera_lock = threading.Lock()
camera_holder = {"picam2": None}
pending_phone_alert = {"id": 0, "payload": None, "queue": []}
pending_phone_lock = threading.Lock()

# ══════════════════════════════════════════
#  SUPABASE DEVICE SYNC
#  The service credential is Pi-local only. Never copy this file or
#  ~/.divyadrishti/config.env into the companion app repository.
# ══════════════════════════════════════════
CONFIG_DIR = Path.home() / ".divyadrishti"
CONFIG_FILE = CONFIG_DIR / "config.env"
DEVICE_FILE = CONFIG_DIR / "device.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
# Events and safety status have different delivery requirements.  Status is a
# latest-value heartbeat, so it must never occupy an unbounded FIFO behind old
# events.  Keep only the newest status snapshot; events retain their order in a
# deliberately small queue.
sync_queue = queue.Queue(maxsize=50)
pending_status_lock = threading.Lock()
pending_status = None
pending_status_version = 0
status_sync_requested = threading.Event()
STATUS_MIN_INTERVAL_SECONDS = 10.0
LAST_SEEN_INTERVAL_SECONDS = 30.0

# A VL53L5CX may not have a new sample on every 300 ms loop.  Reuse a very
# recent sample so an alternating ready/not-ready cycle cannot turn one stable
# obstacle into a stream of left/right/ahead events.  Holding a close reading
# briefly is conservative: it delays clearing, not warning.
TOF_SAMPLE_HOLD_SECONDS = 1.5
# Per-frame ToF logging floods journald; enable only while debugging.
TOF_DEBUG = os.environ.get("DIVYA_TOF_DEBUG") == "1"
tof_sample_lock = threading.Lock()
tof_samples = {
    "left": {"value": None, "at": 0.0},
    "right": {"value": None, "at": 0.0},
}
LOCAL_LINK_PORT = 8765

# Runtime settings are intentionally narrow: they adjust early guidance but
# never disable close-range protection. These values are changed only by a
# cloud request that the Pi validates and acknowledges.
DEFAULT_RUNTIME_SETTINGS = {
    "sensitivity_mm": 2000,
    "feedback_mode": "both",
    "volume": 70,
    "vibration_intensity": 70,
}
SETTINGS_PI_VERSION = "settings-ack-v1"
SETTINGS_POLL_SECONDS = 4.0
settings_lock = threading.Lock()
runtime_settings = dict(DEFAULT_RUNTIME_SETTINGS)
settings_state = {
    "last_applied_request_id": None,
    "pending_ack": None,
}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def load_sync_config():
    values = {}
    try:
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"[SYNC] No config at {CONFIG_FILE}; cloud sync disabled.")
    return values

SYNC_CONFIG = load_sync_config()
SUPABASE_URL = SYNC_CONFIG.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = SYNC_CONFIG.get("SUPABASE_SERVICE_KEY", "")

def sync_enabled():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

def supabase_headers(prefer="return=minimal"):
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }

def validate_runtime_settings(values):
    """Validate a complete snapshot before it can change device behaviour."""
    try:
        sensitivity_mm = int(values["sensitivity_mm"])
        volume = int(values["volume"])
        vibration_intensity = int(values["vibration_intensity"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Settings must contain numeric range, volume and vibration values.") from error

    feedback_mode = str(values.get("feedback_mode", ""))
    if not 1000 <= sensitivity_mm <= 2500:
        raise ValueError("Detection range must be between 1000 and 2500 mm.")
    if feedback_mode not in ("audio", "vibration", "both"):
        raise ValueError("Feedback mode must be audio, vibration or both.")
    if not 20 <= volume <= 100:
        raise ValueError("Volume must be between 20 and 100.")
    if not 40 <= vibration_intensity <= 100:
        raise ValueError("Vibration intensity must be between 40 and 100.")

    return {
        "sensitivity_mm": sensitivity_mm,
        "feedback_mode": feedback_mode,
        "volume": volume,
        "vibration_intensity": vibration_intensity,
    }

def runtime_settings_snapshot():
    with settings_lock:
        return dict(runtime_settings)

def settings_state_snapshot():
    with settings_lock:
        return {
            "settings": dict(runtime_settings),
            "last_applied_request_id": settings_state["last_applied_request_id"],
            "pending_ack": dict(settings_state["pending_ack"]) if settings_state["pending_ack"] else None,
        }

def write_settings_state(snapshot):
    """Atomically persist validated settings and an acknowledgement retry."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_file = SETTINGS_FILE.with_name(f"{SETTINGS_FILE.name}.tmp")
    temporary_file.write_text(json.dumps(snapshot, sort_keys=True) + "\n")
    os.chmod(temporary_file, 0o600)
    os.replace(temporary_file, SETTINGS_FILE)
    os.chmod(SETTINGS_FILE, 0o600)

def store_settings_state(settings, last_request_id, pending_ack):
    """Persist first, then expose the new values to the sensing loop."""
    snapshot = {
        "settings": dict(settings),
        "last_applied_request_id": last_request_id,
        "pending_ack": dict(pending_ack) if pending_ack else None,
    }
    write_settings_state(snapshot)
    with settings_lock:
        runtime_settings.clear()
        runtime_settings.update(settings)
        settings_state["last_applied_request_id"] = last_request_id
        settings_state["pending_ack"] = dict(pending_ack) if pending_ack else None

def load_settings_state():
    """Restore the last known safe snapshot without making any output."""
    try:
        saved = json.loads(SETTINGS_FILE.read_text())
        settings = validate_runtime_settings(saved.get("settings", {}))
        pending_ack = saved.get("pending_ack")
        if pending_ack is not None and not isinstance(pending_ack, dict):
            raise ValueError("Pending acknowledgement has an invalid format.")
        store_settings_state(settings, saved.get("last_applied_request_id"), pending_ack)
        print("[SETTINGS] Restored locally confirmed settings.")
    except FileNotFoundError:
        # First boot uses the same values as the historical fixed thresholds.
        pass
    except (ValueError, json.JSONDecodeError, OSError) as error:
        print(f"[SETTINGS] Ignoring invalid local settings: {error}")

def call_settings_rpc(function_name, payload):
    """Call a service-only settings RPC without blocking the sensing loop."""
    try:
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/{function_name}",
            headers=supabase_headers("return=representation"),
            json=payload,
            timeout=5,
        )
        if not response.ok:
            print(f"[SETTINGS] {function_name} failed ({response.status_code})")
            return None
        result = response.json()
        if isinstance(result, list):
            return result[0] if result else None
        return result if isinstance(result, dict) else None
    except (requests.RequestException, ValueError) as error:
        print(f"[SETTINGS] {function_name} failed: {error}")
        return None

def acknowledge_settings_request(ack):
    result = call_settings_rpc("ack_device_setting_request", {
        "request_id_input": ack["request_id"],
        "success_input": ack["success"],
        "pi_version_input": SETTINGS_PI_VERSION,
        "error_code_input": ack.get("error_code"),
        "error_message_input": ack.get("error_message"),
    })
    return result is not None

def retry_pending_settings_ack():
    snapshot = settings_state_snapshot()
    ack = snapshot["pending_ack"]
    if not ack:
        return True
    if not acknowledge_settings_request(ack):
        return False
    store_settings_state(snapshot["settings"], snapshot["last_applied_request_id"], None)
    print("[SETTINGS] Acknowledged saved settings request.")
    return True

def prepare_settings_ack(request):
    """Persist an apply result before the acknowledgement can be retried."""
    request_id = str(request.get("id", ""))
    if not request_id:
        return None

    snapshot = settings_state_snapshot()
    try:
        settings = validate_runtime_settings(request)
    except ValueError as error:
        ack = {
            "request_id": request_id,
            "success": False,
            "error_code": "invalid_settings",
            "error_message": str(error),
        }
        store_settings_state(snapshot["settings"], snapshot["last_applied_request_id"], ack)
        return ack

    ack = {
        "request_id": request_id,
        "success": True,
        "error_code": None,
        "error_message": None,
    }
    if snapshot["last_applied_request_id"] != request_id:
        store_settings_state(settings, request_id, ack)
        print("[SETTINGS] Applied a new settings snapshot locally.")
    else:
        # The setting was already persisted before a previous network failure.
        store_settings_state(snapshot["settings"], request_id, ack)
    return ack

def settings_worker(stop_event):
    """Poll, apply and acknowledge cloud settings outside sensing/output work."""
    while not stop_event.is_set():
        try:
            if not sync_enabled() or not retry_pending_settings_ack():
                stop_event.wait(SETTINGS_POLL_SECONDS)
                continue

            with state_lock:
                device_id = state["device_id"]
            if not device_id:
                stop_event.wait(SETTINGS_POLL_SECONDS)
                continue

            request = call_settings_rpc(
                "claim_next_device_setting_request",
                {"device_id_input": device_id},
            )
            if request and request.get("state") == "applying":
                ack = prepare_settings_ack(request)
                if ack:
                    retry_pending_settings_ack()
        except Exception as error:
            # Never let a malformed cloud/local record kill obstacle sensing.
            print(f"[SETTINGS] Worker error: {error}")
        stop_event.wait(SETTINGS_POLL_SECONDS)

def random_pairing_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(6))

def speak_pairing_code(code):
    spaced = ". ".join(code)
    speak(f"Your pairing code is {spaced}. I repeat. {spaced}", blocking=True)

def register_device_if_needed():
    """Register once and keep the server-assigned device ID on the Pi."""
    if not sync_enabled():
        return None

    try:
        saved = json.loads(DEVICE_FILE.read_text())
        if saved.get("device_id") and saved.get("pairing_code"):
            with state_lock:
                state["device_id"] = saved["device_id"]
                state["pairing_code"] = saved["pairing_code"]
            print(f"[SYNC] Using registered device {saved['device_id']}")
            return saved
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    for _ in range(5):
        pairing_code = random_pairing_code()
        payload = {
            "name": "Divya Drishti",
            "pairing_code": pairing_code,
            "last_seen_at": utc_now(),
        }
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/devices",
                headers=supabase_headers("return=representation"),
                json=payload,
                timeout=6,
            )
            if response.ok:
                row = response.json()[0]
                saved = {"device_id": row["id"], "pairing_code": pairing_code}
                DEVICE_FILE.write_text(json.dumps(saved) + "\n")
                os.chmod(DEVICE_FILE, 0o600)
                with state_lock:
                    state["device_id"] = saved["device_id"]
                    state["pairing_code"] = pairing_code
                print(f"[SYNC] Registered device with pairing code {pairing_code}")
                speak_pairing_code(pairing_code)
                return saved
            print(f"[SYNC] Registration rejected ({response.status_code})")
        except requests.RequestException as error:
            print(f"[SYNC] Registration failed: {error}")
            break
    return None

def enqueue_sync(method, endpoint, payload, prefer="return=minimal"):
    """Queue an event write without allowing it to block sensing."""
    if not sync_enabled():
        return
    try:
        sync_queue.put_nowait((method, endpoint, payload, prefer))
    except queue.Full:
        # Status is coalesced separately, so a full FIFO now means cloud event
        # delivery is genuinely behind.  Do not pretend an oldest item was
        # removed when the new item is the one being dropped.
        print("[SYNC] Event queue full; dropping newest cloud event.")

def queue_status(current_alert, mode):
    """Coalesce the latest safety heartbeat for the cloud worker."""
    global pending_status, pending_status_version
    with state_lock:
        device_id = state["device_id"]
        payload = {
            "device_id": device_id,
            "battery_pct": None,  # No battery sensor is wired in Phase 1.
            "tof_left_ok": state["tof_left_ok"],
            "tof_right_ok": state["tof_right_ok"],
            "camera_ok": state["camera_ok"],
            "mic_ok": state["mic_ok"],
            "mode": mode,
            "current_alert": current_alert,
            "updated_at": utc_now(),
        }
    if not device_id:
        return
    with pending_status_lock:
        pending_status = {
            "device_id": device_id,
            "status": payload,
            "last_seen_at": payload["updated_at"],
        }
        pending_status_version += 1
        status_sync_requested.set()

def queue_event(event_type, detail):
    with state_lock:
        device_id = state["device_id"]
    if device_id:
        enqueue_sync("POST", "device_events", {
            "device_id": device_id,
            "event_type": event_type,
            "detail": detail,
        })

# ══════════════════════════════════════════
#  LOCAL COMPANION LINK (same Wi-Fi)
#  The phone can read nearby status even if cloud connectivity is slow. Commands
#  require the pairing code already held by the paired companion app.
# ══════════════════════════════════════════

def set_haptics_muted(muted):
    with state_lock:
        state["haptics_muted"] = bool(muted)


def publish_phone_alert(payload):
    """Queue a guidance payload for the companion app (photo + optional speak)."""
    with pending_phone_lock:
        pending_phone_alert["id"] = int(pending_phone_alert.get("id") or 0) + 1
        item = {
            **payload,
            "alert_id": pending_phone_alert["id"],
            "created_at": utc_now(),
        }
        pending_phone_alert["payload"] = item
        queue = pending_phone_alert.setdefault("queue", [])
        queue.append(item)
        if len(queue) > 8:
            del queue[:-8]
        snapshot = dict(item)
    return snapshot


def obstacle_phone_guidance_worker(frame, direction, distance_mm, event_type, image_jpeg_b64="", alert_id=None):
    """Background: Gemini labels NEAR obstacle only; phone already has the photo."""
    try:
        max_range_mm = runtime_settings_snapshot().get("sensitivity_mm", 2500)
        result = describe_obstacle(
            frame,
            direction=direction,
            distance_mm=distance_mm,
            max_range_mm=max_range_mm,
        )
        # "busy": another obstacle call is already in flight (Gemini allows
        # only one at a time now). The phone already has the instant distance
        # line, so just leave it — no point overwriting it with nothing.
        if result.get("status") in ("cooldown", "skipped", "busy"):
            return
        text_hi = (result.get("text_hi") or "").strip()
        if not text_hi:
            return
        if result.get("status") == "error":
            print(f"[DESCRIBE] Obstacle Gemini fallback, reason: {result.get('error')}")
        payload = {
            "kind": "obstacle",
            "event_type": event_type,
            "direction": direction,
            "distance_mm": distance_mm,
            "speak_hi": text_hi,
            "text_hi": text_hi,
            "image_jpeg_b64": "",
            "source": result.get("source"),
            "speak": True,
            "replaces_alert_id": alert_id,
        }
        publish_phone_alert(payload)
        queue_event(event_type, {
            "distance_mm": distance_mm,
            "direction": direction,
            "message": text_hi,
            "speak_hi": text_hi,
            "object_label": text_hi,
            "gemini": True,
        })
        print(f"[DESCRIBE] Obstacle Gemini ready ({result.get('source')})")
    except Exception as error:
        print(f"[DESCRIBE] Obstacle guidance failed: {error}")

def apply_settings_from_companion(payload):
    """Apply settings from the nearby companion immediately, then ack cloud if possible."""
    settings = validate_runtime_settings(payload)
    request_id = str(payload.get("request_id") or "").strip() or None
    snapshot = settings_state_snapshot()
    store_settings_state(settings, request_id or snapshot["last_applied_request_id"], None)
    print(
        f"[SETTINGS] Nearby companion applied sensitivity_mm="
        f"{settings['sensitivity_mm']} feedback={settings['feedback_mode']}"
    )

    # Best-effort: claim+ack the matching cloud request so app confirmation matches hardware.
    if not sync_enabled():
        return settings_state_snapshot()["settings"]

    with state_lock:
        device_id = state["device_id"]
    if not device_id:
        return settings_state_snapshot()["settings"]

    try:
        request = call_settings_rpc(
            "claim_next_device_setting_request",
            {"device_id_input": device_id},
        )
        if request and request.get("state") == "applying":
            ack = prepare_settings_ack(request)
            if ack:
                retry_pending_settings_ack()
    except Exception as error:
        print(f"[SETTINGS] Nearby cloud ack skipped: {error}")
    return settings_state_snapshot()["settings"]



# ---- Auto scene-describe: no button, camera decides on its own ----
# Ambient scan: once on camera/boot after the frame settles, then every
# ~5 minutes — not on every scene diff (that was too chatty). See
# DECISIONS_AND_LESSONS.md / 2026-08-18 note in apply_auto_scene_describe.py.
SCENE_DIFF_SIZE = (80, 60)         # downscale target: cheap to diff, still enough signal
SCENE_SETTLE_MAX_DIFF = 6.0        # frame-to-frame diff at/below this = "not moving right now"
SCENE_SETTLE_SECONDS = 0.8         # must stay settled this long before we trust it
SCENE_CHANGE_MIN_DIFF = 18.0       # skip only a literally-unchanged frame once the interval is due
AUTO_DESCRIBE_INTERVAL_SECONDS = 300.0  # ~5 minutes between unprompted ambient descriptions
AUTO_DESCRIBE_MAX_WAIT_SECONDS = 45.0  # retry through a busy Gemini slot long enough for a 35s call
# A normal indoor room almost always has *something* within the default 2.5m
# sensitivity range (a wall, furniture, a person), so obstacle_active can
# stay true nearly continuously. Without a cap, a genuinely new scene would
# never get described indoors. Obstacle safety still wins immediately and
# for this grace period, then auto-describe goes ahead anyway.
OBSTACLE_DEFER_MAX_SECONDS = 6.0

_auto_describe_lock = threading.Lock()
_auto_describe_state = {
    "ref_gray": None,
    "prev_gray": None,
    "settled_since": None,
    "attempt_in_flight": False,
    "obstacle_blocked_since": None,
    "last_spoken_at": None,
    "startup_describe_due": True,
}


def reset_auto_describe_schedule(*, reason: str = "camera") -> None:
    """Schedule one ambient describe as soon as the next frame settles."""
    with _auto_describe_lock:
        _auto_describe_state.update({
            "ref_gray": None,
            "prev_gray": None,
            "settled_since": None,
            "attempt_in_flight": False,
            "obstacle_blocked_since": None,
            "last_spoken_at": None,
            "startup_describe_due": True,
        })
    print(f"[DESCRIBE] Auto scene-describe scheduled on {reason} "
          f"(first settled frame, then every {AUTO_DESCRIBE_INTERVAL_SECONDS / 60:.0f} min)")


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
                        _auto_describe_state["last_spoken_at"] = time.monotonic()
                        _auto_describe_state["startup_describe_due"] = False
                    print("[DESCRIBE] Auto scene-describe spoken (next ambient describe in "
                          f"~{AUTO_DESCRIBE_INTERVAL_SECONDS / 60:.0f} min)")
            return
    except Exception as error:
        print(f"[DESCRIBE] Auto scene-describe failed: {error}")
    finally:
        with _auto_describe_lock:
            _auto_describe_state["attempt_in_flight"] = False


def maybe_auto_describe(frame, obstacle_active):
    """Call once per detection_loop tick — ambient describe on first settle
    after boot/camera-on, then every AUTO_DESCRIBE_INTERVAL_SECONDS."""
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

        if now - scene.get("last_debug_log_at", 0.0) > 2.0:
            scene["last_debug_log_at"] = now
            settled_for = (now - scene["settled_since"]) if scene["settled_since"] else 0.0
            diff_from_ref = _mean_abs_diff(gray, scene["ref_gray"])
            print(
                f"[DESCRIBE] Auto scene-describe check: frame_diff={frame_diff:.1f} "
                f"(settle<={SCENE_SETTLE_MAX_DIFF}) settled_for={settled_for:.1f}s "
                f"(need>={SCENE_SETTLE_SECONDS}) diff_from_ref={diff_from_ref:.1f} "
                f"(need>={SCENE_CHANGE_MIN_DIFF}) obstacle_active={obstacle_active} "
                f"startup_due={scene.get('startup_describe_due')}"
            )

        if scene["settled_since"] is None:
            return

        if now - scene["settled_since"] < SCENE_SETTLE_SECONDS:
            return

        startup_due = bool(scene.get("startup_describe_due"))
        last_spoken_at = scene.get("last_spoken_at")

        if not startup_due:
            if last_spoken_at is not None and now - last_spoken_at < AUTO_DESCRIBE_INTERVAL_SECONDS:
                return
            if (
                last_spoken_at is not None
                and _mean_abs_diff(gray, scene["ref_gray"]) < SCENE_CHANGE_MIN_DIFF
            ):
                return

        if obstacle_active and not startup_due:
            if scene["obstacle_blocked_since"] is None:
                scene["obstacle_blocked_since"] = now
                return
            if now - scene["obstacle_blocked_since"] < OBSTACLE_DEFER_MAX_SECONDS:
                return
        scene["obstacle_blocked_since"] = None
        if startup_due:
            scene["startup_describe_due"] = False

        scene["attempt_in_flight"] = True

    threading.Thread(
        target=_auto_describe_worker,
        args=(frame.copy(), gray),
        daemon=True,
    ).start()


def local_status_snapshot():
    with state_lock:
        snapshot = {
            "device_id": state["device_id"],
            "available": True,
            "paused": state["paused"],
            "haptics_muted": state.get("haptics_muted", False),
            "last_scene": state["last_scene"],
            "tof_left_ok": state["tof_left_ok"],
            "tof_right_ok": state["tof_right_ok"],
            "camera_ok": state["camera_ok"],
            "mic_ok": state["mic_ok"],
            "updated_at": utc_now(),
            "settings": runtime_settings_snapshot(),
        }
    with pending_phone_lock:
        queue = list(pending_phone_alert.get("queue") or [])
        # Only ship the newest few to the phone (full images). Older entries text-only.
        slim = []
        newest = list(reversed(queue[-3:]))
        for index, item in enumerate(newest):
            copy = dict(item)
            if index >= 2:
                copy["image_jpeg_b64"] = ""
            slim.append(copy)
        slim.reverse()
        snapshot["phone_alert"] = pending_phone_alert.get("payload")
        snapshot["phone_alerts"] = slim
    return snapshot

def local_pairing_code_matches(headers):
    with state_lock:
        expected = state["pairing_code"] or ""
    received = headers.get("X-Divya-Pairing-Code", "").strip().upper()
    return bool(expected and received and hmac.compare_digest(expected.upper(), received))

class LocalLinkServer(ThreadingHTTPServer):
    allow_reuse_address = True

class LocalLinkHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[LOCAL] {self.address_string()} - {fmt % args}")

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "https://localhost")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Divya-Pairing-Code")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_json(204, {})

    def do_GET(self):
        if self.path == "/v1/health":
            self.send_json(200, {"name": "Divya Drishti", "available": True})
            return
        if self.path == "/v1/settings":
            if not local_pairing_code_matches(self.headers):
                self.send_json(401, {"error": "Pairing required"})
                return
            snap = settings_state_snapshot()
            self.send_json(200, {
                "status": "ok",
                "settings": snap["settings"],
                "last_applied_request_id": snap["last_applied_request_id"],
            })
            return
        if self.path != "/v1/status":
            self.send_json(404, {"error": "Not found"})
            return
        if not local_pairing_code_matches(self.headers):
            self.send_json(401, {"error": "Pairing required"})
            return
        self.send_json(200, local_status_snapshot())

    def do_POST(self):
        if self.path not in ("/v1/command", "/v1/settings"):
            self.send_json(404, {"error": "Not found"})
            return
        if not local_pairing_code_matches(self.headers):
            self.send_json(401, {"error": "Pairing required"})
            return
        try:
            size = min(int(self.headers.get("Content-Length", "0")), 2048)
            payload = json.loads(self.rfile.read(size) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid request"})
            return

        if self.path == "/v1/settings":
            try:
                settings = apply_settings_from_companion(payload)
            except ValueError as error:
                self.send_json(400, {"status": "error", "error": str(error)})
                return
            except Exception as error:
                print(f"[SETTINGS] Nearby apply failed: {error}")
                self.send_json(500, {"status": "error", "error": "Could not apply settings"})
                return
            self.send_json(200, {
                "status": "ok",
                "settings": settings,
                "updated_at": utc_now(),
            })
            return

        command = str(payload.get("command", "")).lower()
        if command not in ("pause", "resume", "describe", "read", "unmute_haptics"):
            self.send_json(400, {"error": "Unsupported command"})
            return

        if command in ("describe", "read"):
            picam2 = camera_holder.get("picam2")
            if picam2 is None:
                self.send_json(503, {
                    "status": "error",
                    "text_hi": "कैमरा उपलब्ध नहीं है।",
                    "source": "fallback",
                })
                return
            set_haptics_muted(True)
            try:
                with camera_lock:
                    frame = picam2.capture_array()
                result = describe_frame(frame, include_image=True, mode=command)
            except Exception as error:
                print(f"[DESCRIBE] Failed: {error}")
                set_haptics_muted(False)
                self.send_json(500, {
                    "status": "error",
                    "text_hi": "अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।",
                    "source": "fallback",
                    "error": str(error),
                })
                return
            if result.get("text_hi"):
                publish_phone_alert({
                    "kind": command,
                    "event_type": "voice_command",
                    "speak_hi": result["text_hi"],
                    "text_hi": result["text_hi"],
                    "image_jpeg_b64": result.get("image_jpeg_b64") or "",
                    "source": command,
                    # Companion already speaks the HTTP result; don't double-TTS.
                    "speak": False,
                })
            # Keep motors quiet while phone speaks; companion can resume via resume/describe-done.
            # Auto-unmute after 20s as a safety net.
            def _unmute_later():
                time.sleep(20)
                set_haptics_muted(False)
            threading.Thread(target=_unmute_later, daemon=True).start()
            queue_event("voice_command", {
                "command": command,
                "source": "companion_app",
                "status": result.get("status"),
                "speak_hi": result.get("text_hi"),
            })
            self.send_json(200, result)
            return

        if command == "unmute_haptics":
            set_haptics_muted(False)
            self.send_json(200, local_status_snapshot())
            return

        with state_lock:
            state["paused"] = command == "pause"
            if command == "resume":
                state["haptics_muted"] = False
        queue_event("voice_command", {"command": command, "source": "companion_app"})
        self.send_json(200, local_status_snapshot())

def start_local_link(stop_event):
    try:
        server = LocalLinkServer(("0.0.0.0", LOCAL_LINK_PORT), LocalLinkHandler)
    except OSError as error:
        print(f"[LOCAL] Could not start companion link: {error}")
        return None

    def serve():
        print(f"[LOCAL] Companion link ready on port {LOCAL_LINK_PORT}")
        server.timeout = 0.5
        while not stop_event.is_set():
            server.handle_request()
        server.server_close()

    threading.Thread(target=serve, daemon=True).start()
    return server

def send_sync_request(method, endpoint, payload, prefer="return=minimal"):
    """Perform one bounded cloud request and report success to the caller."""
    try:
        response = requests.request(
            method,
            f"{SUPABASE_URL}/rest/v1/{endpoint}",
            headers=supabase_headers(prefer),
            json=payload,
            timeout=4,
        )
        if response.ok:
            return True
        print(f"[SYNC] {method} {endpoint} failed ({response.status_code})")
    except requests.RequestException as error:
        print(f"[SYNC] {method} {endpoint} failed: {error}")
    return False

def pending_status_snapshot():
    """Take a versioned view without discarding a newer safety heartbeat."""
    with pending_status_lock:
        return pending_status_version, pending_status

def mark_status_sent(version):
    """Clear only the snapshot that was actually delivered."""
    global pending_status
    with pending_status_lock:
        if pending_status_version == version:
            pending_status = None
            status_sync_requested.clear()

def status_sync_worker(stop_event):
    """Publish latest safety state independently of append-only events."""
    last_status_sent = 0.0
    last_seen_sent = 0.0
    while not stop_event.is_set() or status_sync_requested.is_set():
        status_sync_requested.wait(timeout=0.5)
        version, status = pending_status_snapshot()
        if status is None:
            continue

        remaining = STATUS_MIN_INTERVAL_SECONDS - (time.monotonic() - last_status_sent)
        if remaining > 0:
            stop_event.wait(remaining)
            version, status = pending_status_snapshot()
            if status is None:
                continue

        delivered = send_sync_request(
            "POST",
            "device_status?on_conflict=device_id",
            status["status"],
            "resolution=merge-duplicates,return=minimal",
        )
        if not delivered:
            # Retain this one latest snapshot. A short retry avoids stale
            # state without allowing a network outage to grow a memory queue.
            stop_event.wait(2.0)
            continue

        last_status_sent = time.monotonic()
        if last_status_sent - last_seen_sent >= LAST_SEEN_INTERVAL_SECONDS:
            if send_sync_request(
                "PATCH",
                f"devices?id=eq.{status['device_id']}",
                {"last_seen_at": status["last_seen_at"]},
            ):
                last_seen_sent = last_status_sent
        mark_status_sent(version)

def sync_worker(stop_event):
    """Append-only cloud events stay off sensing and voice threads."""
    while not stop_event.is_set() or not sync_queue.empty():
        try:
            method, endpoint, payload, prefer = sync_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            send_sync_request(method, endpoint, payload, prefer)
        finally:
            sync_queue.task_done()

# ══════════════════════════════════════════
#  AUDIO
# ══════════════════════════════════════════
# Glasses speaker is unreliable, so the phone is the only guidance voice.
# Flip to True only after the speaker hardware is replaced and verified.
GLASSES_SPEAKER_ENABLED = False


def speak(text, blocking=False, volume=None):
    print(f"[AUDIO] {text}")
    try:
        publish_phone_alert({
            "kind": "announcement",
            "event_type": "system",
            "direction": None,
            "distance_mm": None,
            "speak_hi": text,
            "text_hi": text,
            "image_jpeg_b64": "",
            "source": "glasses_voice",
            "speak": True,
        })
    except Exception as error:
        print(f"[AUDIO] Could not hand speech to the phone: {error}")
    if not GLASSES_SPEAKER_ENABLED:
        return
    env = {**os.environ, "AUDIODEV": "plughw:0,0"}
    args = ["espeak", "-s", "140", "-v", "en", text]
    if volume is not None:
        args[1:1] = ["-a", str(max(20, min(100, int(volume))))]
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    if blocking:
        subprocess.call(args, **kwargs)
    else:
        subprocess.Popen(args, **kwargs)

# ══════════════════════════════════════════
#  VIBRATION (dual motor, directional)
# ══════════════════════════════════════════
def vibrate(side, duration=0.3, intensity=100):
    with motor_lock:
        pwm_l = GPIO.PWM(MOTOR_LEFT,  1000)
        pwm_r = GPIO.PWM(MOTOR_RIGHT, 1000)

        if side in ("left",  "both"): pwm_l.start(intensity)
        if side in ("right", "both"): pwm_r.start(intensity)

        time.sleep(duration)
        pwm_l.stop()
        pwm_r.stop()
        GPIO.output(MOTOR_LEFT,  GPIO.LOW)
        GPIO.output(MOTOR_RIGHT, GPIO.LOW)

def vibrate_pattern(side, pattern, configured_intensity=None):
    # The historical 70% app default preserves the existing motor patterns.
    # Strong urgent feedback cannot be reduced below a safety floor.
    uses_live_intensity = configured_intensity is not None
    configured = 70 if configured_intensity is None else max(40, min(100, int(configured_intensity)))

    def scaled(base, minimum=40):
        return max(minimum, min(100, round(base * configured / 70)))

    if pattern == "rapid":
        # Urgent is still one distinct warning, not a continuous buzz.
        intensity = max(85, configured) if uses_live_intensity else scaled(100, 85)
        vibrate(side, 0.35, intensity)
    elif pattern == "double":
        intensity = configured if uses_live_intensity else scaled(100)
        vibrate(side, 0.2, intensity)
        time.sleep(0.1)
        vibrate(side, 0.2, intensity)
    elif pattern == "single":
        intensity = configured if uses_live_intensity else scaled(70)
        vibrate(side, 0.3, intensity)
    elif pattern == "pulse":
        vibrate(side, 0.5, scaled(80))

def deliver_haptic_burst(side, pattern, count=HAPTIC_OPENING_BURST_COUNT):
    """Two (or count) haptic pulses, then stop — used for the opening warning."""
    def run():
        for index in range(max(1, int(count))):
            deliver_alert(side, pattern, None)
            if index + 1 < count:
                # Gap longer than one rapid pulse so the wearer feels two distinct hits.
                time.sleep(0.55 if pattern == "rapid" else 0.4)
    threading.Thread(target=run, daemon=True).start()


def deliver_alert(side, pattern, message):
    """Use the confirmed runtime feedback settings for future guidance only."""
    settings = runtime_settings_snapshot()
    feedback_mode = settings["feedback_mode"]
    with state_lock:
        haptics_muted = state.get("haptics_muted", False)
    # Glasses speaker is weak — still attempt audio if configured, but never
    # vibrate while the phone is speaking a describe/read result.
    if message and feedback_mode in ("audio", "both") and not haptics_muted:
        speak(message, volume=settings["volume"])
    if side and pattern and feedback_mode in ("vibration", "both") and not haptics_muted:
        vibrate_pattern(side, pattern, settings["vibration_intensity"])

# ══════════════════════════════════════════
#  TOF SENSORS (dual, separate I2C buses)
# ══════════════════════════════════════════
def init_tof_sensors():
    """
    Sensor on bus 3 (GPIO23/24, Pin 16/18) faces the wearer's LEFT.
    Sensor on bus 4 (GPIO17/27, Pin 11/13) faces the wearer's RIGHT.
    Field report 2026-08-14: the previous mapping had this backwards again
    (left bus was driving the right-side alert/vibration) — swapped back.
    Independent buses, both at default address 0x29 - no conflict.
    """
    if not TOF_LIB_AVAILABLE:
        print("[TOF] Library not installed, skipping ToF sensors.")
        return None, None, None, None

    def init_sensor(label, bus_number):
        bus = None
        try:
            print(f"[TOF] Opening bus {bus_number} (sensor {label})...")
            bus = smbus2.SMBus(bus_number)
            for attempt in range(3):
                try:
                    sensor = VL53L5CX(i2c_dev=bus)
                    sensor.set_resolution(4 * 4)
                    sensor.start_ranging()
                    print(f"[TOF] Sensor {label} active on bus {bus_number} (attempt {attempt+1})")
                    return sensor, bus
                except Exception as error:
                    print(f"[TOF] Sensor {label} attempt {attempt+1} failed: {error}")
                    time.sleep(1.0)
        except Exception as error:
            print(f"[TOF] Sensor {label} bus unavailable: {error}")

        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass
        return None, None

    tof1, bus3 = init_sensor("LEFT", 3)
    tof2, bus4 = init_sensor("RIGHT", 4)

    with state_lock:
        state["tof_ok"] = bool(tof1 or tof2)
        state["tof_left_ok"] = tof1 is not None
        state["tof_right_ok"] = tof2 is not None

    if tof1 and tof2:
        print("[TOF] Dual sensors active.")
    elif tof1:
        print("[TOF] Left sensor active; right sensor unavailable.")
    elif tof2:
        print("[TOF] Right sensor active; left sensor unavailable.")
    else:
        print("[TOF] No sensors available. Falling back to camera-only detection.")

    return tof1, tof2, bus3, bus4

# VL53L5CX marks each zone with a ranging status. 5 = valid, 9 = valid but a
# weaker/half-rate signal. Anything else (4 = below noise, 255 = no target,
# 6/12 = wrap-around) is noise and must never become an obstacle distance.
TOF_VALID_STATUSES = (5, 9)
# Below this the return is almost always cover-glass / enclosure crosstalk.
TOF_MIN_VALID_MM = 60
# A very close reading in exactly one zone is treated as a flyer until a
# neighbouring zone agrees, which is what turned 1.5 m targets into "3 cm".
TOF_CONFIRM_BELOW_MM = 300
TOF_CONFIRM_SPREAD_MM = 120


def closest_valid_zone(sensor):
    """Closest trustworthy zone distance in mm, or None when nothing is valid."""
    data = sensor.get_data()
    distances = list(data.distance_mm[0])[:16]
    statuses = list(data.target_status[0])[:16]
    good = sorted(
        distance
        for distance, status in zip(distances, statuses)
        if status in TOF_VALID_STATUSES and distance >= TOF_MIN_VALID_MM
    )
    if not good:
        return None

    closest = good[0]
    if closest < TOF_CONFIRM_BELOW_MM:
        agreeing = sum(1 for d in good if d - closest <= TOF_CONFIRM_SPREAD_MM)
        if agreeing < 2:
            remaining = [d for d in good if d - closest > TOF_CONFIRM_SPREAD_MM]
            return remaining[0] if remaining else None
    return closest


def read_tof(tof1, tof2):
    """Return stable recent ToF distances, using only sensor-validated zones."""
    if tof1 is None and tof2 is None:
        return None, None
    d_left, d_right = None, None
    if tof1 is not None:
        try:
            if tof1.data_ready():
                d_left = closest_valid_zone(tof1)
        except Exception:
            pass
    if tof2 is not None:
        try:
            if tof2.data_ready():
                d_right = closest_valid_zone(tof2)
        except Exception:
            pass

    # data_ready() can alternate between the two independent sensor buses. A
    # missing sample does not mean an obstacle disappeared; retain a valid
    # sample only for this short bounded window.
    now = time.monotonic()
    with tof_sample_lock:
        if d_left is not None:
            tof_samples["left"] = {"value": d_left, "at": now}
        elif now - tof_samples["left"]["at"] <= TOF_SAMPLE_HOLD_SECONDS:
            d_left = tof_samples["left"]["value"]

        if d_right is not None:
            tof_samples["right"] = {"value": d_right, "at": now}
        elif now - tof_samples["right"]["at"] <= TOF_SAMPLE_HOLD_SECONDS:
            d_right = tof_samples["right"]["value"]
    return d_left, d_right

# ══════════════════════════════════════════
#  CAMERA + CV
# ══════════════════════════════════════════
def init_camera():
    print("[CAMERA] Initializing...")
    try:
        picam2 = Picamera2()
        picam2.configure(
            picam2.create_still_configuration(main={"size": (320, 240)})
        )
        picam2.start()
        time.sleep(2)
        with state_lock:
            state["camera_ok"] = True
        print("[CAMERA] Ready.")
        return picam2
    except Exception as error:
        # Known hardware TODO: Picamera2 IndexError here means libcamera found
        # no camera. Keep ToF/audio/vibration running until ribbon/config is fixed.
        with state_lock:
            state["camera_ok"] = False
        print(f"[CAMERA] Unavailable ({error}); continuing without camera.")
        return None

def analyze_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    left   = gray[:, :w//3]
    center = gray[:, w//3:2*w//3]
    right  = gray[:, 2*w//3:]
    bottom = gray[2*h//3:, :]

    def density(zone, lo=50, hi=150):
        return cv2.Canny(zone, lo, hi).mean() / 255.0

    return {
        "left":   density(left),
        "center": density(center),
        "right":  density(right),
        "floor":  density(bottom, 30, 100),
    }

# ══════════════════════════════════════════
#  OBSTACLE DECISION LOGIC (ToF primary, CV secondary)
# ══════════════════════════════════════════
def decide_alert(tof_left, tof_right, cv_densities):
    """Prefer ToF (accurate, real distance) over CV (heuristic) when available."""
    caution_distance = runtime_settings_snapshot()["sensitivity_mm"]

    # ── ToF path ──
    if tof_left is not None or tof_right is not None:
        # Always respect Settings range first — never alert beyond sensitivity_mm.
        left_blocked = tof_left is not None and tof_left < caution_distance
        right_blocked = tof_right is not None and tof_right < caution_distance

        if not left_blocked and not right_blocked:
            return (None, None, "path clear")

        if left_blocked and right_blocked:
            if abs(tof_left - tof_right) <= TOF_SIDE_DIFFERENCE_MM:
                side, closest = "both", min(tof_left, tof_right)
            elif tof_left < tof_right:
                side, closest = "left", tof_left
            else:
                side, closest = "right", tof_right
        elif left_blocked:
            side, closest = "left", tof_left
        else:
            side, closest = "right", tof_right

        dist_cm = max(1, int(round(closest / 10.0)))

        if side == "both":
            if closest < TOF_URGENT_MM:
                return ("both", "rapid", f"obstacle directly ahead, {dist_cm} centimeters")
            if closest < TOF_WARNING_MM:
                return ("both", "double", f"obstacle ahead, {dist_cm} centimeters")
            return ("both", "single", f"object nearby ahead, {dist_cm} centimeters")

        if closest < TOF_URGENT_MM:
            return (side, "rapid", f"obstacle very close on {side}, {dist_cm} centimeters")
        if closest < TOF_WARNING_MM:
            return (side, "double", f"obstacle on {side}, {dist_cm} centimeters")
        return (side, "single", f"object nearby on {side}, {dist_cm} centimeters")


    # ── CV fallback path ──
    d = cv_densities
    if d["center"] > CV_HIGH:
        return ("both", "rapid", "obstacle directly ahead")
    if d["center"] > CV_MED:
        return ("both", "double", "obstacle ahead")
    if d["left"] > CV_HIGH:
        return ("left", "double", "obstacle on left")
    if d["right"] > CV_HIGH:
        return ("right", "double", "obstacle on right")
    if d["floor"] > CV_HIGH:
        return ("both", "rapid", "uneven ground ahead")
    return (None, None, "path clear")

def event_type_for(side, message):
    message = (message or "").lower()
    if "path clear" in message:
        return "path_clear"
    if "uneven" in message:
        return "uneven_ground"
    if side == "left":
        return "obstacle_left"
    if side == "right":
        return "obstacle_right"
    return "obstacle_ahead"

# ══════════════════════════════════════════
#  DETECTION LOOP (background thread)
# ══════════════════════════════════════════
def detection_loop(picam2, tof1, tof2, stop_event):
    print("[DETECT] Detection loop started.")
    last_alert = 0
    last_alert_distance = None
    last_alert_side = None
    last_alert_pattern = None
    last_alert_message = None
    obstacle_active = False
    clear_since = None
    last_status_sync = 0
    # After the opening double-buzz: quiet if standing, repeat only while approaching.
    haptic_quiet = False
    approach_active = False
    opening_burst_at = None
    distance_samples = []

    while not stop_event.is_set():
        with state_lock:
            if state["paused"]:
                time.sleep(0.5)
                continue

        try:
            frame = None
            if picam2 is not None:
                with camera_lock:
                    frame = picam2.capture_array()
                cv_densities = analyze_frame(frame)
            else:
                # ToF remains the primary source while camera hardware is offline.
                cv_densities = {"left": 0, "center": 0, "right": 0, "floor": 0}
            tof_left, tof_right = read_tof(tof1, tof2)

            side, pattern, message = decide_alert(tof_left, tof_right, cv_densities)
            if TOF_DEBUG:
                print(f"[DEBUG] tof_left={tof_left} tof_right={tof_right} -> side={side} pattern={pattern} msg={message}")



            with state_lock:
                state["frame_count"] += 1
                fc = state["frame_count"]
                state["last_scene"] = message or "path clear"

            if fc % 10 == 0:
                tof_str = f"TOF L={tof_left} R={tof_right}" if (tof1 or tof2) else "TOF n/a"
                print(f"[DETECT] Frame {fc}: {tof_str} | "
                      f"CV L={cv_densities['left']:.3f} "
                      f"C={cv_densities['center']:.3f} "
                      f"R={cv_densities['right']:.3f} | {message}")

            now = time.time()
            event_type = event_type_for(side, message)
            mode = "tof" if (tof1 is not None or tof2 is not None) else "camera_fallback"
            # A five-second cloud heartbeat is frequent enough for the
            # companion while leaving bandwidth for meaningful activity events.
            if now - last_status_sync >= 5.0:
                queue_status(event_type, mode)
                last_status_sync = now
            if side is not None:
                # Cane, not tour guide: buzz when closing in or already close.
                # While an obstacle remains, repeat only its directional haptic.
                clear_since = None
                distance_mm = min(d for d in (tof_left, tof_right) if d is not None) \
                    if tof_left is not None or tof_right is not None else None
                severity = {"single": 1, "double": 2, "rapid": 3}.get(pattern, 0)
                previous_severity = {"single": 1, "double": 2, "rapid": 3}.get(last_alert_pattern, 0)
                direction_changed = obstacle_active and side != last_alert_side
                escalated = obstacle_active and severity > previous_severity
                # Ahead ("both") still re-alerts after a 30cm close-in.
                # Pure side obstacles need 45cm, but only outside urgent range —
                # under TOF_URGENT_MM, side stays as responsive as ahead.
                side_only = side in ("left", "right")
                in_urgent = pattern == "rapid" or (
                    distance_mm is not None and distance_mm < TOF_URGENT_MM
                )
                closer_delta_mm = (
                    SIDE_ONLY_MOVED_CLOSER_MM if side_only and not in_urgent else 300
                )
                moved_closer = (
                    obstacle_active and distance_mm is not None and
                    last_alert_distance is not None and
                    distance_mm <= last_alert_distance - closer_delta_mm
                )
                if distance_mm is not None:
                    distance_samples.append((now, distance_mm))
                    distance_samples[:] = [
                        sample for sample in distance_samples
                        if now - sample[0] <= HAPTIC_MOTION_WINDOW_S
                    ]
                approaching_now = False
                stationary_now = False
                if len(distance_samples) >= 2:
                    oldest_d = distance_samples[0][1]
                    newest_d = distance_samples[-1][1]
                    approaching_now = newest_d <= oldest_d - HAPTIC_APPROACH_DELTA_MM
                    stationary_now = abs(newest_d - oldest_d) <= HAPTIC_STATIONARY_TOLERANCE_MM
                since_burst = (now - opening_burst_at) if opening_burst_at is not None else None
                if since_burst is not None and since_burst >= HAPTIC_MAX_CONTINUOUS_SECONDS:
                    # Hard stop: this obstacle has already warned. Staying near
                    # or slowly drifting toward it must not buzz indefinitely.
                    approach_active = False
                    haptic_quiet = True
                elif since_burst is not None and since_burst >= 0.8:
                    if approaching_now:
                        approach_active = True
                        haptic_quiet = False
                    elif stationary_now:
                        approach_active = False
                        haptic_quiet = True
                reminder_interval = HAPTIC_REPEAT_SECONDS.get(pattern, 2.5)
                # Side-only caution/warning reminders are 1.5x slower than ahead.
                # Rapid (urgent < 50cm) is never stretched — close calls keep pace.
                if side_only and not in_urgent:
                    reminder_interval *= 1.5
                haptic_reminder = (
                    obstacle_active
                    and approach_active
                    and not haptic_quiet
                    and (now - last_alert) >= reminder_interval
                )
                seconds_since_alert = now - last_alert
                urgent_change = escalated or moved_closer
                # Direction flips onto left/right wait longer before re-speaking,
                # except when the new reading is already urgent-range.
                side_realert_seconds = (
                    SIDE_ONLY_REALERT_SECONDS if side_only and not in_urgent
                    else SIDE_REALERT_SECONDS
                )
                # Presence in the 2 m cone is not a warning. Warn if:
                # already in the face (<50 cm), or distance is falling, or
                # there is no ToF number (camera fallback — don't go mute).
                opening_worthy = (
                    in_urgent
                    or approaching_now
                    or distance_mm is None
                )
                should_alert = (
                    (not obstacle_active and opening_worthy)
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= side_realert_seconds)
                )
                if should_alert and seconds_since_alert < MIN_BURST_GAP_SECONDS:
                    should_alert = False
                # Ears need traffic, not a list of bowls. Speak only when it
                # is in the forward path or already urgent. Side pass-bys
                # are a left/right buzz; double-tap Describe if they want the name.
                speak_now = in_urgent or (not side_only) or distance_mm is None

                if should_alert:
                    announcement = message if message != last_alert_message else None
                    direction = "ahead" if side == "both" else side
                    event_detail = {
                        "distance_mm": distance_mm,
                        "direction": direction,
                        "message": message,
                    }
                    frame_copy = None
                    image_b64 = ""
                    if frame is not None:
                        try:
                            jpeg = frame_to_jpeg_bytes(frame, quality=55)
                            image_b64 = base64.b64encode(jpeg).decode("ascii")
                            event_detail["image_jpeg_b64"] = image_b64
                            frame_copy = frame.copy()
                        except Exception as snap_error:
                            print(f"[CAMERA] Obstacle snapshot skipped: {snap_error}")
                    # Instant pass to phone: photo now (do not wait for Gemini).
                    if distance_mm is None:
                        dist_label = "अज्ञात दूरी"
                    else:
                        dist_label = (
                            f"{max(1, int(round(distance_mm / 10.0)))} cm"
                            if distance_mm < 1000
                            else (
                                f"{int(round(distance_mm / 1000.0))} m"
                                if abs(distance_mm / 1000.0 - round(distance_mm / 1000.0)) < 0.05
                                else f"{distance_mm / 1000.0:.1f} m"
                            )
                        )
                    dir_hi = {"ahead": "सामने", "left": "बाईं ओर", "right": "दाईं ओर"}.get(
                        str(direction or "ahead").lower(), "सामने"
                    )
                    quick_hi = f"{dir_hi} बाधा है, लगभग {dist_label}।"
                    instant = publish_phone_alert({
                        "kind": "obstacle_snapshot",
                        "event_type": event_type,
                        "direction": direction,
                        "distance_mm": distance_mm,
                        "speak_hi": quick_hi,
                        "text_hi": quick_hi,
                        "image_jpeg_b64": "",
                        "source": "tof_snapshot",
                        # Phone TTS is primary while glasses speaker is unreliable.
                        "speak": speak_now,
                    })
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
                    queue_event(event_type, event_detail)
                    if speak_now and frame_copy is not None:
                        threading.Thread(
                            target=obstacle_phone_guidance_worker,
                            args=(frame_copy, direction, distance_mm, event_type, image_b64, instant.get("alert_id")),
                            daemon=True,
                        ).start()
                    last_alert = now
                    last_alert_distance = distance_mm
                    last_alert_side = side
                    last_alert_pattern = pattern
                    last_alert_message = message
                    obstacle_active = True
                    haptic_quiet = False
                    approach_active = False
                    opening_burst_at = now
                    distance_samples = [(now, distance_mm)] if distance_mm is not None else []
                    with state_lock:
                        state["last_alert_side"] = side
                        state["last_alert_zone"] = pattern
                elif haptic_reminder:
                    # Approaching only: keep buzzing. No glasses speech (phone already guided).
                    threading.Thread(target=deliver_alert, args=(side, pattern, None)).start()
                    # While obstacle stays, refresh phone photo every reminder tick
                    # so continuous buzz still shows an updated live capture.
                    if frame is not None:
                        try:
                            jpeg = frame_to_jpeg_bytes(frame, quality=50)
                            image_b64 = base64.b64encode(jpeg).decode("ascii")
                            direction = "ahead" if side == "both" else side
                            if distance_mm is None:
                                dist_label = "अज्ञात दूरी"
                            else:
                                dist_label = (
                            f"{max(1, int(round(distance_mm / 10.0)))} cm"
                            if distance_mm < 1000
                            else (
                                f"{int(round(distance_mm / 1000.0))} m"
                                if abs(distance_mm / 1000.0 - round(distance_mm / 1000.0)) < 0.05
                                else f"{distance_mm / 1000.0:.1f} m"
                            )
                        )
                            dir_hi = {"ahead": "सामने", "left": "बाईं ओर", "right": "दाईं ओर"}.get(
                                str(direction or "ahead").lower(), "सामने"
                            )
                            publish_phone_alert({
                                "kind": "obstacle_snapshot",
                                "event_type": event_type,
                                "direction": direction,
                                "distance_mm": distance_mm,
                                "speak_hi": f"{dir_hi} बाधा है, लगभग {dist_label}।",
                                "text_hi": f"{dir_hi} बाधा है, लगभग {dist_label}।",
                                "image_jpeg_b64": "",
                                "source": "tof_live",
                                "speak": False,
                            })
                        except Exception as snap_error:
                            print(f"[CAMERA] Live snapshot skipped: {snap_error}")
                    last_alert = now
            else:
                # Require a stable clear reading before resetting. One noisy
                # sensor frame must not cause a repeat alert for the same person.
                if obstacle_active:
                    clear_since = clear_since or now
                    if now - clear_since >= CLEAR_CONFIRM_SECONDS:
                        queue_event("path_clear", {"message": "Path clear"})
                        threading.Thread(target=deliver_alert, args=(None, None, "Path clear")).start()
                        obstacle_active = False
                        last_alert_distance = None
                        last_alert_side = None
                        last_alert_pattern = None
                        last_alert_message = None
                        haptic_quiet = False
                        approach_active = False
                        opening_burst_at = None
                        distance_samples = []
                        with state_lock:
                            state["last_alert_side"] = None
                            state["last_alert_zone"] = None

            maybe_auto_describe(frame, obstacle_active)

        except Exception as e:
            print(f"[DETECT] Error: {e}")

        time.sleep(0.3)

# ══════════════════════════════════════════
#  VOICE COMMAND LOOP (main thread)
# ══════════════════════════════════════════
def voice_loop(picam2, stop_event):
    print("[MIC] Voice loop started.")
    print("[MIC] Commands: 'what is ahead', 'pause', 'resume', "
          "'photo', 'status', 'pairing code', 'help', 'stop'")

    r = sr.Recognizer()
    r.energy_threshold = 300
    r.dynamic_energy_threshold = True

    while not stop_event.is_set():
        try:
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.5)
                audio = r.listen(source, timeout=4, phrase_time_limit=5)

            text = r.recognize_google(audio).lower()
            print(f"[MIC] Heard: '{text}'")

            if "what" in text or "ahead" in text or "around" in text:
                with state_lock:
                    scene = state["last_scene"]
                speak(f"Currently: {scene}", blocking=True)
                vibrate("both", 0.2, 60)
                queue_event("voice_command", {
                    "command": text,
                    "response": f"Currently: {scene}",
                })

            elif "pause" in text:
                with state_lock:
                    state["paused"] = True
                speak("Detection paused", blocking=True)

            elif "resume" in text or "start" in text:
                with state_lock:
                    state["paused"] = False
                speak("Detection resumed", blocking=True)

            elif "photo" in text or "capture" in text or "picture" in text:
                if picam2 is None:
                    speak("Camera is unavailable", blocking=True)
                else:
                    fname = f"photo_{int(time.time())}.jpg"
                    with camera_lock:
                        frame = picam2.capture_array()
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    cv2.imwrite(fname, frame_bgr)
                    speak("Photo saved", blocking=True)
                    print(f"[CAMERA] Saved {fname}")

            elif "status" in text or "check" in text:
                with state_lock:
                    fc = state["frame_count"]
                    scene = state["last_scene"]
                    paused = state["paused"]
                    tof_ok = state["tof_ok"]
                mode = "ToF sensors active" if tof_ok else "camera-only mode"
                status = "paused" if paused else "running"
                speak(
                    f"System {status}, {mode}. "
                    f"{fc} frames processed. {scene}",
                    blocking=True
                )
                queue_event("voice_command", {
                    "command": text,
                    "response": f"System {status}, {mode}. {scene}",
                })

            elif "pairing code" in text or text.strip() == "code":
                with state_lock:
                    code = state["pairing_code"]
                if code:
                    speak_pairing_code(code)
                else:
                    speak("A pairing code is not available", blocking=True)

            elif "help" in text or "commands" in text:
                speak(
                    "Commands: what is ahead, pause, resume, "
                    "photo, status, stop",
                    blocking=True
                )

            elif "stop" in text or "exit" in text or "shutdown" in text:
                speak("Shutting down Divya Drishti", blocking=True)
                vibrate_pattern("both", "double")
                stop_event.set()

            else:
                speak("Command not recognized")

        except sr.WaitTimeoutError:
            pass
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            print(f"[MIC] API error: {e}")
        except Exception as e:
            print(f"[MIC] Error: {e}")

# ══════════════════════════════════════════
#  STARTUP SEQUENCE
# ══════════════════════════════════════════
def startup_sequence():
    print("=" * 50)
    print("  DIVYA DRISHTI - PHASE 1 FULL SYSTEM")
    print("=" * 50)
    speak("Divya Drishti starting", blocking=False)
    time.sleep(0.3)
    vibrate("left",  0.2, 100)
    time.sleep(0.15)
    vibrate("right", 0.2, 100)
    time.sleep(0.15)
    vibrate("both",  0.4, 100)
    time.sleep(0.5)

# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════
def main():
    startup_sequence()

    registered = register_device_if_needed()
    if sync_enabled() and not registered:
        speak("Cloud sync is unavailable. Continuing offline.")
    load_settings_state()

    tof1, tof2, bus3, bus4 = init_tof_sensors()
    if tof1 is not None and tof2 is not None:
        speak("Dual ToF sensors online.")
    elif tof1 is not None:
        speak("Left ToF sensor online. Right sensor unavailable.")
    elif tof2 is not None:
        speak("Right ToF sensor online. Left sensor unavailable.")
    else:
        speak("ToF sensors unavailable. Using camera detection only.")

    picam2 = init_camera()
    camera_holder["picam2"] = picam2
    if picam2 is not None:
        speak("Camera ready.")
        reset_auto_describe_schedule(reason="camera ready")

    stop_event = threading.Event()
    start_local_link(stop_event)
    if sync_enabled():
        threading.Thread(target=sync_worker, args=(stop_event,), daemon=True).start()
        threading.Thread(target=status_sync_worker, args=(stop_event,), daemon=True).start()
        threading.Thread(target=settings_worker, args=(stop_event,), daemon=True).start()

    det_thread = threading.Thread(
        target=detection_loop,
        args=(picam2, tof1, tof2, stop_event)
    )
    det_thread.daemon = True
    det_thread.start()

    speak("All systems active. Listening for commands.")
    vibrate("both", 0.3, 70)

    try:
        voice_loop(picam2, stop_event)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Ctrl+C received, shutting down...")
        stop_event.set()

    # cleanup
    for sensor in (tof1, tof2):
        if sensor is None:
            continue
        try:
            sensor.stop_ranging()
        except Exception:
            pass
    for bus in (bus3, bus4):
        if bus is None:
            continue
        try:
            bus.close()
        except Exception:
            pass
    if picam2 is not None:
        picam2.stop()
    GPIO.cleanup()

    print("=" * 50)
    print("  SHUTDOWN COMPLETE")
    print("=" * 50)

if __name__ == "__main__":
    if "--link-only" in sys.argv:
        try:
            saved = json.loads(DEVICE_FILE.read_text())
            with state_lock:
                state["device_id"] = saved.get("device_id")
                state["pairing_code"] = saved.get("pairing_code")
        except (FileNotFoundError, json.JSONDecodeError):
            print("[LOCAL] Device is not registered yet; link-only mode cannot start.")
            sys.exit(1)
        link_stop_event = threading.Event()
        start_local_link(link_stop_event)
        print("[LOCAL] Link-only mode active. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            link_stop_event.set()
    else:
        main()
