#!/usr/bin/env python3
"""Reject invalid VL53L5CX zones so a far target is not reported as a few cm.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

The old reader kept every zone with distance > 0 and took min() across all 16.
A single crosstalk/noise zone (cover glass reflection, status != 5) therefore
won a 1.5 m real target and the wearer heard "3 cm". This reader:

- keeps only zones the sensor itself marks as a valid range (target_status)
- drops sub-floor readings that are almost always cover-glass crosstalk
- needs a second nearby zone to confirm a very close reading before trusting it
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

START = "def read_tof(tof1, tof2):"
END = "    # data_ready() can alternate between the two independent sensor buses."

start = text.find(START)
end = text.find(END)
if start == -1 or end == -1 or end <= start:
    raise SystemExit("read_tof block not found (already patched?)")

if "TOF_VALID_STATUSES" in text:
    raise SystemExit("ToF status filter already applied")

NEW = '''# VL53L5CX marks each zone with a ranging status. 5 = valid, 9 = valid but a
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

'''

text = text[:start] + NEW + text[end:]
PATH.write_text(text)
print("OK: ToF status filter applied to", PATH)
