#!/usr/bin/env python3
"""Split Describe (objects) vs Read (OCR) on the live Pi sensing script.

Patches /home/pi/divya_drishti_final.py only. scp gemini_describe.py first.
"""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

PATH = Path("/home/pi/divya_drishti_final.py")
text = PATH.read_text()

if "describe_frame(frame, include_image=True, mode=command)" in text:
    raise SystemExit("already applied: describe/read mode split")

OLD = '''                result = describe_frame(frame, include_image=True)
'''
NEW = '''                result = describe_frame(frame, include_image=True, mode=command)
'''
if OLD not in text:
    raise SystemExit("describe_frame call not found")
text = text.replace(OLD, NEW, 1)

OLD_PUB = '''            if result.get("text_hi"):
                publish_phone_alert({
                    "kind": "read",
                    "event_type": "voice_command",
                    "speak_hi": result["text_hi"],
                    "text_hi": result["text_hi"],
                    "image_jpeg_b64": result.get("image_jpeg_b64") or "",
                    "source": result.get("source"),
                    "speak": result.get("status") == "ok",
                })
            # Keep motors quiet while phone speaks; companion can resume via resume/describe-done.
            # Auto-unmute after 20s as a safety net.
            def _unmute_later():
                time.sleep(20)
                set_haptics_muted(False)
            threading.Thread(target=_unmute_later, daemon=True).start()
            queue_event("voice_command", {
                "command": "read",
                "source": "companion_app",
                "status": result.get("status"),
                "speak_hi": result.get("text_hi"),
            })
'''

NEW_PUB = '''            if result.get("text_hi"):
                publish_phone_alert({
                    "kind": command,
                    "event_type": "voice_command",
                    "speak_hi": result["text_hi"],
                    "text_hi": result["text_hi"],
                    "image_jpeg_b64": result.get("image_jpeg_b64") or "",
                    "source": command,
                    # Companion already speaks the HTTP result; don't double-TTS.
                    "speak": False,
                })
            # Keep motors quiet while phone speaks; companion can resume via resume/describe-done.
            # Auto-unmute after 20s as a safety net.
            def _unmute_later():
                time.sleep(20)
                set_haptics_muted(False)
            threading.Thread(target=_unmute_later, daemon=True).start()
            queue_event("voice_command", {
                "command": command,
                "source": "companion_app",
                "status": result.get("status"),
                "speak_hi": result.get("text_hi"),
            })
'''

if OLD_PUB not in text:
    # Older Pi copy may still force speak True without the status check.
    OLD_PUB_ALT = OLD_PUB.replace(
        '"speak": result.get("status") == "ok",',
        '"speak": True,',
    )
    if OLD_PUB_ALT not in text:
        raise SystemExit("publish_phone_alert describe/read block not found")
    text = text.replace(OLD_PUB_ALT, NEW_PUB, 1)
else:
    text = text.replace(OLD_PUB, NEW_PUB, 1)

if "--dry-run" in sys.argv:
    print("OK dry-run: describe/read split would patch", PATH)
    raise SystemExit(0)

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = PATH.with_name(f"divya_drishti_final.py.bak-describe-read-{stamp}")
shutil.copy2(PATH, backup)
PATH.write_text(text)
print("OK: apply_describe_read_split patched", PATH)
print("backup:", backup)
