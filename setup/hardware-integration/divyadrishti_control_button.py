#!/usr/bin/env python3
"""GPIO25 main control button for Divya Drishti.

Wiring: GPIO25 (physical pin 22) to GND (physical pin 6). Internal pull-up only.
Never drive GPIO25 toward 3.3V/5V. Separate from sensing — does not own camera,
ToF, motors, or speaker.

Actions (on release):
  held < 1.5s          → systemctl start divyadrishti-sensing.service
  1.5s <= held < 3s    → dead zone (no-op, logged)
  3s <= held <= 7s     → systemctl poweroff
  7s < held < 8s       → dead zone (no-op, logged)
  held >= 8s           → systemctl reboot

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

import logging
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

GPIO_PIN = 25
BOUNCE_TIME_S = 0.05
TAP_MAX_SECONDS = 1.5
SHUTDOWN_MIN_SECONDS = 3.0
SHUTDOWN_MAX_SECONDS = 7.0
REBOOT_MIN_SECONDS = 8.0
LOG_PATH = Path("/var/log/divyadrishti-control-button.log")
SENSING_UNIT = "divyadrishti-sensing.service"

logger = logging.getLogger("divyadrishti-control-button")

press_time: float | None = None
press_lock = threading.Lock()
stop_event = threading.Event()


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
        logger.info(
            "Decision: TAP (%.2fs < %.1fs) → start %s (never stop/restart)",
            held_seconds,
            TAP_MAX_SECONDS,
            SENSING_UNIT,
        )
        run_systemctl("start", SENSING_UNIT)
    elif SHUTDOWN_MIN_SECONDS <= held_seconds <= SHUTDOWN_MAX_SECONDS:
        logger.warning(
            "Decision: SHUTDOWN (%.1fs–%.1fs hold, got %.2fs) → systemctl poweroff",
            SHUTDOWN_MIN_SECONDS,
            SHUTDOWN_MAX_SECONDS,
            held_seconds,
        )
        run_systemctl("poweroff")
    elif held_seconds >= REBOOT_MIN_SECONDS:
        logger.warning(
            "Decision: REBOOT (%.1fs+ hold, got %.2fs) → systemctl reboot",
            REBOOT_MIN_SECONDS,
            held_seconds,
        )
        run_systemctl("reboot")
    else:
        logger.info(
            "Decision: NO-OP dead zone (%.2fs); bands are <%.1fs tap, "
            "%.1f–%.1fs shutdown, %.1fs+ reboot",
            held_seconds,
            TAP_MAX_SECONDS,
            SHUTDOWN_MIN_SECONDS,
            SHUTDOWN_MAX_SECONDS,
            REBOOT_MIN_SECONDS,
        )


def request_stop(_signal_number: int, _frame: object) -> None:
    logger.info("Stopping control-button daemon")
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
