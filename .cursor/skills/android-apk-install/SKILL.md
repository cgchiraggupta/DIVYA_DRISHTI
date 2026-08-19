---
name: android-apk-install
description: >-
  Builds and installs the DeepGear TST / Divya Drishti Android debug APK
  on the USB test phone. Use when the user asks to install the app, put
  a new APK on the phone, adb install, android:install, or to try a UI
  change on device. Do not use for iOS, Play Store release, or native
  Capacitor plugin / gradle config changes (those need the slow path).
---

# Android APK install (JS/UI)

Test phone serial: `0015935A7000905` (`ADB_SERIAL` overrides).
Package: `com.divyadrishti.app` / `.MainActivity`.

## Do this (JS/UI only)

From repo root, after UI/JS is saved:

```bash
adb -s 0015935A7000905 get-state
# must print: device

# 1. New lucide-react icons MUST be exported in src/lib/lucide.js first.
#    The app aliases lucide-react → that barrel. Missing export = 3 min
#    Vite fail (MISSING_EXPORT), not a runtime blank icon.

# 2. Vite — never `npx vite build` from a Cursor agent shell.
#    That hangs at 0% CPU with no logs. Direct binary + CI=1 works.
CI=1 node ./node_modules/vite/bin/vite.js build --logLevel info

# 3. Skip `cap sync`. rsync web assets only.
mkdir -p android/app/src/main/assets/public
rsync -a --delete dist/ android/app/src/main/assets/public/

# 4. Incremental Gradle. Never clean / --stop unless dex is broken.
cd android && ./gradlew assembleDebug -q

# 5. Replace install + launch
adb -s 0015935A7000905 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s 0015935A7000905 shell am start -n com.divyadrishti.app/.MainActivity
```

Same sequence: `npm run android:install` (script uses the non-hanging Vite path). Then launch MainActivity.

**Expect:** Vite ~2–5 min in a Cursor sandbox, Gradle ~1 min when warm, adb a few seconds. If Vite has no log after ~90s and 0% CPU, kill it and rerun the `CI=1 node ./node_modules/vite/bin/vite.js` line — do not wait 10 minutes.

## Do not

- `npx vite build` / `npx cap sync` in an agent terminal
- `gradlew clean` or `gradlew --stop` for a normal UI install
- `npm run android:build` unless native Android, plugins, or `capacitor.config` changed
- Add a lucide icon in a page without exporting it from `src/lib/lucide.js`

## Slow path (native / Capacitor)

```bash
npm run android:build
adb -s 0015935A7000905 install -r android/app/build/outputs/apk/debug/app-debug.apk
```

Gradle dex / NoSuchFile:

```bash
cd android && ./gradlew --stop
rm -rf app/build build
./gradlew assembleDebug
```

Then go back to the fast path.

## JDK

`android/gradlew` is pinned to `/opt/homebrew/opt/openjdk@21`.
