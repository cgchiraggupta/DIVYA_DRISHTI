#!/usr/bin/env python3
"""Local rate-limiting + JPEG encoding for Divya Drishti's on-demand/ambient
photo requests.

The Pi has no Gemini key of its own — every actual Gemini call happens on
the phone, via the `gemini-vision` Supabase Edge Function
(supabase/functions/gemini-vision/index.ts), reached over the WebSocket link
as a vision_request/vision_result pair (see request_phone_vision() and
_describe_via_phone_or_local()/obstacle_phone_guidance_worker()/
_auto_describe_worker() in divya_drishti_final.py).

What stays here is purely local and Gemini-independent: encoding a camera
frame to JPEG bytes, and the three separate cooldown/in-flight gates that
stop the Pi from firing off more requests than the phone can keep up with.
Three gates, not one, so a person pressing the on-demand describe/read
button doesn't have to wait out a cooldown window an automatic obstacle
naming or ambient scene-describe call just used, and vice versa — they all
still share one in-flight lock, so at most one photo is ever in flight to
the phone at a time.
"""

from __future__ import annotations

import threading
import time

import cv2

# Manual on-demand describe/read/read_full waits behind an in-flight
# auto/obstacle request instead of failing instantly with status=busy.
MANUAL_DESCRIBE_INFLIGHT_WAIT_SECONDS = 20
DESCRIBE_COOLDOWN_SECONDS = 8
OBSTACLE_COOLDOWN_SECONDS = 6
# Auto scene-describe (camera-triggered, no button) gets its own, slightly
# longer floor than the manual button — it can fire again on its own the
# moment the scene changes, so it needs more breathing room than a human
# re-pressing a button on purpose.
AUTO_DESCRIBE_COOLDOWN_SECONDS = 12

_cooldown_lock = threading.Lock()
_last_describe_at = 0.0
_last_obstacle_at = 0.0
_last_auto_describe_at = 0.0
# Walking triggers several ToF/escalation events almost simultaneously
# (left sensor, right sensor, "getting closer"). Without this, multiple
# background threads could all pass the cooldown check before any of them
# marked it used, firing a burst of requests at once. This lock makes "is
# it free AND claim it" one atomic step.
#
# Shared across every on-demand/ambient photo request this module gates —
# manual "Describe"/"Read" button, auto ToF obstacle naming, AND the
# camera-driven auto scene-describe. One shared lock means only one photo
# is EVER in flight to the phone, system-wide; every other caller gets an
# immediate, honest "busy" result instead of piling up behind a slow call.
_gemini_inflight_lock = threading.Lock()


def cooldown_remaining() -> float:
    with _cooldown_lock:
        elapsed = time.monotonic() - _last_describe_at
    remaining = DESCRIBE_COOLDOWN_SECONDS - elapsed
    return remaining if remaining > 0 else 0.0


def obstacle_cooldown_remaining() -> float:
    with _cooldown_lock:
        elapsed = time.monotonic() - _last_obstacle_at
    remaining = OBSTACLE_COOLDOWN_SECONDS - elapsed
    return remaining if remaining > 0 else 0.0


def auto_describe_cooldown_remaining() -> float:
    with _cooldown_lock:
        elapsed = time.monotonic() - _last_auto_describe_at
    remaining = AUTO_DESCRIBE_COOLDOWN_SECONDS - elapsed
    return remaining if remaining > 0 else 0.0


def _mark_describe_used() -> None:
    global _last_describe_at
    with _cooldown_lock:
        _last_describe_at = time.monotonic()


def _mark_obstacle_used() -> None:
    global _last_obstacle_at
    with _cooldown_lock:
        _last_obstacle_at = time.monotonic()


def _mark_auto_describe_used() -> None:
    global _last_auto_describe_at
    with _cooldown_lock:
        _last_auto_describe_at = time.monotonic()


def format_distance_label(distance_mm: int | None) -> str:
    """Spoken distance: digits + English units (e.g. 320 → '32 cm')."""
    if distance_mm is None:
        return "अज्ञात दूरी"
    mm = max(0, int(distance_mm))
    if mm < 1000:
        return f"{max(1, int(round(mm / 10.0)))} cm"
    meters = mm / 1000.0
    if abs(meters - round(meters)) < 0.05:
        return f"{int(round(meters))} m"
    return f"{meters:.1f} m"


def format_direction_hi(direction: str | None) -> str:
    mapping = {
        "ahead": "सामने",
        "left": "बाईं ओर",
        "right": "दाईं ओर",
        "behind": "पीछे",
    }
    key = (direction or "ahead").strip().lower()
    return mapping.get(key, "सामने")


def frame_to_jpeg_bytes(frame, quality: int = 70) -> bytes:
    # Picamera2 still frames are RGB; encode as BGR for natural JPEG colors.
    if getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Could not encode the camera frame in memory.")
    return encoded.tobytes()


def describe_cooldown_or_busy(timeout: float = MANUAL_DESCRIBE_INFLIGHT_WAIT_SECONDS) -> dict | None:
    """Acquire the shared on-demand describe/read/read_full gate: the
    cooldown window plus the single in-flight lock (see its docstring).

    Returns a cooldown/busy result dict if the caller must not proceed, or
    None if the gate was acquired — the caller MUST call
    release_describe_gate() exactly once when done (success or failure).
    """
    remaining = cooldown_remaining()
    if remaining > 0:
        return {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "retry_after_seconds": int(remaining + 0.999),
        }

    # Wait for any in-flight auto/obstacle request to finish — a double-tap
    # or phone Describe must not lose to status=busy in 0.00s.
    if not _gemini_inflight_lock.acquire(blocking=True, timeout=timeout):
        return {"status": "busy", "text_hi": "", "source": "busy"}

    _mark_describe_used()
    return None


def release_describe_gate() -> None:
    _gemini_inflight_lock.release()


def auto_describe_gate_or_busy() -> dict | None:
    """Non-blocking ambient scene-describe gate (own cooldown clock,
    separate from the on-demand/obstacle gates so none of the three fight
    over the same budget). Returns a result dict if the caller must not
    proceed, or None if the gate was acquired — caller MUST call
    release_describe_gate() when done."""
    remaining = auto_describe_cooldown_remaining()
    if remaining > 0:
        return {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "retry_after_seconds": int(remaining + 0.999),
        }

    if not _gemini_inflight_lock.acquire(blocking=False):
        return {"status": "busy", "text_hi": "", "source": "busy", "mode": "auto_describe"}

    _mark_auto_describe_used()
    return None


def obstacle_gate_or_skip(direction: str, distance_mm: int | None, max_range_mm: int | None) -> dict | None:
    """Non-blocking near-obstacle-naming gate: cooldown, in-flight lock, and
    the "don't invent far-scene narration outside the configured range"
    check, all in one place. Returns a result dict if the caller must not
    proceed (busy/cooldown/out-of-range), or None if the gate was acquired —
    caller MUST call release_describe_gate() when done."""
    # Non-blocking: if another thread is already mid-request, don't wait —
    # the phone always has *something* to say right away (the instant
    # distance line), so there's no need to queue behind a slow call.
    if not _gemini_inflight_lock.acquire(blocking=False):
        return {
            "status": "busy",
            "text_hi": "",
            "source": "busy",
            "direction": direction,
            "distance_mm": distance_mm,
        }

    remaining = obstacle_cooldown_remaining()
    if remaining > 0:
        _gemini_inflight_lock.release()
        return {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "retry_after_seconds": int(remaining + 0.999),
        }

    # Respect product range: do not invent far-scene narration outside settings.
    range_mm = max(1000, min(2500, int(max_range_mm or 2500)))
    if distance_mm is not None and distance_mm > range_mm + 300:
        _gemini_inflight_lock.release()
        distance = format_distance_label(distance_mm)
        return {
            "status": "skipped",
            "text_hi": f"{format_direction_hi(direction)} बाधा सेंसर की दूरी {distance} है, सेटिंग रेंज से बाहर।",
            "source": "range_skip",
            "direction": direction,
            "distance_mm": distance_mm,
        }

    # Mark used while still holding the lock — closes the race where
    # several threads all saw "cooldown clear" before any of them claimed it.
    _mark_obstacle_used()
    return None
