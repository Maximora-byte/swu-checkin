#!/usr/bin/env bash
# Disposable GitHub runner only; no school account, no system security changes.
set -euo pipefail
api="${1:?Android API required}"
case "$api" in
  24) image="system-images;android-24;default;x86_64" ;;
  35) image="system-images;android-35;google_apis;x86_64" ;;
  *) echo 'Unsupported feasibility API' >&2; exit 1 ;;
esac
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --install "$image" emulator platform-tools </dev/null
printf 'no\n' | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd -n swu-feasibility --force -k "$image"
accel=off
if [[ -r /dev/kvm && -w /dev/kvm ]]; then accel=on; fi
mkdir -p android/evidence
printf 'api=%s\nabi=x86_64\nacceleration=%s\n' "$api" "$accel" > android/evidence/emulator.txt
"$ANDROID_HOME/emulator/emulator" -avd swu-feasibility -no-window -no-audio \
  -no-boot-anim -no-snapshot -gpu swiftshader_indirect -accel "$accel" \
  > android/evidence/emulator.log 2>&1 &
emulator_pid=$!
trap 'adb emu kill >/dev/null 2>&1 || true; kill "$emulator_pid" 2>/dev/null || true' EXIT
ready=false
for _ in $(seq 1 180); do
  if [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; then
    ready=true
    break
  fi
  kill -0 "$emulator_pid" 2>/dev/null || { tail -60 android/evidence/emulator.log; exit 1; }
  sleep 5
done
[[ "$ready" == true ]] || { echo 'Emulator boot timed out'; exit 1; }
adb shell input keyevent 82
adb shell getprop ro.build.version.sdk >> android/evidence/emulator.txt
adb shell getprop ro.product.cpu.abi >> android/evidence/emulator.txt
adb shell getconf PAGE_SIZE >> android/evidence/emulator.txt
(cd android && ./gradlew --no-daemon :app:connectedDebugAndroidTest)
