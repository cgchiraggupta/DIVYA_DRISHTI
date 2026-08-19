#!/usr/bin/env python3
"""Cane-style opening burst: warn on closing / <50cm, not mere presence.

Patches /home/pi/divya_drishti_final.py (backup, then apply).

Live Pi already has the 3s continuous-buzz cap. This only changes:
- First alert requires urgent, approaching, or no ToF number (ahead AND side).
- Phone speaks only for urgent, ahead, or camera fallback.
- Gemini obstacle naming runs only when we are going to speak.

Show + approve before restart. Rollback: restore the .bak next to the file.
"""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "opening_worthy" in text:
    raise SystemExit("opening_worthy already present — already applied?")

OLD_COMMENT = '''            if side is not None:
                # Speak new or materially changed guidance once. While an
                # obstacle remains, repeat only its directional haptic cue.
'''

NEW_COMMENT = '''            if side is not None:
                # Cane, not tour guide: buzz when closing in or already close.
                # While an obstacle remains, repeat only its directional haptic.
'''

if OLD_COMMENT not in text:
    raise SystemExit("obstacle-block comment not found")
text = text.replace(OLD_COMMENT, NEW_COMMENT, 1)

OLD_SHOULD = '''                should_alert = (
                    not obstacle_active
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= side_realert_seconds)
                )
                if should_alert and seconds_since_alert < MIN_BURST_GAP_SECONDS:
                    should_alert = False

                if should_alert:
'''

NEW_SHOULD = '''                # Presence in the 2 m cone is not a warning. Warn if:
                # already in the face (<50 cm), or distance is falling, or
                # there is no ToF number (camera fallback — don't go mute).
                opening_worthy = (
                    in_urgent
                    or approaching_now
                    or distance_mm is None
                )
                should_alert = (
                    (not obstacle_active and opening_worthy)
                    or (urgent_change and seconds_since_alert >= URGENT_REALERT_SECONDS)
                    or (direction_changed and seconds_since_alert >= side_realert_seconds)
                )
                if should_alert and seconds_since_alert < MIN_BURST_GAP_SECONDS:
                    should_alert = False
                # Ears need traffic, not a list of bowls. Speak only when it
                # is in the forward path or already urgent. Side pass-bys
                # are a left/right buzz; double-tap Describe if they want the name.
                speak_now = in_urgent or (not side_only) or distance_mm is None

                if should_alert:
'''

if OLD_SHOULD not in text:
    raise SystemExit("should_alert block not found")
text = text.replace(OLD_SHOULD, NEW_SHOULD, 1)

OLD_SPEAK = '''                        # Phone TTS is primary while glasses speaker is unreliable.
                        "speak": True,
                    })
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
                    queue_event(event_type, event_detail)
                    if frame_copy is not None:
'''

NEW_SPEAK = '''                        # Phone TTS is primary while glasses speaker is unreliable.
                        "speak": speak_now,
                    })
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
                    queue_event(event_type, event_detail)
                    if speak_now and frame_copy is not None:
'''

if OLD_SPEAK not in text:
    raise SystemExit("speak/frame_copy block not found")
text = text.replace(OLD_SPEAK, NEW_SPEAK, 1)

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = PATH.with_name(f"divya_drishti_final.py.bak-opening-burst-{stamp}")
if "--dry-run" in sys.argv:
    print("OK dry-run: all anchors matched; would write", PATH, "backup", backup)
    raise SystemExit(0)

shutil.copy2(PATH, backup)
PATH.write_text(text)
print("OK: apply_opening_burst_gate patched", PATH)
print("backup:", backup)
