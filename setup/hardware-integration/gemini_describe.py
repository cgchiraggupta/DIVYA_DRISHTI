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
# 2026-08-18 live on this Pi (tiny image, thinkingLevel low):
#   gemini-3.6-flash      23.34s
#   gemini-3.5-flash       5.72s
#   gemini-3.5-flash-lite  1.77s
# 3.6 was kept earlier for 503-reliability vs "latest"/3.7, not speed.
# 3.5-flash is the same billed key, ~4x faster, still good enough for
# Hindi scene + OCR. Lite is faster still but weaker on small sign text —
# do not drop to lite without a real glasses-camera OCR check.
GEMINI_MODEL = "gemini-3.5-flash"
# Read/describe: 3.5-flash image calls measured ~6s; 16s is ample headroom
# and keeps a double-tap from sitting 30–40s if Gemini is already busy.
DESCRIBE_TIMEOUT_SECONDS = 16
# Obstacle: user is walking, but the instant TOF beep/haptic already covers
# "something is there right now" — this timeout only gates the *name* of
# the object, so it can afford to wait for a real answer instead of cutting
# off a call that was about to succeed.
OBSTACLE_TIMEOUT_SECONDS = 16
# Manual Describe (button / phone) waits behind an in-flight auto/obstacle
# call instead of failing instantly with status=busy.
MANUAL_DESCRIBE_INFLIGHT_WAIT_SECONDS = 20
DESCRIBE_COOLDOWN_SECONDS = 8
OBSTACLE_COOLDOWN_SECONDS = 6
# Auto scene-describe (camera-triggered, no button) gets its own, slightly
# longer floor than the manual button — it can fire again on its own the
# moment the scene changes, so it needs more breathing room than a human
# re-pressing a button on purpose.
AUTO_DESCRIBE_COOLDOWN_SECONDS = 12
MOCK_DESCRIBE_HI = "सामने कुर्सी है। दाईं ओर एक व्यक्ति खड़ा है।"
MOCK_OCR_HI = "बोर्ड पर लिखा है EXIT। नीचे Gate 2 लिखा है।"
MOCK_READ_HI = MOCK_DESCRIBE_HI
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

# Double-tap / phone Describe: objects and space, not a full OCR pass.
DESCRIBE_PROMPT = (
    "You are Divya Drishti object mode for a blind walker looking through glasses. "
    + HINDI_TTS_RULES
    + "Name what is directly in front: people, furniture, walls, doors, vehicles, poles, "
    "or stairs if clearly visible. Say side when obvious (सामने / बाईं ओर / दाईं ओर). "
    "If a large sign is the main thing, say a board is there — do not read long text; "
    "that is a separate Read action. Do NOT tour the far background. Max 40 words."
)

# Phone Read: printed text only.
OCR_PROMPT = (
    "You are Divya Drishti read mode for a blind user pointing the glasses at text. "
    + HINDI_TTS_RULES
    + "Read ONLY printed or on-screen text that is clearly visible "
    "(signs, labels, posters, screens). Quote it exactly as written. "
    "If several lines, read the main heading first, then one short extra line if useful. "
    "If no writing is readable, say exactly: कोई लिखावट नहीं दिख रही। "
    "Do NOT describe furniture, people, or the room. Max 40 words."
)

# Backward-compatible alias used by auto-describe until callers switch.
READ_PROMPT = DESCRIBE_PROMPT

# Auto obstacle alert: only the near obstacle that triggered ToF.
OBSTACLE_PROMPT = (
    "You are Divya Drishti obstacle mode. A distance sensor fired: direction={direction}, "
    "measured distance about {distance}. User obstacle range setting is max {max_range}. "
    + HINDI_TTS_RULES
    + "Look at the photo and name ONLY the nearby object likely causing that reading "
    "(chair, person, door, wall, vehicle, pole, stairs — roughly within {max_range}, "
    "toward {direction}). Example: 'सामने कुर्सी है, लगभग 80 cm।' "
    "Do NOT mention far walls, distant people, sky, or anything clearly beyond {max_range}. "
    "Do NOT read sign text. If the near object is unclear, say so briefly with the distance. "
    "Max 20 words."
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


def describe_frame(frame, *, include_image: bool = True, prompt: str | None = None, mode: str = "describe") -> dict:
    """On-demand look-ahead. mode='describe' names objects; mode='read' is OCR only.

    Shares _gemini_inflight_lock with every other Gemini call in this module
    (see its docstring) — if an obstacle-naming or auto-describe call is
    already in flight, this waits briefly instead of returning busy instantly.
    """
    mode = "read" if str(mode).lower() == "read" else "describe"
    start = time.monotonic()
    remaining = cooldown_remaining()
    if remaining > 0:
        return _finish("describe_frame", start, {
            "status": "cooldown",
            "text_hi": "",
            "source": "cooldown",
            "mode": mode,
            "retry_after_seconds": int(remaining + 0.999),
        })

    # Wait for any in-flight auto/obstacle Gemini call to finish — a double-tap
    # or phone Describe must not lose to status=busy in 0.00s.
    if not _gemini_inflight_lock.acquire(
        blocking=True, timeout=MANUAL_DESCRIBE_INFLIGHT_WAIT_SECONDS
    ):
        return _finish("describe_frame", start, {
            "status": "busy",
            "text_hi": "",
            "source": "busy",
            "mode": mode,
        })

    try:
        _mark_describe_used()
        key = load_api_key()
        jpeg = frame_to_jpeg_bytes(frame)
        chosen_prompt = prompt or (OCR_PROMPT if mode == "read" else DESCRIBE_PROMPT)
        mock_hi = MOCK_OCR_HI if mode == "read" else MOCK_DESCRIBE_HI

        try:
            if not key or key == "mock":
                text_hi = mock_hi
                source = "mock"
            else:
                text_hi = _call_gemini(jpeg, key, chosen_prompt)
                source = "gemini"
            result = {
                "status": "ok",
                "text_hi": text_hi,
                "source": source,
                "mode": mode,
            }
        except RuntimeError as error:
            result = {
                "status": "error",
                "text_hi": "अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।",
                "source": "fallback",
                "error": str(error),
                "mode": mode,
            }
    finally:
        _gemini_inflight_lock.release()

    if include_image:
        result["image_jpeg_b64"] = base64.b64encode(jpeg).decode("ascii")
    return _finish("describe_frame", start, result)


def describe_scene_auto(frame, *, include_image: bool = True) -> dict:
    """Ambient object/space description, not OCR.

    Triggered by the glasses' camera schedule instead of a button press.

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
                text_hi = MOCK_DESCRIBE_HI
                source = "mock"
            else:
                text_hi = _call_gemini(jpeg, key, DESCRIBE_PROMPT)
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
