#!/usr/bin/env bash
# Disposable GitHub-hosted runner only; no school account or persistent host changes.
set -euo pipefail
api="${1:?Android API required}"
page_size="${2:-4096}"
# Recent cmdline-tools and emulator releases disagree on defaults: explicitly
# give both tools the same disposable AVD root.
export ANDROID_USER_HOME="${RUNNER_TEMP:?GitHub runner required}/swu-android-user"
export ANDROID_EMULATOR_HOME="$ANDROID_USER_HOME"
export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
mkdir -p "$ANDROID_AVD_HOME"
case "$api:$page_size" in
  24:4096) image="system-images;android-24;default;x86_64" ;;
  35:4096) image="system-images;android-35;google_apis;x86_64" ;;
  35:16384) image="system-images;android-35;google_apis_ps16k;x86_64" ;;
  *) echo 'Unsupported feasibility API' >&2; exit 1 ;;
esac
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --install "$image" emulator platform-tools </dev/null
printf 'no\n' | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd -n swu-feasibility --force -k "$image" -p "$ANDROID_AVD_HOME/swu-feasibility.avd"
# Recent x86_64 Android guests are unreliable under pure software emulation.
# Grant only this already-administrative test user access inside the disposable
# GitHub VM. Refuse self-hosted machines and never use world-writable modes.
[[ "${RUNNER_ENVIRONMENT:-}" == github-hosted ]]
[[ -c /dev/kvm && ! -L /dev/kvm ]]
sudo chown "$(id -u):$(id -g)" /dev/kvm
sudo chmod 0600 /dev/kvm
[[ -r /dev/kvm && -w /dev/kvm ]]
accel=on
mkdir -p android/evidence
printf 'api=%s\nabi=x86_64\nacceleration=%s\nexpected_page_size=%s\n' \
  "$api" "$accel" "$page_size" > android/evidence/emulator.txt
stat -c 'kvm_mode=%a kvm_uid=%u kvm_gid=%g' /dev/kvm >> android/evidence/emulator.txt
"$ANDROID_HOME/emulator/emulator" -avd swu-feasibility -no-window -no-audio \
  -no-boot-anim -no-snapshot -no-metrics -gpu swiftshader_indirect -accel "$accel" \
  > android/evidence/emulator.log 2>&1 &
emulator_pid=$!
cleanup() {
  # Disposable emulator only, with no credentials or school responses. Preserve
  # startup/crash evidence even if instrumentation never reaches the first test.
  adb logcat -d -b crash > android/evidence/android-crash.log 2>&1 || true
  adb logcat -d -b all -v threadtime > android/evidence/system-logcat.txt 2>&1 || true
  adb logcat -d -s AndroidRuntime:E python.stderr:E > android/evidence/runtime-errors.log 2>&1 || true
  adb emu kill >/dev/null 2>&1 || true
  kill "$emulator_pid" 2>/dev/null || true
}
trap cleanup EXIT
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
# Android 7's shell has no getconf. This is metadata, not a pass/fail check.
if ! adb shell getconf PAGE_SIZE >> android/evidence/emulator.txt 2>/dev/null; then
  adb shell cat /proc/self/smaps 2>/dev/null \
    | awk '!found && /KernelPageSize:/ {print $2 * 1024; found=1} END {if (!found) exit 1}' \
    >> android/evidence/emulator.txt || echo 'page_size=not_reported' >> android/evidence/emulator.txt
fi
if [[ "$api" == 35 ]]; then
  actual_page_size="$(adb shell getconf PAGE_SIZE | tr -d '\r')"
  [[ "$actual_page_size" == "$page_size" ]] || { echo 'Device page size does not match test matrix'; exit 1; }
fi
# These exact APKs were downloaded from the package job, not rebuilt here.
[[ "$(git rev-parse HEAD)" == "$(cat android/evidence/commit.txt)" ]]
(cd android && sha256sum -c evidence/SHA256SUMS)
apk=android/app/build/outputs/apk/debug/app-debug.apk
tests=android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
app_id=io.github.maximorabyte.swucheckin.feasibility
adb install "$apk"
adb install "$tests"
run_tests() {
  adb shell am instrument -w -r "$app_id.test/androidx.test.runner.AndroidJUnitRunner" \
    | tee "android/evidence/instrumentation-$1.txt"
  python3 scripts/android/verify_instrumentation.py "android/evidence/instrumentation-$1.txt"
}
run_tests fresh-install
# Same-version replacement exercises preservation of app-private data; it is
# not a claim of a production-version migration test.
adb install -r "$apk"
run_tests replacement-install
adb shell pm clear "$app_id"
run_tests cleared-data
adb shell am start -n "$app_id/io.github.maximorabyte.swucheckin.MainActivity"
# A fixed delay can capture only the Android splash screen. Require the actual
# app title and both enabled controls before collecting the UI screenshot.
ui_ready=false
for _ in $(seq 1 30); do
  if adb shell uiautomator dump /data/local/tmp/swu-feasibility-ui.xml \
      > android/evidence/ui-dump.log 2>&1 && \
    adb pull /data/local/tmp/swu-feasibility-ui.xml android/evidence/feasibility-ui.xml \
      >> android/evidence/ui-dump.log 2>&1 && \
    python3 scripts/android/verify_ui.py android/evidence/feasibility-ui.xml; then
    ui_ready=true
    break
  fi
  sleep 2
done
[[ "$ui_ready" == true ]] || { echo 'Feasibility UI readiness timed out'; exit 1; }
adb exec-out screencap -p > android/evidence/feasibility-screen.png
