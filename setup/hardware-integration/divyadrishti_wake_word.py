#!/usr/bin/env python3
"""Hindi wake-word ("Hey Divya Drishti") listener for Divya Drishti.

Purpose: an always-listening but fully on-device wake-word detector. Audio is
processed locally, frame by frame, and never leaves the device — nothing is
recorded to disk and nothing is streamed anywhere unless the wake word is
detected, at which point this script does exactly one thing: call the same
local API the phone's Describe button and the GPIO25 button use.

Separate from sensing and from the control button — does not own the camera,
ToF, motors, or speaker, and does not replace the button. Both triggers call
the identical local API, so either one works independently; keeping both is
intentional redundancy, not duplication (voice can fail in noise or with
accent drift, the button always works).

NOT YET DEPLOYED. This file only exists in the repo until explicitly told to
push it to the Pi. Never run divyadrishti-sensing.service actions, never
touch the camera/ToF/motors from this script.

Engine: Picovoice Porcupine (pvporcupine), a small on-device keyword-spotting
model — it only recognizes the trained phrase, it is not speech-to-text and
cannot transcribe arbitrary speech. Audio capture: Picovoice's own PvRecorder
library (pvrecorder), which pairs with Porcupine's expected sample rate/frame
length out of the box.

KNOWN OPEN RISK — read before deploying:
  This project's compute is a Raspberry Pi Zero W (single-core ARM1176JZF-S,
  ARMv6, no NEON) per divyadrishti-sensing-start.sh. There is an open
  Picovoice GitHub issue (Picovoice/porcupine#1414) where their ARM11/ARMv6
  build crashes with SIGILL because the shipped binary contains NEON
  instructions, and Picovoice's own reply says they no longer officially
  support that chip family (same family as the Pi 1B in that report). This
  script may simply fail to start on the real hardware. Verify with:
    python3 -c "import pvporcupine; pvporcupine.create(access_key='...', keywords=['porcupine'])"
  on the Pi itself, on a harmless built-in keyword, BEFORE relying on a
  custom model. If that crashes, this needs to move to the phone instead.

Setup required before this will run (none of this is done by this script):
  1. pip3 install pvporcupine pvrecorder
  2. Create a free account at https://console.picovoice.ai/ and get an
     AccessKey. Put it in /home/pi/.divyadrishti/porcupine.env as:
       PORCUPINE_ACCESS_KEY=your-key-here
     Never commit this key or paste it in chat/logs.
  3. Train a custom Hindi keyword ("Divya Drishti" or "Hey Divya Drishti" —
     test both, shorter phrases perform better) on Picovoice Console,
     platform "Raspberry Pi" (re-check against the KNOWN OPEN RISK above for
     the exact chip). Download the resulting .ppn file to
     /home/pi/.divyadrishti/wake_word/keyword.ppn
  4. Because Hindi is a non-English language, Porcupine also needs the Hindi
     acoustic model file (porcupine_params_hi.pv) from Picovoice's
     lang-model GitHub repo. Place it at
     /home/pi/.divyadrishti/wake_word/porcupine_params_hi.pv
  5. See DEPLOY_WAKE_WORD.md in this directory for the full deploy sequence.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_PATH = Path("/var/log/divyadrishti-wake-word.log")
ENV_FILE = Path("/home/pi/.divyadrishti/porcupine.env")
DEVICE_FILE = Path("/home/pi/.divyadrishti/device.json")
KEYWORD_PATH = Path(
    os.environ.get("PORCUPINE_KEYWORD_PATH", "/home/pi/.divyadrishti/wake_word/keyword.ppn")
)
HINDI_MODEL_PATH = Path(
    os.environ.get(
        "PORCUPINE_MODEL_PATH", "/home/pi/.divyadrishti/wake_word/porcupine_params_hi.pv"
    )
)
SENSITIVITY = float(os.environ.get("PORCUPINE_SENSITIVITY", "0.5"))

LOCAL_API_URL = "http://127.0.0.1:8765/v1/command"
LOCAL_API_TIMEOUT_S = 6.0

# Minimum gap between two accepted triggers. Prevents a single sustained
# utterance (or an echo) from firing multiple describe calls back to back.
# The Gemini-side describe pipeline has its own separate cooldown too; this
# is purely about not hammering the local HTTP endpoint.
RETRIGGER_COOLDOWN_S = 6.0

logger = logging.getLogger("divyadrishti-wake-word")

stop_event = threading.Event()
last_trigger_monotonic = 0.0
trigger_lock = threading.Lock()


def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:
        logger.warning("File log unavailable at %s: %s (journal only)", LOG_PATH, error)


def load_access_key() -> str:
    """Read PORCUPINE_ACCESS_KEY from env var first, then the env file. Never log the value."""
    env_key = os.environ.get("PORCUPINE_ACCESS_KEY", "").strip()
    if env_key:
        return env_key

    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "PORCUPINE_ACCESS_KEY":
                return value.strip().strip('"').strip("'")
    except (FileNotFoundError, OSError) as error:
        logger.error("Could not read %s: %s", ENV_FILE, error)
    return ""


def local_pairing_code() -> str:
    """Read the device pairing code the same way the button daemon and local-link API do."""
    try:
        return json.loads(DEVICE_FILE.read_text()).get("pairing_code", "").upper()
    except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
        logger.error("Could not load pairing code from %s: %s", DEVICE_FILE, error)
        return ""


def trigger_read_command() -> None:
    """Ask the sensing service to describe what's ahead — identical action to the phone's Describe button and the GPIO25 button's medium hold."""
    code = local_pairing_code()
    if not code:
        logger.error("Wake word detected, but no pairing code available — not calling local API")
        return

    request = urllib.request.Request(
        LOCAL_API_URL,
        data=json.dumps({"command": "read"}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Divya-Pairing-Code": code,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_API_TIMEOUT_S) as response:
            logger.info("Wake word trigger: local API responded %s", response.status)
    except urllib.error.URLError as error:
        logger.error("Wake word trigger: local API call failed (%s): %s", LOCAL_API_URL, error)


def on_wake_word_detected() -> None:
    global last_trigger_monotonic
    now = time.monotonic()
    with trigger_lock:
        since_last = now - last_trigger_monotonic
        if since_last < RETRIGGER_COOLDOWN_S:
            logger.info(
                "Wake word detected but ignored (%.1fs since last trigger, cooldown %.1fs)",
                since_last,
                RETRIGGER_COOLDOWN_S,
            )
            return
        last_trigger_monotonic = now

    logger.info("Wake word detected → calling local API read/describe")
    threading.Thread(target=trigger_read_command, daemon=True).start()


def request_stop(_signal_number: int, _frame: object) -> None:
    logger.info("Stopping wake-word daemon")
    stop_event.set()


def run() -> int:
    access_key = load_access_key()
    if not access_key:
        logger.error(
            "No PORCUPINE_ACCESS_KEY found (checked env var and %s). "
            "Get one free at https://console.picovoice.ai/ — refusing to start.",
            ENV_FILE,
        )
        return 1

    if not KEYWORD_PATH.exists():
        logger.error(
            "Keyword file missing at %s. Train a custom wake word at "
            "https://console.picovoice.ai/ and download the .ppn there.",
            KEYWORD_PATH,
        )
        return 1

    if not HINDI_MODEL_PATH.exists():
        logger.error(
            "Hindi acoustic model missing at %s (porcupine_params_hi.pv, needed for any "
            "non-English keyword — get it from the Porcupine GitHub repo's lib/common folder).",
            HINDI_MODEL_PATH,
        )
        return 1

    try:
        import pvporcupine
    except ImportError:
        logger.error("pvporcupine is not installed — run: pip3 install pvporcupine")
        return 1

    try:
        from pvrecorder import PvRecorder
    except ImportError:
        logger.error("pvrecorder is not installed — run: pip3 install pvrecorder")
        return 1

    try:
        porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(KEYWORD_PATH)],
            model_path=str(HINDI_MODEL_PATH),
            sensitivities=[SENSITIVITY],
        )
    except Exception as error:  # noqa: BLE001 - startup failure must be logged clearly, not crash silently
        logger.exception(
            "Porcupine failed to initialize (%s). If this is a SIGILL/illegal instruction, "
            "this Pi's CPU architecture is not compatible with the shipped Porcupine binary — "
            "see the KNOWN OPEN RISK note at the top of this file. Not retrying automatically.",
            error,
        )
        return 1

    recorder = PvRecorder(frame_length=porcupine.frame_length, device_index=-1)

    logger.info(
        "Listening for wake word (sample_rate=%d, frame_length=%d, sensitivity=%.2f, "
        "device=%s)",
        porcupine.sample_rate,
        porcupine.frame_length,
        SENSITIVITY,
        recorder.selected_device,
    )

    try:
        recorder.start()
        while not stop_event.is_set():
            pcm = recorder.read()
            keyword_index = porcupine.process(pcm)
            if keyword_index >= 0:
                on_wake_word_detected()
    except Exception:
        logger.exception("Wake-word listen loop crashed")
        return 1
    finally:
        try:
            recorder.stop()
            recorder.delete()
        except Exception:  # noqa: BLE001 - best-effort cleanup, don't mask the original error
            pass
        porcupine.delete()

    return 0


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    sys.exit(run())


if __name__ == "__main__":
    main()
