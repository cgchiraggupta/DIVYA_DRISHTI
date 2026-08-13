#!/usr/bin/env python3
"""Correct the ToF side mapping — the wiring is the mirror of what code assumed.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Field check 2026-08-11: the module wired to bus 3 physically sits on the
wearer's RIGHT and the bus 4 module on their LEFT, so every directional cue
(haptic side and spoken "left"/"right") was mirrored. Only the bus-to-side
mapping changes; thresholds and zone filtering stay as they are.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "bus 4 (GPIO17/27" in text and 'init_sensor("LEFT", 4)' in text:
    raise SystemExit("side swap already applied")

OLD_DOC = '''    Sensor 1 (LEFT)  -> bus 3 (GPIO23/24, Pin 16/18)
    Sensor 2 (RIGHT) -> bus 4 (GPIO17/27, Pin 11/13)
    Independent buses, both at default address 0x29 - no conflict.
'''

NEW_DOC = '''    Sensor on bus 4 (GPIO17/27, Pin 11/13) faces the wearer's LEFT.
    Sensor on bus 3 (GPIO23/24, Pin 16/18) faces the wearer's RIGHT.
    Verified against the built frame — the earlier mapping was mirrored, which
    made the glasses buzz and say the opposite side.
    Independent buses, both at default address 0x29 - no conflict.
'''

if OLD_DOC not in text:
    raise SystemExit("init_tof_sensors docstring not found")
text = text.replace(OLD_DOC, NEW_DOC, 1)

OLD_INIT = '''    tof1, bus3 = init_sensor("LEFT", 3)
    tof2, bus4 = init_sensor("RIGHT", 4)
'''

NEW_INIT = '''    tof1, bus4 = init_sensor("LEFT", 4)
    tof2, bus3 = init_sensor("RIGHT", 3)
'''

if OLD_INIT not in text:
    raise SystemExit("init_sensor call pair not found")
text = text.replace(OLD_INIT, NEW_INIT, 1)

PATH.write_text(text)
print("OK: ToF left/right mapping swapped in", PATH)
