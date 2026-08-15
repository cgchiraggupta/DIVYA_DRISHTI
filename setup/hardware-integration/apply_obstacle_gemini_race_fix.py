#!/usr/bin/env python3
"""Fix the obstacle-Gemini race: treat "busy" like cooldown/skipped, and log
the real error instead of just printing "fallback" with no reason.

The actual race fix lives in gemini_describe.py (single in-flight lock).
This patch only updates how divya_drishti_final.py's worker reacts to the
new "busy" status describe_obstacle() can now return.

Run against a copy first, review the diff, then apply to the real file.
"""

from pathlib import Path
import sys

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/pi/divya_drishti_final.py")
text = TARGET.read_text(encoding="utf-8")
original = text

OLD = '''        if result.get("status") in ("cooldown", "skipped"):
            return
        text_hi = (result.get("text_hi") or "").strip()
        if not text_hi:
            return
        payload = {
            "kind": "obstacle",
            "event_type": event_type,
            "direction": direction,
            "distance_mm": distance_mm,
            "speak_hi": text_hi,
            "text_hi": text_hi,
            "image_jpeg_b64": "",
            "source": result.get("source"),
            "speak": True,
            "replaces_alert_id": alert_id,
        }
        publish_phone_alert(payload)
        queue_event(event_type, {
            "distance_mm": distance_mm,
            "direction": direction,
            "message": text_hi,
            "speak_hi": text_hi,
            "object_label": text_hi,
            "gemini": True,
        })
        print(f"[DESCRIBE] Obstacle Gemini ready ({result.get('source')})")
    except Exception as error:
        print(f"[DESCRIBE] Obstacle guidance failed: {error}")'''

NEW = '''        # "busy": another obstacle call is already in flight (Gemini allows
        # only one at a time now). The phone already has the instant distance
        # line, so just leave it — no point overwriting it with nothing.
        if result.get("status") in ("cooldown", "skipped", "busy"):
            return
        text_hi = (result.get("text_hi") or "").strip()
        if not text_hi:
            return
        if result.get("status") == "error":
            print(f"[DESCRIBE] Obstacle Gemini fallback, reason: {result.get('error')}")
        payload = {
            "kind": "obstacle",
            "event_type": event_type,
            "direction": direction,
            "distance_mm": distance_mm,
            "speak_hi": text_hi,
            "text_hi": text_hi,
            "image_jpeg_b64": "",
            "source": result.get("source"),
            "speak": True,
            "replaces_alert_id": alert_id,
        }
        publish_phone_alert(payload)
        queue_event(event_type, {
            "distance_mm": distance_mm,
            "direction": direction,
            "message": text_hi,
            "speak_hi": text_hi,
            "object_label": text_hi,
            "gemini": True,
        })
        print(f"[DESCRIBE] Obstacle Gemini ready ({result.get('source')})")
    except Exception as error:
        print(f"[DESCRIBE] Obstacle guidance failed: {error}")'''

if OLD not in text:
    print("ERROR: obstacle_phone_guidance_worker body not found as expected", file=sys.stderr)
    sys.exit(1)

text = text.replace(OLD, NEW, 1)

if text == original:
    print("No changes needed (already patched).")
    sys.exit(0)

TARGET.write_text(text, encoding="utf-8")
print("Patched", TARGET)
print("Bytes:", len(original), "->", len(text))
