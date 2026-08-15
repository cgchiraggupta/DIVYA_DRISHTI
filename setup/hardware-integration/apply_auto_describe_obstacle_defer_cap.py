#!/usr/bin/env python3
"""Patch divya_drishti_final.py: cap how long auto scene-describe can be
deferred by obstacle_active.

Bug this fixes: maybe_auto_describe() currently returns unconditionally
every tick while obstacle_active is True, with no time limit. obstacle_active
stays True until CLEAR_CONFIRM_SECONDS (3.0s) of a *stable clear* reading —
but with the default 2.5m sensitivity range, almost any normal indoor room
has *something* (a wall, furniture, a person) within range nearly
continuously. Result: once a scene genuinely changes, auto-describe can be
silently blocked forever indoors, even though the haptic/beep safety alert
for that obstacle has long since fired and gone quiet. This matches the
reported symptom: "I get it one time, but not the other time, for so long."

Fix: track how long a settled+changed scene has been sitting blocked by
obstacle_active. Obstacle safety still wins immediately and for a grace
period (OBSTACLE_DEFER_MAX_SECONDS), but once that grace period elapses,
auto-describe fires anyway instead of waiting indefinitely.

Usage (on the Pi):
    python3 apply_auto_describe_obstacle_defer_cap.py /home/pi/divya_drishti_final.py
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD_CONSTANTS = """SCENE_CHANGE_MIN_DIFF = 18.0       # settled frame vs last-described frame must differ at least this much
AUTO_DESCRIBE_MAX_WAIT_SECONDS = 20.0  # give up retrying a "busy" (Gemini in use) attempt after this long"""

NEW_CONSTANTS = """SCENE_CHANGE_MIN_DIFF = 18.0       # settled frame vs last-described frame must differ at least this much
AUTO_DESCRIBE_MAX_WAIT_SECONDS = 20.0  # give up retrying a "busy" (Gemini in use) attempt after this long
# A normal indoor room almost always has *something* within the default 2.5m
# sensitivity range (a wall, furniture, a person), so obstacle_active can
# stay true nearly continuously. Without a cap, a genuinely new scene would
# never get described indoors. Obstacle safety still wins immediately and
# for this grace period, then auto-describe goes ahead anyway.
OBSTACLE_DEFER_MAX_SECONDS = 6.0"""

OLD_STATE = """_auto_describe_state = {
    "ref_gray": None,
    "prev_gray": None,
    "settled_since": None,
    "attempt_in_flight": False,
}"""

NEW_STATE = """_auto_describe_state = {
    "ref_gray": None,
    "prev_gray": None,
    "settled_since": None,
    "attempt_in_flight": False,
    "obstacle_blocked_since": None,
}"""

OLD_GATE = """        if obstacle_active:
            # Obstacle safety audio wins right now. Leave ref_gray alone so
            # "changed" stays true and this fires on a later tick instead,
            # right after the obstacle clears.
            return

        scene["attempt_in_flight"] = True"""

NEW_GATE = """        if obstacle_active:
            # Obstacle safety audio wins right now, and for a short grace
            # period after — but not forever, or a normal room (something
            # is almost always within range) would block this permanently.
            if scene["obstacle_blocked_since"] is None:
                scene["obstacle_blocked_since"] = now
                return
            if now - scene["obstacle_blocked_since"] < OBSTACLE_DEFER_MAX_SECONDS:
                return
            # Waited long enough — describe anyway, same as if obstacle
            # had cleared. Falls through to the existing fire-thread path.
        scene["obstacle_blocked_since"] = None

        scene["attempt_in_flight"] = True"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_auto_describe_obstacle_defer_cap.py <path-to-divya_drishti_final.py>")
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    if "OBSTACLE_DEFER_MAX_SECONDS" in text:
        print("Already patched (OBSTACLE_DEFER_MAX_SECONDS present). No changes made.")
        return 0

    for old, name in ((OLD_CONSTANTS, "constants"), (OLD_STATE, "state dict"), (OLD_GATE, "obstacle gate")):
        if old not in text:
            print(f"ERROR: anchor for {name!r} not found — file may have changed. Aborting, no changes written.")
            return 1

    text = text.replace(OLD_CONSTANTS, NEW_CONSTANTS)
    text = text.replace(OLD_STATE, NEW_STATE)
    text = text.replace(OLD_GATE, NEW_GATE)

    path.write_text(text, encoding="utf-8")
    print(f"Patched {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
