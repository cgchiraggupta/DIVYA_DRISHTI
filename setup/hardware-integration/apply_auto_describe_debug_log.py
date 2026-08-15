#!/usr/bin/env python3
"""Patch divya_drishti_final.py: add a rate-limited diagnostic print inside
maybe_auto_describe() so we can see WHY it isn't firing instead of guessing
from silence in the logs.

Right now there is zero log output while auto-describe stays blocked,
whether that's because the scene never settles (continuous motion in view)
or because it settles but never differs enough from the reference frame —
no way to tell which gate is the actual blocker. This adds one print, at
most every 2 seconds, showing:
  - frame_diff vs the settle threshold, and how long it's been settled
  - how different the (once-settled) frame is from the last-described
    reference frame, vs the threshold that must be crossed
  - whether obstacle_active is currently blocking it

Usage (on the Pi):
    python3 apply_auto_describe_debug_log.py /home/pi/divya_drishti_final.py
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD = """        frame_diff = _mean_abs_diff(gray, scene["prev_gray"])
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
            return"""

NEW = """        frame_diff = _mean_abs_diff(gray, scene["prev_gray"])
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
                f"(need>={SCENE_CHANGE_MIN_DIFF}) obstacle_active={obstacle_active}"
            )

        if scene["settled_since"] is None:
            return

        if now - scene["settled_since"] < SCENE_SETTLE_SECONDS:
            return

        if _mean_abs_diff(gray, scene["ref_gray"]) < SCENE_CHANGE_MIN_DIFF:
            return"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_auto_describe_debug_log.py <path-to-divya_drishti_final.py>")
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    if "Auto scene-describe check:" in text:
        print("Already patched. No changes made.")
        return 0

    if OLD not in text:
        print("ERROR: anchor not found — file may have changed. Aborting, no changes written.")
        return 1

    text = text.replace(OLD, NEW)
    path.write_text(text, encoding="utf-8")
    print(f"Patched {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
