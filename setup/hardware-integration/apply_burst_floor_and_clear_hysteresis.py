#!/usr/bin/env python3
"""Make continuous buzzing impossible and stop false "path clear" flapping.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Measured on a stationary rig: the side stayed "right" for the whole window yet
five opening bursts fired in 30 s. The cause was not a side flip — the ToF
reading briefly dropped out, the loop declared "path clear", reset
obstacle_active, and the returning reading counted as a brand new obstacle.

Three changes:
- a hard floor between opening bursts, so no code path can buzz faster
- a longer stable-clear requirement before an obstacle is considered gone
- a longer sample hold, so a single dropped frame is not treated as clear

Also gates the per-frame [DEBUG] print behind DIVYA_TOF_DEBUG=1, because it was
flooding journald and causing real events to be rate-limited out of the log.
"""
import os
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "MIN_BURST_GAP_SECONDS" in text:
    raise SystemExit("burst floor already applied")

# 1. Constants
OLD_CONST = "URGENT_REALERT_SECONDS = 1.0"
NEW_CONST = '''URGENT_REALERT_SECONDS = 1.0
# No code path may restart the opening burst faster than this.
MIN_BURST_GAP_SECONDS = 2.0
# A dropped reading is not a clear path — require this much steady clear first.
CLEAR_CONFIRM_SECONDS = 3.0'''

if OLD_CONST not in text:
    raise SystemExit("URGENT_REALERT_SECONDS not found — apply the re-alert patch first")
text = text.replace(OLD_CONST, NEW_CONST, 1)

# 2. Longer sample hold across dropped frames
OLD_HOLD = "TOF_SAMPLE_HOLD_SECONDS = 0.9"
NEW_HOLD = "TOF_SAMPLE_HOLD_SECONDS = 1.5"
if OLD_HOLD not in text:
    raise SystemExit("TOF_SAMPLE_HOLD_SECONDS not found")
text = text.replace(OLD_HOLD, NEW_HOLD, 1)

# 3. Hard floor on burst frequency
OLD_SHOULD = '''                should_alert = (
                    not obstacle_active
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= SIDE_REALERT_SECONDS)
                )
'''
NEW_SHOULD = '''                should_alert = (
                    not obstacle_active
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= SIDE_REALERT_SECONDS)
                )
                if should_alert and seconds_since_alert < MIN_BURST_GAP_SECONDS:
                    should_alert = False
'''
if OLD_SHOULD not in text:
    raise SystemExit("should_alert block not found")
text = text.replace(OLD_SHOULD, NEW_SHOULD, 1)

# 4. Longer stable clear
OLD_CLEAR = "                    if now - clear_since >= 2.0:"
NEW_CLEAR = "                    if now - clear_since >= CLEAR_CONFIRM_SECONDS:"
if OLD_CLEAR not in text:
    raise SystemExit("clear_since threshold not found")
text = text.replace(OLD_CLEAR, NEW_CLEAR, 1)

# 5. Quiet the per-frame debug print
OLD_DEBUG = '            print(f"[DEBUG] tof_left={tof_left} tof_right={tof_right} -> side={side} pattern={pattern} msg={message}")\n'
NEW_DEBUG = '''            if TOF_DEBUG:
                print(f"[DEBUG] tof_left={tof_left} tof_right={tof_right} -> side={side} pattern={pattern} msg={message}")
'''
if OLD_DEBUG in text:
    text = text.replace(OLD_DEBUG, NEW_DEBUG, 1)
    text = text.replace(
        NEW_HOLD,
        NEW_HOLD + '\n# Per-frame ToF logging floods journald; enable only while debugging.\nTOF_DEBUG = os.environ.get("DIVYA_TOF_DEBUG") == "1"',
        1,
    )
else:
    print("NOTE: per-frame debug print not found, skipping log gate")

PATH.write_text(text)
print("OK: burst floor + clear hysteresis applied to", PATH)
