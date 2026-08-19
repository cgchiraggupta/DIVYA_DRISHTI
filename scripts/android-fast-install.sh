#!/usr/bin/env bash
# Fast phone install for JS/UI changes only.
# Skips: gradle clean, daemon stop, full Capacitor native sync.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHONE_SERIAL="${ADB_SERIAL:-0015935A7000905}"
APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
PUBLIC="$ROOT/android/app/src/main/assets/public"
VITE_BIN="$ROOT/node_modules/vite/bin/vite.js"

cd "$ROOT"

if ! adb -s "$PHONE_SERIAL" get-state >/dev/null 2>&1; then
  echo "Phone $PHONE_SERIAL not connected. Plug it in (USB debugging on)."
  adb devices -l
  exit 1
fi

echo "==> lucide barrel check"
python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
barrel = (root / "src/lib/lucide.js").read_text()
exported = set(re.findall(r"export \{ default as (\w+)", barrel))
missing = []
for path in (root / "src").rglob("*.jsx"):
    text = path.read_text()
    for block in re.findall(r"import\s+\{([^}]+)\}\s+from\s+['\"]lucide-react['\"]", text):
        for part in block.split(","):
            part = part.strip()
            if not part:
                continue
            name = part.split(" as ")[0].strip()
            if name not in exported:
                missing.append(f"{path.relative_to(root)}: {name}")
if missing:
    print("Add these to src/lib/lucide.js before building:")
    print("\n".join(f"  {m}" for m in missing))
    sys.exit(1)
print("lucide barrel OK")
PY

echo "==> vite build (direct binary; npx vite hangs in Cursor agent shells)"
CI=1 node "$VITE_BIN" build --logLevel info

echo "==> sync web assets into Android (rsync, no full cap sync)"
mkdir -p "$PUBLIC"
rsync -a --delete "$ROOT/dist/" "$PUBLIC/"

echo "==> gradle assembleDebug (incremental)"
cd "$ROOT/android"
./gradlew assembleDebug -q

echo "==> adb install -r"
adb -s "$PHONE_SERIAL" install -r "$APK"
adb -s "$PHONE_SERIAL" shell am start -n com.divyadrishti.app/.MainActivity

echo "OK — installed and launched on $PHONE_SERIAL"
