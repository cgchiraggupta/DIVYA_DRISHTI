#!/usr/bin/env python3
"""Stop sensor flicker from restarting the opening buzz over and over.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Either ToF module drops in and out of validity between frames, so the chosen
side flips (right -> both -> left -> right). Every flip counted as a direction
change, fired a fresh two-pulse burst, and the wearer felt one long buzz.

A re-alert now needs a minimum gap: 2.5 s for a side change, 1.0 s when the
obstacle genuinely escalates or closes in. A brand new obstacle still alerts
immediately, so nothing is delayed on first detection.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "SIDE_REALERT_SECONDS" in text:
    raise SystemExit("re-alert rate limit already applied")

OLD_CONST = "HAPTIC_OPENING_BURST_COUNT = 2"
NEW_CONST = '''HAPTIC_OPENING_BURST_COUNT = 2
# Minimum gap before the opening burst may fire again for the same obstacle.
# Without this, a flickering sensor restarts the burst every few frames.
SIDE_REALERT_SECONDS = 2.5
URGENT_REALERT_SECONDS = 1.0'''

if OLD_CONST not in text:
    raise SystemExit("HAPTIC_OPENING_BURST_COUNT not found")
text = text.replace(OLD_CONST, NEW_CONST, 1)

OLD = "                should_alert = not obstacle_active or direction_changed or escalated or moved_closer\n"

NEW = '''                seconds_since_alert = now - last_alert
                urgent_change = escalated or moved_closer
                should_alert = (
                    not obstacle_active
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= SIDE_REALERT_SECONDS)
                )
'''

if OLD not in text:
    raise SystemExit("should_alert line not found (already patched?)")

text = text.replace(OLD, NEW, 1)
PATH.write_text(text)
print("OK: re-alert rate limit applied to", PATH)
