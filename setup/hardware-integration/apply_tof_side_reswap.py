#!/usr/bin/env python3
"""Interchange the two ToF I2C buses' LEFT/RIGHT assignment.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Field report 2026-08-14: after the previous side-swap fix, the mapping is
backwards again — the bus wired to the wearer's LEFT is driving the RIGHT-side
alert/vibration and vice versa. This just swaps which bus number is called
LEFT vs RIGHT back to bus3=LEFT / bus4=RIGHT. It does not touch the
`dtoverlay=i2c-gpio` bus-to-GPIO wiring in /boot/firmware/config.txt (bus 3 =
GPIO23/24, bus 4 = GPIO17/27) — only the software label changes.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "bus 3 (GPIO23/24" in text and 'init_sensor("LEFT", 3)' in text:
    raise SystemExit("side re-swap already applied")

OLD_DOC = '''    Sensor on bus 4 (GPIO17/27, Pin 11/13) faces the wearer's LEFT.
    Sensor on bus 3 (GPIO23/24, Pin 16/18) faces the wearer's RIGHT.
    Verified against the built frame — the earlier mapping was mirrored, which
    made the glasses buzz and say the opposite side.
    Independent buses, both at default address 0x29 - no conflict.
'''

NEW_DOC = '''    Sensor on bus 3 (GPIO23/24, Pin 16/18) faces the wearer's LEFT.
    Sensor on bus 4 (GPIO17/27, Pin 11/13) faces the wearer's RIGHT.
    Field report 2026-08-14: the previous mapping had this backwards again
    (left bus was driving the right-side alert/vibration) — swapped back.
    Independent buses, both at default address 0x29 - no conflict.
'''

if OLD_DOC not in text:
    raise SystemExit("init_tof_sensors docstring not found")
text = text.replace(OLD_DOC, NEW_DOC, 1)

OLD_INIT = '''    tof1, bus4 = init_sensor("LEFT", 4)
    tof2, bus3 = init_sensor("RIGHT", 3)
'''

NEW_INIT = '''    tof1, bus3 = init_sensor("LEFT", 3)
    tof2, bus4 = init_sensor("RIGHT", 4)
'''

if OLD_INIT not in text:
    raise SystemExit("init_sensor call pair not found")
text = text.replace(OLD_INIT, NEW_INIT, 1)

PATH.write_text(text)
print("OK: ToF left/right mapping re-swapped in", PATH)
