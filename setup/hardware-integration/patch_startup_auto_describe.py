#!/usr/bin/env python3
"""One-shot patch for live Pi divya_drishti_final.py — startup auto-describe + manual read speak."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/pi/divya_drishti_final.py")
    text = path.read_text(encoding="utf-8")

    text = text.replace(
        "AUTO_DESCRIBE_MAX_WAIT_SECONDS = 20.0",
        "AUTO_DESCRIBE_MAX_WAIT_SECONDS = 45.0",
    )

    if "startup_describe_due" not in text:
        text = text.replace(
            '"last_spoken_at": None,\n}',
            '"last_spoken_at": None,\n    "startup_describe_due": True,\n}',
        )

    if "def reset_auto_describe_schedule" not in text:
        marker = '\n    "last_spoken_at": None,  # time.monotonic() of the last successful ambient describe\n}\n\n\ndef _scene_gray(frame):'
        if marker not in text:
            marker = '\n}\n\n\ndef _scene_gray(frame):'
        reset_fn = """

def reset_auto_describe_schedule(*, reason: str = "camera") -> None:
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
"""
        if marker not in text:
            print("Could not find insertion point for reset_auto_describe_schedule")
            return 1
        text = text.replace(marker, '\n    "startup_describe_due": True,\n}' + reset_fn + '\n\ndef _scene_gray(frame):', 1)

    needle = '_auto_describe_state["last_spoken_at"] = time.monotonic()'
    if needle in text and "startup_describe_due" not in text.split(needle)[1][:120]:
        text = text.replace(
            needle,
            needle + '\n                        _auto_describe_state["startup_describe_due"] = False',
            1,
        )

    if "startup_due={scene.get" not in text:
        text = text.replace(
            'f"(need>={SCENE_CHANGE_MIN_DIFF}) obstacle_active={obstacle_active}"',
            'f"(need>={SCENE_CHANGE_MIN_DIFF}) obstacle_active={obstacle_active} "\n                f"startup_due={scene.get(\'startup_describe_due\')}"',
            1,
        )

    old_gate = """        # Ambient interval gate: this is the primary trigger now (see the
        # 2026-08-18 note above), not "did the scene change enough". Fires
        # once on first settle (last_spoken_at is None), then every
        # AUTO_DESCRIBE_INTERVAL_SECONDS after that.
        last_spoken_at = scene.get("last_spoken_at")
        if last_spoken_at is not None and now - last_spoken_at < AUTO_DESCRIBE_INTERVAL_SECONDS:
            return

        if last_spoken_at is not None and _mean_abs_diff(gray, scene["ref_gray"]) < SCENE_CHANGE_MIN_DIFF:
            # Interval is due, but the camera is looking at the exact same
            # static frame as last time -- nothing new to say, skip the
            # Gemini call and check again on the next settled frame.
            return

        if obstacle_active:"""

    new_gate = """        startup_due = bool(scene.get("startup_describe_due"))
        last_spoken_at = scene.get("last_spoken_at")

        if not startup_due:
            if last_spoken_at is not None and now - last_spoken_at < AUTO_DESCRIBE_INTERVAL_SECONDS:
                return
            if (
                last_spoken_at is not None
                and _mean_abs_diff(gray, scene["ref_gray"]) < SCENE_CHANGE_MIN_DIFF
            ):
                return

        if obstacle_active and not startup_due:"""

    if old_gate in text:
        text = text.replace(old_gate, new_gate, 1)
        text = text.replace(
            "        scene[\"obstacle_blocked_since\"] = None\n\n        scene[\"attempt_in_flight\"] = True",
            "        scene[\"obstacle_blocked_since\"] = None\n        if startup_due:\n            scene[\"startup_describe_due\"] = False\n\n        scene[\"attempt_in_flight\"] = True",
            1,
        )

    text = text.replace(
        'if result.get("status") == "ok" and result.get("text_hi"):\n                publish_phone_alert({',
        'if result.get("text_hi"):\n                publish_phone_alert({',
        1,
    )
    text = text.replace(
        '"speak": False,\n                })\n            # Keep motors quiet',
        '"speak": result.get("status") == "ok",\n                })\n            # Keep motors quiet',
        1,
    )

    if 'reset_auto_describe_schedule(reason="camera ready")' not in text:
        text = text.replace(
            '        speak("Camera ready.")\n',
            '        speak("Camera ready.")\n        reset_auto_describe_schedule(reason="camera ready")\n',
            1,
        )

    path.write_text(text, encoding="utf-8")
    print(f"Patched {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
