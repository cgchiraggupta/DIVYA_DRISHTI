#!/usr/bin/env python3
"""Buzz the side that is actually blocked instead of always buzzing both motors.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

The old branch was `if tof_left and tof_right:` — both sensors almost always
return some reading, so it took the "both" path on every alert. The left/right
branches were unreachable in practice, so an obstacle on one side still buzzed
both motors and announced "directly ahead".

Now the decision is made on which side is inside the Settings range, and
"both"/ahead is reserved for a wide obstacle that both sensors see at a
similar distance.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "TOF_SIDE_DIFFERENCE_MM" in text:
    raise SystemExit("directional alert fix already applied")

OLD_CONST = "CV_HIGH = 0.020"
NEW_CONST = '''# Both sensors within this spread means one wide obstacle straight ahead.
# A bigger gap means one side is genuinely nearer, so only that motor fires.
TOF_SIDE_DIFFERENCE_MM = 250

CV_HIGH = 0.020'''

if OLD_CONST not in text:
    raise SystemExit("CV_HIGH constant not found")
text = text.replace(OLD_CONST, NEW_CONST, 1)

OLD = '''    # ── ToF path ──
    if tof_left is not None or tof_right is not None:
        vals = [d for d in [tof_left, tof_right] if d is not None]
        closest = min(vals) if vals else None

        # Always respect Settings range first — never alert beyond sensitivity_mm.
        if closest is None or closest >= caution_distance:
            return (None, None, "path clear")

        if tof_left and tof_right:
            dist_cm = max(1, int(round(closest / 10.0)))
            if closest < TOF_URGENT_MM:
                return ("both", "rapid", f"obstacle directly ahead, {dist_cm} centimeters")
            if closest < TOF_WARNING_MM:
                return ("both", "double", f"obstacle ahead, {dist_cm} centimeters")
            return ("both", "single", "object nearby ahead")
        if tof_left and tof_left < caution_distance:
            dist_cm = max(1, int(round(tof_left / 10.0)))
            if tof_left < TOF_URGENT_MM:
                return ("left", "rapid", f"obstacle very close on left, {dist_cm} centimeters")
            if tof_left < TOF_WARNING_MM:
                return ("left", "double", f"obstacle on left, {dist_cm} centimeters")
            return ("left", "single", "object nearby on left")
        if tof_right and tof_right < caution_distance:
            dist_cm = max(1, int(round(tof_right / 10.0)))
            if tof_right < TOF_URGENT_MM:
                return ("right", "rapid", f"obstacle very close on right, {dist_cm} centimeters")
            if tof_right < TOF_WARNING_MM:
                return ("right", "double", f"obstacle on right, {dist_cm} centimeters")
            return ("right", "single", "object nearby on right")

        return (None, None, "path clear")
'''

NEW = '''    # ── ToF path ──
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
'''

if OLD not in text:
    raise SystemExit("decide_alert ToF block not found (already patched?)")

text = text.replace(OLD, NEW, 1)
PATH.write_text(text)
print("OK: directional alert fix applied to", PATH)
