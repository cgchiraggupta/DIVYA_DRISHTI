#!/usr/bin/env python3
"""Send every spoken line to the paired phone instead of the glasses speaker.

Patches /home/pi/divya_drishti_final.py (show + approve before apply/restart).

The glasses speaker is dead/garbled, so speak() now publishes the text as a
phone alert (speak: true) and skips espeak. This covers obstacle announcements,
"Path clear", and every voice-command reply with one change.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "GLASSES_SPEAKER_ENABLED" in text:
    raise SystemExit("phone-audio-only already applied")

OLD = '''def speak(text, blocking=False, volume=None):
    print(f"[AUDIO] {text}")
    env = {**os.environ, "AUDIODEV": "plughw:0,0"}
'''

NEW = '''# Glasses speaker is unreliable, so the phone is the only guidance voice.
# Flip to True only after the speaker hardware is replaced and verified.
GLASSES_SPEAKER_ENABLED = False


def speak(text, blocking=False, volume=None):
    print(f"[AUDIO] {text}")
    try:
        publish_phone_alert({
            "kind": "announcement",
            "event_type": "system",
            "direction": None,
            "distance_mm": None,
            "speak_hi": text,
            "text_hi": text,
            "image_jpeg_b64": "",
            "source": "glasses_voice",
            "speak": True,
        })
    except Exception as error:
        print(f"[AUDIO] Could not hand speech to the phone: {error}")
    if not GLASSES_SPEAKER_ENABLED:
        return
    env = {**os.environ, "AUDIODEV": "plughw:0,0"}
'''

if OLD not in text:
    raise SystemExit("speak() body not found (already patched?)")

text = text.replace(OLD, NEW, 1)
PATH.write_text(text)
print("OK: phone-audio-only applied to", PATH)
