#!/usr/bin/env python3
"""Shared Gemini read/obstacle helper for Divya Drishti.

Phone-first: returns Hindi (Devanagari) text for Sarvam TTS, with
digits left as numbers. Optional in-memory JPEG bytes. Does not write
captured images to disk. API key from env or ~/.divyadrishti/gemini.env
— never log the key value.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2

GEMINI_ENV_FILE = Path.home() / ".divyadrishti" / "gemini.env"
# 2026-08-14: measured live success rate on this key. "gemini-flash-latest"
# currently resolves to gemini-3.7-flash, which was overloaded and returning
# HTTP 503 "high demand" on ~64% of calls (4/11 ok in a 75s stress test).
# gemini-3.6-flash scored 15/15 ok across two back-to-back test rounds with
# the same key/network, so it's the one actually in use for now. Re-check
# this if object naming starts silently falling back again — Google's
# "latest" alias keeps moving to newer, more contested models.
GEMINI_MODEL = "gemini-3.6-flash"
# Read/describe: user is standing still waiting, can afford a longer wait.
# gemini-3.6-flash was observed up to ~12.8s on a real call, so this needs
# headroom above that, not just above the "usual" case.
DESCRIBE_TIMEOUT_SECONDS = 16
# Obstacle: user is walking, but the instant TOF beep/haptic already covers
# "something is there right now" — this timeout only gates the *name* of
# the object, so it can afford to wait for a real answer instead of cutting
# off a call that was about to succeed.
OBSTACLE_TIMEOUT_SECONDS = 16
DESCRIBE_COOLDOWN_SECONDS = 8
OBSTACLE_COOLDOWN_SECONDS = 6
# Auto scene-describe (camera-triggered, no button) gets its own, slightly
# longer floor than the manual button — it can fire again on its own the
# moment the scene changes, so it needs more breathing room than a human
# re-pressing a button on purpose.
AUTO_DESCRIBE_COOLDOWN_SECONDS = 12
MOCK_READ_HI = (
    "सामने दीवार है। बोर्ड पर लिखा है EXIT। नीचे छोटे लेबल पर Gate 2 लिखा है।"
)
MOCK_OBSTACLE_HI = "सामने कुर्सी है, लगभग 80 cm।"

# Spoken output: Hindi Devanagari. Distance numbers + cm/m stay English.
HINDI_TTS_RULES = (
    "Reply ONLY in Hindi Devanagari script. "
    "Keep numbers as digits (2, 80, 1.5), never as words. "
    "Write distance units in English as cm or m, for example 80 cm or 1 m. "
    "Do not write सेंटीमीटर or मीटर. "
    "Do not use other English words except printed text you read from signs, labels, "
    "screens, or posters — quote that text exactly as written. "
)

# On-demand button: scene in front + OCR for any visible writing.
READ_PROMPT = (
    "You are Divya Drishti for a blind or low-vision user looking through glasses. "
    + HINDI_TTS_RULES
    + "Describe what is directly in front: "
    "images or posters, objects and people, and nearby obstacles "
    "(chair, table, wall, vehicle, stairs, pole). "
    "If a signboard, label, screen, or any writing is visible, read it out (OCR). "
    "Do NOT tour the far background. Max 50 words."
)

# Auto obstacle alert: only the near obstacle that triggered ToF.
OBSTACLE_PROMPT = (
    "You are Divya Drishti obstacle mode. A distance sensor fired: direction={direction}, "
    "measured distance about {distance}. User obstacle range setting is max {max_range}. "
    + HINDI_TTS_RULES
    + "Look at the photo and name ONLY the nearby obstacle likely causing that reading "
    "(roughly within {max_range}, toward {direction}). "
    "Example: 'सामने कुर्सी है, लगभग 80 cm।' "
    "Do NOT mention far walls, distant people, sky, or anything clearly beyond {max_range}. "
    "If the near obstacle is unclear, say so briefly with the distance. Max 20 words."
)

_cooldown_lock = threading.Lock()
_last_describe_at = 0.0
_last_obstacle_at = 0.0
_last_auto_describe_at = 0.0
# Walking triggers several ToF/escalation events almost simultaneously
# (left sensor, right sensor, "getting closer"). Without this, multiple
# background threads could all pass the cooldown check before any of them
# marked it used, firing a burst of Gemini calls at once. Gemini then rate
# limits the burst, every call except the first times out or errors, and
# each one still waits the full timeout before giving up — which is what
# made obstacle naming feel both wrong and slow. This lock makes "is it free
# AND claim it" one atomic step.
#
# Shared across every Gemini call this module makes — manual "Describe"
# button, auto ToF obstacle naming, AND the camera-driven auto scene-describe.
# Previously obstacle naming had its own lock and describe_frame() had none
# at all, so an obstacle call and a describe call could legitimately run at
# the same time, or a double-tap on Describe could fire two overlapping
# calls. One shared lock means only one Gemini call is EVER in flight,
# system-wide; every other caller gets an immediate, honest "busy" result
# instead of piling up behind a slow network call.
_gemini_inflight_lock = threading.Lock()


def load_api_key() -> str:
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        for line in GEMINI_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.partition("=")[2].strip()
    except OSError:
        pass
    return ""


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


# Back-compat alias used by older call sites / patches.
def _format_m(distance_mm: int | None) -> str:
    return format_distance_label(distance_mm)


def _finish(label: str, start: float, result: dict) -> dict:
    """Attach elapsed seconds and log one line for every return path of a
    describe_*() call — including instant cooldown/busy bounces, so it's
    visible at a glance that those didn't wait on anything. Printed here
    (not by the caller) so timing is consistent across the manual Describe
    button, ToF obstacle naming, and auto scene-describe without having to
    instrument three different call sites in divya_drishti_final.py.
    """
    result["duration_s"] = round(time.monotonic() - start, 2)
    print(
        f"[DESCRIBE] {label} status={result.get('status')} "
        f"source={result.get('source')} took {result['duration_s']:.2f}s"
    )
    return result


def frame_to_jpeg_bytes(frame, quality: int = 70) -> bytes:
    # Picamera2 still frames are RGB; encode as BGR for natural JPEG colors.
    if getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Could not encode the camera frame in memory.")
    return encoded.tobytes()


def describe_frame(frame, *, include_image: bool = True, prompt: str | None = None) -> dict:
    """On-demand scene + OCR for what's in front. Returns JSON-serializable dict.

    Shares _gemini_inflight_lock with every other Gemini call in this module
    (see its docstring) — if an obstacle-naming or auto-describe call is
    already in flight, this returns "busy" immediately instead of stacking
    a second concurrent request.
    """
    start = time.monotonic()
    remaining = cooldown_remaining()
    if remaining > 0:
        return _finish("describe_frame", start, {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "retry_after_seconds": int(remaining + 0.999),
        })

    # Non-blocking: don't wait behind another in-flight Gemini call, and
    # don't spend this cooldown window on a request that never actually ran.
    if not _gemini_inflight_lock.acquire(blocking=False):
        return _finish("describe_frame", start, {
            "status": "busy",
            "text_hi": "",
            "source": "busy",
            "mode": "read",
        })

    try:
        _mark_describe_used()
        key = load_api_key()
        jpeg = frame_to_jpeg_bytes(frame)

        try:
            if not key or key == "mock":
                text_hi = MOCK_READ_HI
                source = "mock"
            else:
                text_hi = _call_gemini(jpeg, key, prompt or READ_PROMPT)
                source = "gemini"
            result = {
                "status": "ok",
                "text_hi": text_hi,
                "source": source,
                "mode": "read",
            }
        except RuntimeError as error:
            result = {
                "status": "error",
                "text_hi": "अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।",
                "source": "fallback",
                "error": str(error),
                "mode": "read",
            }
    finally:
        _gemini_inflight_lock.release()

    if include_image:
        result["image_jpeg_b64"] = base64.b64encode(jpeg).decode("ascii")
    return _finish("describe_frame", start, result)


def describe_scene_auto(frame, *, include_image: bool = True) -> dict:
    """Same scene + OCR description as describe_frame(), but triggered by the
    glasses' own camera-side scene-change detection instead of a button press.

    Kept as a separate function (own cooldown clock) so the automatic path
    and the manual "Describe" button don't fight over the same cooldown
    budget — a person pressing the button should not have to wait out a
    window an auto-trigger just used, and vice versa. Both still share the
    single _gemini_inflight_lock, so they can never call Gemini at the same
    time. On any failure this returns empty text_hi (status "error") rather
    than a spoken fallback line — unlike the manual button, nobody asked for
    this one, so silence is better than narrating a Gemini/network hiccup
    out of nowhere.
    """
    start = time.monotonic()
    remaining = auto_describe_cooldown_remaining()
    if remaining > 0:
        return _finish("describe_scene_auto", start, {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "retry_after_seconds": int(remaining + 0.999),
        })

    if not _gemini_inflight_lock.acquire(blocking=False):
        return _finish("describe_scene_auto", start, {
            "status": "busy",
            "text_hi": "",
            "source": "busy",
            "mode": "auto_describe",
        })

    try:
        _mark_auto_describe_used()
        key = load_api_key()
        jpeg = frame_to_jpeg_bytes(frame)

        try:
            if not key or key == "mock":
                text_hi = MOCK_READ_HI
                source = "mock"
            else:
                text_hi = _call_gemini(jpeg, key, READ_PROMPT)
                source = "gemini"
            result = {
                "status": "ok",
                "text_hi": text_hi,
                "source": source,
                "mode": "auto_describe",
            }
        except RuntimeError as error:
            result = {
                "status": "error",
                "text_hi": "",
                "source": "fallback",
                "error": str(error),
                "mode": "auto_describe",
            }
    finally:
        _gemini_inflight_lock.release()

    if include_image:
        result["image_jpeg_b64"] = base64.b64encode(jpeg).decode("ascii")
    return _finish("describe_scene_auto", start, result)


def describe_obstacle(
    frame,
    *,
    direction: str,
    distance_mm: int | None,
    max_range_mm: int | None = 2500,
) -> dict:
    """Event-triggered near-obstacle label for phone TTS.

    Shares _gemini_inflight_lock with every other Gemini call in this module.
    Every other concurrent caller gets an immediate "busy" result instead of
    piling up behind a slow network call, so the phone always has
    *something* to say right away.
    """
    start = time.monotonic()
    # Non-blocking: if another thread is already mid-call, don't wait on it.
    if not _gemini_inflight_lock.acquire(blocking=False):
        return _finish("describe_obstacle", start, {
            "status": "busy",
            "text_hi": "",
            "source": "busy",
            "direction": direction,
            "distance_mm": distance_mm,
        })

    try:
        remaining = obstacle_cooldown_remaining()
        if remaining > 0:
            return _finish("describe_obstacle", start, {
                "status": "cooldown",
                "text_hi": "",
                "source": "cooldown",
                "retry_after_seconds": int(remaining + 0.999),
            })

        # Respect product range: do not invent far-scene narration outside settings.
        range_mm = int(max_range_mm or 2500)
        range_mm = max(1000, min(2500, range_mm))
        if distance_mm is not None and distance_mm > range_mm + 300:
            distance = _format_m(distance_mm)
            return _finish("describe_obstacle", start, {
                "status": "skipped",
                "text_hi": f"{format_direction_hi(direction)} बाधा सेंसर की दूरी {distance} है, सेटिंग रेंज से बाहर।",
                "source": "range_skip",
                "direction": direction,
                "distance_mm": distance_mm,
            })

        # Mark used while still holding the lock — closes the race where
        # several threads all saw "cooldown clear" before any of them
        # claimed it.
        _mark_obstacle_used()
        distance = _format_m(distance_mm)
        max_range = _format_m(range_mm)
        prompt = OBSTACLE_PROMPT.format(
            direction=format_direction_hi(direction),
            distance=distance,
            max_range=max_range,
        )
        key = load_api_key()
        jpeg = frame_to_jpeg_bytes(frame, quality=55)
        try:
            if not key or key == "mock":
                text_hi = f"सामने जाँच: {format_direction_hi(direction)} बाधा है, लगभग {distance}।"
                source = "mock"
            else:
                text_hi = _call_gemini(jpeg, key, prompt, timeout=OBSTACLE_TIMEOUT_SECONDS)
                source = "gemini"
            return _finish("describe_obstacle", start, {
                "status": "ok",
                "text_hi": text_hi,
                "source": source,
                "direction": direction,
                "distance_mm": distance_mm,
            })
        except RuntimeError as error:
            return _finish("describe_obstacle", start, {
                "status": "error",
                "text_hi": f"{format_direction_hi(direction)} बाधा है, लगभग {distance}।",
                "source": "fallback",
                "error": str(error),
                "direction": direction,
                "distance_mm": distance_mm,
            })
    finally:
        _gemini_inflight_lock.release()


def _call_gemini(
    jpeg_bytes: bytes,
    api_key: str,
    prompt: str,
    timeout: float = DESCRIBE_TIMEOUT_SECONDS,
    thinking_level: str = "low",
) -> str:
    # 2026-08-14: measured live on this key/network with cv_test.jpg + the
    # obstacle prompt. gemini-3.6-flash defaults to thinkingLevel "medium",
    # which took 9.73s on the one real call we captured and timed out (>20s,
    # no answer at all) on two of four direct test calls. Forcing "low"
    # (light reasoning, not zero — "minimal" still timed out once in testing)
    # gave 3/3 clean answers at 2.46s / 4.28s / 4.47s, same correct text each
    # time. For a single-object naming task this is plenty of reasoning depth
    # and the latency difference is the whole point of this override — do not
    # remove it without re-measuring, since Gemini 3.x ignores the older
    # numeric thinkingBudget for this model (400 INVALID_ARGUMENT).
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(jpeg_bytes).decode("ascii"),
                    }
                },
            ]
        }],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": thinking_level},
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", errors="ignore")[:160]
        except Exception:
            pass
        raise RuntimeError(f"Gemini HTTP {error.code}{(': ' + detail) if detail else ''}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Gemini request timed out or could not reach the service.") from error

    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = " ".join(part.get("text", "").strip() for part in parts if part.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned no description text.")
    return text
