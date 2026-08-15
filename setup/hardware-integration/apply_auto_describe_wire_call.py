#!/usr/bin/env python3
"""Patch divya_drishti_final.py: actually CALL maybe_auto_describe() from the
detection loop.

Root cause found 2026-08-15: an earlier patch (apply_auto_scene_describe.py)
added the maybe_auto_describe() function, the scene-diff helpers, and the
worker thread — but never actually inserted the call site into
detection_loop(). The function has been fully defined and completely dead
code ever since: `grep -n "maybe_auto_describe(" divya_drishti_final.py`
matched only the `def` line, zero call sites. This is why auto-describe
never fired even once, regardless of standing still, scene changes, or
obstacle state — none of that logic was ever reachable.

This adds the single missing call, once per detection_loop tick, right after
the existing should_alert / haptic_reminder / clear-reading branches finish
(so obstacle_active reflects this tick's final state) and using the same
`frame` already captured for CV this tick.

Usage (on the Pi):
    python3 apply_auto_describe_wire_call.py /home/pi/divya_drishti_final.py
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD = """                        with state_lock:
                            state["last_alert_side"] = None
                            state["last_alert_zone"] = None


        except Exception as e:
            print(f"[DETECT] Error: {e}")

        time.sleep(0.3)"""

NEW = """                        with state_lock:
                            state["last_alert_side"] = None
                            state["last_alert_zone"] = None

            maybe_auto_describe(frame, obstacle_active)

        except Exception as e:
            print(f"[DETECT] Error: {e}")

        time.sleep(0.3)"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_auto_describe_wire_call.py <path-to-divya_drishti_final.py>")
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    # Careful: "maybe_auto_describe(frame, obstacle_active)" is a substring
    # of the `def maybe_auto_describe(frame, obstacle_active):` line itself,
    # so a naive text.count() over-reports by 1 for the definition. Only the
    # indented call form (as inserted by NEW below) counts as "wired".
    if "\n            maybe_auto_describe(frame, obstacle_active)\n" in text:
        print("Already wired (real call site found). No changes made.")
        return 0

    if OLD not in text:
        print("ERROR: anchor not found — file may have changed. Aborting, no changes written.")
        return 1

    text = text.replace(OLD, NEW, 1)
    path.write_text(text, encoding="utf-8")
    print(f"Patched {path} — added the missing maybe_auto_describe() call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
