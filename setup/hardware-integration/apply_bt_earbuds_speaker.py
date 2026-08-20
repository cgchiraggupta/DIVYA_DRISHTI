#!/usr/bin/env python3
"""Route glasses TTS to paired Nirvana Ion earbuds instead of the phone speaker.

Patches /home/pi/divya_drishti_final.py. Does not restart sensing.
"""
from pathlib import Path

PATH = Path("/home/pi/divya_drishti_final.py")
BACKUP = Path("/home/pi/divya_drishti_final.py.bak-bt-speaker")
text = PATH.read_text()
if not BACKUP.exists():
    BACKUP.write_text(text)
    print("backup", BACKUP)

OLD_SPEAK = '''# Glasses speaker is unreliable, so the phone is the only guidance voice.
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
    args = ["espeak", "-s", "140", "-v", "en", text]
    if volume is not None:
        args[1:1] = ["-a", str(max(20, min(100, int(volume))))]
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    if blocking:
        subprocess.call(args, **kwargs)
    else:
        subprocess.Popen(args, **kwargs)
'''

NEW_SPEAK = '''# Guidance voice is the Bluetooth earbuds on this Pi (Nirvana Ion A2DP).
# Phone TTS is muted on these payloads so the wearer does not hear two voices.
GLASSES_SPEAKER_ENABLED = True
BT_SPEAKER_MAC = "90:A0:BE:CA:23:A9"
BT_APLAY_DEV = f"bluealsa:DEV={BT_SPEAKER_MAC},PROFILE=a2dp"


def _ensure_bt_speaker():
    try:
        listed = subprocess.check_output(
            ["bluealsa-cli", "list-pcms"],
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        )
        if BT_SPEAKER_MAC.replace(":", "_") in listed:
            return
    except Exception:
        pass
    try:
        subprocess.run(
            ["bluetoothctl", "connect", BT_SPEAKER_MAC],
            timeout=6,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception as error:
        print(f"[AUDIO] BT connect skipped: {error}")


def _espeak_voice_for(text):
    return "hi" if any("\u0900" <= ch <= "\u097F" for ch in text) else "en"


def _play_bt_speaker(text, blocking=False, volume=None):
    if not text or not GLASSES_SPEAKER_ENABLED:
        return

    def run():
        _ensure_bt_speaker()
        voice = _espeak_voice_for(text)
        args = ["espeak", "-s", "140", "-v", voice, "--stdout", text]
        if volume is not None:
            args[1:1] = ["-a", str(max(20, min(200, int(volume))))]
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.call(
                ["aplay", "-q", "-D", BT_APLAY_DEV],
                stdin=proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait()
        except Exception as error:
            print(f"[AUDIO] BT playback failed: {error}")

    if blocking:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


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
            "speak": False,
        })
    except Exception as error:
        print(f"[AUDIO] Could not hand speech to the phone: {error}")
    _play_bt_speaker(text, blocking=blocking, volume=volume)
'''

subs = [
    ("speak()", OLD_SPEAK, NEW_SPEAK),
    (
        "gemini speak",
        '''            "source": result.get("source"),
            "speak": True,
            "replaces_alert_id": alert_id,
        }
        publish_phone_alert(payload)
''',
        '''            "source": result.get("source"),
            "speak": False,
            "replaces_alert_id": alert_id,
        }
        publish_phone_alert(payload)
        speak(text_hi)
''',
    ),
    (
        "auto_describe speak",
        '''                        "source": result.get("source"),
                        "speak": True,
                    })
''',
        '''                        "source": result.get("source"),
                        "speak": False,
                    })
                    speak(text_hi)
''',
    ),
    (
        "obstacle snapshot",
        '''                        "source": "tof_snapshot",
                        # Phone TTS is primary while glasses speaker is unreliable.
                        "speak": speak_now,
                    })
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
''',
        '''                        "source": "tof_snapshot",
                        "speak": False,
                    })
                    if speak_now:
                        speak(quick_hi)
                    # Opening warning: two distinct buzzes, haptic only on glasses.
                    deliver_haptic_burst(side, pattern, HAPTIC_OPENING_BURST_COUNT)
''',
    ),
    (
        "describe http",
        '''                    "source": command,
                    # Companion already speaks the HTTP result; don't double-TTS.
                    "speak": False,
                })
''',
        '''                    "source": command,
                    "speak": False,
                })
                speak(result["text_hi"])
''',
    ),
]

for name, old, new in subs:
    if old not in text:
        raise SystemExit(f"MISSING {name}")
    text = text.replace(old, new, 1)
    print("patched", name)

PATH.write_text(text)
print("OK", PATH)
