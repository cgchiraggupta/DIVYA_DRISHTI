#!/usr/bin/env python3
"""GPIO25 main control button for Divya Drishti.

Wiring: GPIO25 (physical pin 22) to GND (physical pin 6). Internal pull-up only.
Never drive GPIO25 toward 3.3V/5V. Separate from sensing — does not own camera,
ToF, motors, or speaker.

Actions (on release):
  one short tap (< 1.5s)     → wait DOUBLE_TAP_WINDOW_S; if no second tap,
                                systemctl start divyadrishti-sensing.service
  two short taps (double-tap) → "read/describe what's ahead" via the sensing
                                service's local API (same as the phone Describe
                                button). A single tap never describes.
  1.5s <= held < 3s           → dead zone (no-op, logged) — safety buffer so a
                                slightly-long tap cannot power off
  3s <= held <= 7s            → systemctl poweroff
  7s < held < 8s              → dead zone (no-op, logged)
  held >= 8s                  → systemctl reboot

The read/describe trigger is a plain HTTP POST to the already-running sensing
service's local API (127.0.0.1:8765/v1/command), the same endpoint the phone
app calls. This script does not touch the camera, ToF, motors, or speaker
itself — it only asks the sensing service to do what it already knows how to
do. Requires: (1) divyadrishti-sensing.service is running with a local API that
accepts {"command": "read"} — see apply_read_near_obstacle.py /
apply_nearby_settings.py; (2) a pairing code exists at
/home/pi/.divyadrishti/device.json (this daemon runs as root, so it reads that
path explicitly rather than via $HOME).

Deploy (when Pi is reachable; do not run from this machine blindly):
  scp setup/hardware-integration/divyadrishti_control_button.py \\
      pi@divyadrishti.local:/home/pi/
  scp setup/hardware-integration/divyadrishti-control-button.service \\
      pi@divyadrishti.local:/tmp/
  ssh pi@divyadrishti.local 'sudo mv /tmp/divyadrishti-control-button.service \\
      /etc/systemd/system/ && sudo systemctl daemon-reload && \\
      sudo systemctl enable --now divyadrishti-control-button.service'
  See also: DEPLOY_BUTTON.md in this directory.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

GPIO_PIN = 25
BOUNCE_TIME_S = 0.05
TAP_MAX_SECONDS = 1.5
SHUTDOWN_MIN_SECONDS = 3.0
SHUTDOWN_MAX_SECONDS = 7.0
REBOOT_MIN_SECONDS = 8.0
# Second tap must arrive within this window after the first tap's release.
# 0.50s was too tight on the real glasses button (two natural taps landed
# ~0.70s apart and were logged as two single taps). 1.0s still will not
# confuse a later unrelated tap with a double-tap.
DOUBLE_TAP_WINDOW_S = 1.00
# Ignore a second "tap" closer than this — cheap-button bounce, not a person.
MIN_DOUBLE_TAP_GAP_S = 0.12
LOG_PATH = Path("/var/log/divyadrishti-control-button.log")
SENSING_UNIT = "divyadrishti-sensing.service"

# Hands-free "read/describe what's ahead" trigger — calls the sensing
# service's own local API, the same one the phone app's Describe button uses.
LOCAL_API_URL = "http://127.0.0.1:8765/v1/command"
LOCAL_API_TIMEOUT_S = 25.0
DEVICE_FILE = Path("/home/pi/.divyadrishti/device.json")

logger = logging.getLogger("divyadrishti-control-button")

press_time: float | None = None
press_lock = threading.Lock()
stop_event = threading.Event()

pending_tap_timer: threading.Timer | None = None
pending_tap_released_at: float | None = None
pending_lock = threading.Lock()


def setup_logging() -> None:
    """Log decisions to stdout (journal) and optionally a dedicated file."""
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=512_000,
            backupCount=3,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:
        logger.warning("File log unavailable at %s: %s (journal only)", LOG_PATH, error)


def local_pairing_code() -> str:
    """Read the device pairing code the same way the local-link/status API does."""
    try:
        return json.loads(DEVICE_FILE.read_text()).get("pairing_code", "").upper()
    except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
        logger.error("Read trigger: could not load pairing code from %s: %s", DEVICE_FILE, error)
        return ""


def cancel_pending_tap() -> None:
    """Drop a waiting single-tap so it cannot fire start-sensing later."""
    global pending_tap_timer, pending_tap_released_at
    with pending_lock:
        if pending_tap_timer is not None:
            pending_tap_timer.cancel()
            pending_tap_timer = None
        pending_tap_released_at = None


def fire_start_sensing() -> None:
    global pending_tap_timer, pending_tap_released_at
    with pending_lock:
        pending_tap_timer = None
        pending_tap_released_at = None
    logger.info(
        "Decision: SINGLE TAP → start %s (never stop/restart)",
        SENSING_UNIT,
    )
    run_systemctl("start", SENSING_UNIT)


def fire_describe() -> None:
    logger.info("Decision: DOUBLE TAP → local API /v1/command read")
    threading.Thread(target=trigger_read_command, daemon=True).start()


def handle_short_tap() -> None:
    """One tap starts sensing after a short wait; two taps in the window describe."""
    global pending_tap_timer, pending_tap_released_at
    now = time.monotonic()
    with pending_lock:
        first_released_at = pending_tap_released_at
        waiting = pending_tap_timer is not None
        if waiting and first_released_at is not None:
            gap = now - first_released_at
            if gap < MIN_DOUBLE_TAP_GAP_S:
                logger.info(
                    "Ignoring extra tap %.3fs after the first (bounce, need >= %.2fs)",
                    gap,
                    MIN_DOUBLE_TAP_GAP_S,
                )
                return
            pending_tap_timer.cancel()
            pending_tap_timer = None
            pending_tap_released_at = None
            is_double = True
        else:
            pending_tap_released_at = now
            pending_tap_timer = threading.Timer(DOUBLE_TAP_WINDOW_S, fire_start_sensing)
            pending_tap_timer.daemon = True
            pending_tap_timer.start()
            is_double = False

    if is_double:
        fire_describe()
    else:
        logger.info(
            "Tap noted; waiting %.2fs for a second tap before starting sensing",
            DOUBLE_TAP_WINDOW_S,
        )


def trigger_read_command() -> None:
    """Ask the sensing service to describe what's ahead — identical to the phone's Describe button."""
    code = local_pairing_code()
    if not code:
        logger.error("Read trigger: no pairing code available, not calling local API")
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
            body = response.read().decode("utf-8", errors="ignore")
            status = ""
            try:
                status = json.loads(body).get("status", "")
            except json.JSONDecodeError:
                pass
            logger.info(
                "Read trigger: local API responded %s status=%s",
                response.status,
                status or "unknown",
            )
            if status in ("busy", "cooldown"):
                logger.warning(
                    "Read trigger: describe not spoken (%s) — Gemini slot was busy or on cooldown",
                    status,
                )
    except urllib.error.URLError as error:
        logger.error("Read trigger: local API call failed (%s): %s", LOCAL_API_URL, error)


def run_systemctl(*args: str) -> None:
    """Run systemctl directly; this service runs as root."""
    command = ["systemctl", *args]
    logger.info("Running: %s", " ".join(command))
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        logger.exception(
            "Command failed with exit code %s: %s",
            error.returncode,
            " ".join(command),
        )


def on_pressed() -> None:
    global press_time
    with press_lock:
        press_time = time.monotonic()
    logger.info("Button pressed on GPIO%d", GPIO_PIN)


def on_released() -> None:
    global press_time
    with press_lock:
        started_at = press_time
        press_time = None

    if started_at is None:
        logger.warning("Ignoring release with no recorded press")
        return

    held_seconds = time.monotonic() - started_at
    logger.info("Button released after %.2f seconds", held_seconds)

    if held_seconds < TAP_MAX_SECONDS:
        handle_short_tap()
    elif SHUTDOWN_MIN_SECONDS <= held_seconds <= SHUTDOWN_MAX_SECONDS:
        cancel_pending_tap()
        logger.warning(
            "Decision: SHUTDOWN (%.1fs–%.1fs hold, got %.2fs) → systemctl poweroff",
            SHUTDOWN_MIN_SECONDS,
            SHUTDOWN_MAX_SECONDS,
            held_seconds,
        )
        run_systemctl("poweroff")
    elif held_seconds >= REBOOT_MIN_SECONDS:
        cancel_pending_tap()
        logger.warning(
            "Decision: REBOOT (%.1fs+ hold, got %.2fs) → systemctl reboot",
            REBOOT_MIN_SECONDS,
            held_seconds,
        )
        run_systemctl("reboot")
    else:
        cancel_pending_tap()
        logger.info(
            "Decision: NO-OP dead zone (%.2fs); bands are <%.1fs tap "
            "(double-tap = describe), %.1f–%.1fs shutdown, %.1fs+ reboot",
            held_seconds,
            TAP_MAX_SECONDS,
            SHUTDOWN_MIN_SECONDS,
            SHUTDOWN_MAX_SECONDS,
            REBOOT_MIN_SECONDS,
        )


def request_stop(_signal_number: int, _frame: object) -> None:
    logger.info("Stopping control-button daemon")
    cancel_pending_tap()
    stop_event.set()


def run_with_gpiozero() -> None:
    from gpiozero import Button

    button = Button(GPIO_PIN, pull_up=True, bounce_time=BOUNCE_TIME_S)
    button.when_pressed = on_pressed
    button.when_released = on_released
    logger.info(
        "Watching GPIO%d via gpiozero (pull-up, %.0f ms debounce, interrupt-driven)",
        GPIO_PIN,
        BOUNCE_TIME_S * 1000,
    )
    try:
        stop_event.wait()
    finally:
        button.close()


def run_with_lgpio() -> None:
    """Fallback when gpiozero is not installed: edge-wait on GPIO25 with pull-up."""
    import lgpio

    chip = lgpio.gpiochip_open(0)
    # Flags: pull-up input. Debounce approximated by ignoring edges within bounce window.
    lgpio.gpio_claim_input(chip, GPIO_PIN, lgpio.SET_PULL_UP)
    logger.info(
        "Watching GPIO%d via lgpio fallback (pull-up, ~%.0f ms software debounce)",
        GPIO_PIN,
        BOUNCE_TIME_S * 1000,
    )

    last_edge_monotonic = 0.0
    pressed = False

    try:
        while not stop_event.is_set():
            # Level: 1 = released (pull-up), 0 = pressed (to GND)
            level = lgpio.gpio_read(chip, GPIO_PIN)
            now = time.monotonic()
            if now - last_edge_monotonic < BOUNCE_TIME_S:
                stop_event.wait(0.01)
                continue

            if level == 0 and not pressed:
                last_edge_monotonic = now
                pressed = True
                on_pressed()
            elif level == 1 and pressed:
                last_edge_monotonic = now
                pressed = False
                on_released()

            # Short wait keeps CPU low without busy-spin; prefer interrupt path via gpiozero.
            stop_event.wait(0.02)
    finally:
        lgpio.gpio_free(chip, GPIO_PIN)
        lgpio.gpiochip_close(chip)


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        import gpiozero  # noqa: F401
    except ImportError:
        logger.warning("gpiozero not available; falling back to lgpio")
        try:
            run_with_lgpio()
        except ImportError:
            logger.error("Neither gpiozero nor lgpio is available; exiting")
            sys.exit(1)
        return

    run_with_gpiozero()


if __name__ == "__main__":
    main()
