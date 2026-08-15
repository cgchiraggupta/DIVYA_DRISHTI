#!/usr/bin/env python3
"""Hindi phone alerts with English cm/m, and no obstacle photos to the phone.

Run on the Pi against /home/pi/divya_drishti_final.py
"""

from pathlib import Path
import sys

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/pi/divya_drishti_final.py")
text = TARGET.read_text(encoding="utf-8")
original = text

replacements = [
    (
        '                    dir_word = "Saamne" if direction == "ahead" else direction.capitalize()\n'
        '                    quick_hi = f"{dir_word} obstacle, about {dist_label}."',
        '                    dir_hi = {"ahead": "सामने", "left": "बाईं ओर", "right": "दाईं ओर"}.get(\n'
        '                        str(direction or "ahead").lower(), "सामने"\n'
        '                    )\n'
        '                    quick_hi = f"{dir_hi} बाधा है, लगभग {dist_label}।"',
    ),
    (
        '                            dir_word = "Saamne" if direction == "ahead" else str(direction).capitalize()',
        '                            dir_hi = {"ahead": "सामने", "left": "बाईं ओर", "right": "दाईं ओर"}.get(\n'
        '                                str(direction or "ahead").lower(), "सामने"\n'
        '                            )',
    ),
    (
        '                                "speak_hi": f"{dir_word} obstacle, about {dist_label}.",\n'
        '                                "text_hi": f"{dir_word} obstacle, about {dist_label}.",',
        '                                "speak_hi": f"{dir_hi} बाधा है, लगभग {dist_label}।",\n'
        '                                "text_hi": f"{dir_hi} बाधा है, लगभग {dist_label}।",',
    ),
    (
        '"text_hi": "Camera available nahi hai."',
        '"text_hi": "कैमरा उपलब्ध नहीं है।"',
    ),
    (
        '"text_hi": "Abhi describe nahi ho paya. Thodi der baad phir try karein."',
        '"text_hi": "अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।"',
    ),
    (
        'dist_label = "unknown distance"',
        'dist_label = "अज्ञात दूरी"',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count == 0:
        print(f"WARN: pattern not found:\n{old[:90]}...", file=sys.stderr)
        continue
    text = text.replace(old, new)
    print(f"replaced x{count}: {old.splitlines()[0][:70]}")

# Never send obstacle JPEGs to the phone. Camera still captures in-memory for Gemini.
# Leave the Describe button image path alone (result.get("image_jpeg_b64") or "").
for old_img, new_img in (
    ('"image_jpeg_b64": image_b64,', '"image_jpeg_b64": "",'),
    ('"image_jpeg_b64": result.get("image_jpeg_b64") or image_jpeg_b64 or "",', '"image_jpeg_b64": "",'),
):
    count = text.count(old_img)
    if count == 0:
        print(f"WARN: image pattern not found: {old_img[:70]}", file=sys.stderr)
        continue
    text = text.replace(old_img, new_img)
    print(f"cleared obstacle image field x{count}")

if text == original:
    print("No changes needed (already patched or patterns missing).")
    sys.exit(1)

TARGET.write_text(text, encoding="utf-8")
print("Patched", TARGET)
print("Bytes:", len(original), "->", len(text))
