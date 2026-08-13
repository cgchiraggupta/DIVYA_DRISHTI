#!/usr/bin/env python3
"""Standing = 2 buzz then quiet; walking into obstacle = keep buzzing.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

Behavior:
- New obstacle: two haptic pulses (same urgency pattern), photo → phone, no glasses TTS
  (phone app speaks guidance).
- If distance stays stable: stop haptic reminders.
- If distance is falling (person moving closer): keep repeating haptics until clear
  or they stop closing in.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

OLD_CONST = '''# Persistent obstacles repeat as haptic-only guidance. Each interval is
# longer than its vibration pattern so motor requests cannot build up.
HAPTIC_REPEAT_SECONDS = {
    "single": 2.5,
    "double": 1.5,
    "rapid": 0.9,
}
'''

NEW_CONST = '''# Persistent obstacles repeat as haptic-only guidance only while the wearer
# is still closing distance. Standing still after the opening burst stays quiet.
# Each interval is longer than its vibration pattern so motor requests cannot build up.
HAPTIC_REPEAT_SECONDS = {
    "single": 2.5,
    "double": 1.5,
    "rapid": 0.9,
}
# Motion heuristics from ToF (no IMU): cm-scale deltas over a short window.
HAPTIC_STATIONARY_TOLERANCE_MM = 80
HAPTIC_APPROACH_DELTA_MM = 50
HAPTIC_MOTION_WINDOW_S = 1.0
HAPTIC_OPENING_BURST_COUNT = 2
'''

if OLD_CONST not in text:
    raise SystemExit("HAPTIC_REPEAT_SECONDS block not found (already patched?)")
text = text.replace(OLD_CONST, NEW_CONST, 1)

# Insert burst helper after vibrate_pattern if missing.
if "def deliver_haptic_burst(" not in text:
    marker = "def deliver_alert(side, pattern, message):"
    if marker not in text:
        raise SystemExit("deliver_alert not found")
    helper = '''def deliver_haptic_burst(side, pattern, count=HAPTIC_OPENING_BURST_COUNT):
    """Two (or count) haptic pulses, then stop — used for the opening warning."""
    def run():
        for index in range(max(1, int(count))):
            deliver_alert(side, pattern, None)
            if index + 1 < count:
                # Gap longer than one rapid pulse so the wearer feels two distinct hits.
                time.sleep(0.55 if pattern == "rapid" else 0.4)
    threading.Thread(target=run, daemon=True).start()


'''
    text = text.replace(marker, helper + marker, 1)

OLD_LOOP_INIT = '''    last_alert = 0
    last_alert_distance = None
    last_alert_side = None
    last_alert_pattern = None
    last_alert_message = None
    obstacle_active = False
    clear_since = None
    last_status_sync = 0
'''

NEW_LOOP_INIT = '''    last_alert = 0
    last_alert_distance = None
    last_alert_side = None
    last_alert_pattern = None
    last_alert_message = None
    obstacle_active = False
    clear_since = None
    last_status_sync = 0
    # After the opening double-buzz: quiet if standing, repeat only while approaching.
    haptic_quiet = False
    approach_active = False
    opening_burst_at = None
    distance_samples = []
'''

if OLD_LOOP_INIT not in text:
    raise SystemExit("detection_loop init block not found")
text = text.replace(OLD_LOOP_INIT, NEW_LOOP_INIT, 1)

OLD_ALERT_LOGIC = '''                severity = {"single": 1, "double": 2, "rapid": 3}.get(pattern, 0)
                previous_severity = {"single": 1, "double": 2, "rapid": 3}.get(last_alert_pattern, 0)
                direction_changed = obstacle_active and side != last_alert_side
                escalated = obstacle_active and severity > previous_severity
                moved_closer = (
                    obstacle_active and distance_mm is not None and
                    last_alert_distance is not None and
                    distance_mm <= last_alert_distance - 300
                )
                reminder_interval = HAPTIC_REPEAT_SECONDS.get(pattern, 2.5)
                haptic_reminder = obstacle_active and (now - last_alert) >= reminder_interval
                should_alert = not obstacle_active or direction_changed or escalated or moved_closer

                if should_alert:
'''

NEW_ALERT_LOGIC = '''                severity = {"single": 1, "double": 2, "rapid": 3}.get(pattern, 0)
                previous_severity = {"single": 1, "double": 2, "rapid": 3}.get(last_alert_pattern, 0)
                direction_changed = obstacle_active and side != last_alert_side
                escalated = obstacle_active and severity > previous_severity
                moved_closer = (
                    obstacle_active and distance_mm is not None and
                    last_alert_distance is not None and
                    distance_mm <= last_alert_distance - 300
                )
                if distance_mm is not None:
                    distance_samples.append((now, distance_mm))
                    distance_samples[:] = [
                        sample for sample in distance_samples
                        if now - sample[0] <= HAPTIC_MOTION_WINDOW_S
                    ]
                approaching_now = False
                stationary_now = False
                if len(distance_samples) >= 2:
                    oldest_d = distance_samples[0][1]
                    newest_d = distance_samples[-1][1]
                    approaching_now = newest_d <= oldest_d - HAPTIC_APPROACH_DELTA_MM
                    stationary_now = abs(newest_d - oldest_d) <= HAPTIC_STATIONARY_TOLERANCE_MM
                if opening_burst_at is not None and (now - opening_burst_at) >= 0.8:
                    if approaching_now:
                        approach_active = True
                        haptic_quiet = False
                    elif stationary_now:
                        approach_active = False
                        haptic_quiet = True
                if haptic_quiet and approaching_now:
                    # Was standing; started walking into the obstacle again.
                    approach_active = True
                    haptic_quiet = False
                reminder_interval = HAPTIC_REPEAT_SECONDS.get(pattern, 2.5)
                haptic_reminder = (
                    obstacle_active
                    and approach_active
                    and not haptic_quiet
                    and (now - last_alert) >= reminder_interval
                )
                should_alert = not obstacle_active or direction_changed or escalated or moved_closer

                if should_alert:
'''

if OLD_ALERT_LOGIC not in text:
    raise SystemExit("should_alert logic block not found")
text = text.replace(OLD_ALERT_LOGIC, NEW_ALERT_LOGIC, 1)

OLD_PUBLISH = '''                    instant = publish_phone_alert({
                        "kind": "obstacle_snapshot",
                        "event_type": event_type,
                        "direction": direction,
                        "distance_mm": distance_mm,
                        "speak_hi": quick_hi,
                        "text_hi": quick_hi,
                        "image_jpeg_b64": image_b64,
                        "source": "tof_snapshot",
                        "speak": False,
                    })
                    threading.Thread(target=deliver_alert, args=(side, pattern, announcement)).start()
'''

NEW_PUBLISH = '''                    instant = publish_phone_alert({
                        "kind": "obstacle_snapshot",
                        "event_type": event_type,
                        "direction": direction,
                        "distance_mm": distance_mm,
                        "speak_hi": quick_hi,
                        "text_hi": quick_hi,
                        "image_jpeg_b64": image_b64,
                        "source": "tof_snapshot",
                        # Phone TTS is primary while glasses speaker is unreliable.
                        "speak": True,
                    })
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
'''

if OLD_PUBLISH not in text:
    raise SystemExit("tof_snapshot publish block not found")
text = text.replace(OLD_PUBLISH, NEW_PUBLISH, 1)

# After should_alert bookkeeping, reset motion state for a fresh obstacle.
OLD_ACTIVE = '''                    last_alert = now
                    last_alert_distance = distance_mm
                    last_alert_side = side
                    last_alert_pattern = pattern
                    last_alert_message = message
                    obstacle_active = True
                    with state_lock:
                        state["last_alert_side"] = side
                        state["last_alert_zone"] = pattern
'''

NEW_ACTIVE = '''                    last_alert = now
                    last_alert_distance = distance_mm
                    last_alert_side = side
                    last_alert_pattern = pattern
                    last_alert_message = message
                    obstacle_active = True
                    haptic_quiet = False
                    approach_active = False
                    opening_burst_at = now
                    distance_samples = [(now, distance_mm)] if distance_mm is not None else []
                    with state_lock:
                        state["last_alert_side"] = side
                        state["last_alert_zone"] = pattern
'''

if OLD_ACTIVE not in text:
    raise SystemExit("obstacle_active bookkeeping block not found")
text = text.replace(OLD_ACTIVE, NEW_ACTIVE, 1)

OLD_CLEAR = '''                        obstacle_active = False
                        last_alert_distance = None
                        last_alert_side = None
                        last_alert_pattern = None
                        last_alert_message = None
'''

NEW_CLEAR = '''                        obstacle_active = False
                        last_alert_distance = None
                        last_alert_side = None
                        last_alert_pattern = None
                        last_alert_message = None
                        haptic_quiet = False
                        approach_active = False
                        opening_burst_at = None
                        distance_samples = []
'''

if OLD_CLEAR not in text:
    raise SystemExit("path_clear reset block not found")
text = text.replace(OLD_CLEAR, NEW_CLEAR, 1)

# Live photo refresh only while approach buzz is active (not while standing quiet).
OLD_REM = '''                elif haptic_reminder:
                    # No message = vibration only; no repeated speech/events.
                    threading.Thread(target=deliver_alert, args=(side, pattern, None)).start()
'''

NEW_REM = '''                elif haptic_reminder:
                    # Approaching only: keep buzzing. No glasses speech (phone already guided).
                    threading.Thread(target=deliver_alert, args=(side, pattern, None)).start()
'''

if OLD_REM not in text:
    raise SystemExit("haptic_reminder block not found")
text = text.replace(OLD_REM, NEW_REM, 1)

PATH.write_text(text)
print("OK: apply_haptic_motion_quiet patched", PATH)
