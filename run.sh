#!/usr/bin/env bash
#
# Builds the debug APK, installs it, and launches the Sorghum capture app.
#
# Uses a connected device if one is attached; otherwise boots an emulator.
#
# Usage:
#   ./run.sh                # use connected device, or boot the default AVD
#   ./run.sh MyAvdName      # boot a specific AVD when no device is connected
#
# Environment:
#   ANDROID_HOME  Android SDK location (default: ~/Library/Android/sdk)

set -euo pipefail

readonly APP_ID="com.sorghum.capture"
readonly MAIN_ACTIVITY="${APP_ID}/.MainActivity"
readonly DEFAULT_AVD="SorghumTest"
readonly BOOT_TIMEOUT_SECONDS=180

ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ADB="$ANDROID_HOME/platform-tools/adb"
EMULATOR="$ANDROID_HOME/emulator/emulator"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
avd_name="${1:-$DEFAULT_AVD}"

fail() {
  echo "error: $*" >&2
  exit 1
}

has_ready_device() {
  "$ADB" devices | awk 'NR > 1 && $2 == "device"' | grep -q .
}

boot_emulator() {
  "$EMULATOR" -list-avds | grep -qx "$avd_name" \
    || fail "AVD '$avd_name' not found. Available: $("$EMULATOR" -list-avds | tr '\n' ' ')"

  echo "No device connected. Booting emulator '$avd_name'..."
  # Detached so the emulator keeps running after this script exits.
  nohup "$EMULATOR" -avd "$avd_name" >/dev/null 2>&1 &

  "$ADB" wait-for-device
  local waited=0
  # wait-for-device returns before Android finishes booting; installs fail until boot completes.
  until [[ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
    (( waited >= BOOT_TIMEOUT_SECONDS )) && fail "emulator did not boot within ${BOOT_TIMEOUT_SECONDS}s"
    sleep 2
    waited=$(( waited + 2 ))
  done
  echo "Emulator booted."
}

[[ -x "$ADB" ]] || fail "adb not found at $ADB (set ANDROID_HOME)"
[[ -x "$EMULATOR" ]] || fail "emulator not found at $EMULATOR (set ANDROID_HOME)"

has_ready_device || boot_emulator

echo "Building and installing debug APK..."
"$PROJECT_DIR/gradlew" -p "$PROJECT_DIR" installDebug

# Pre-grant camera so the app opens straight to the preview instead of the permission prompt.
"$ADB" shell pm grant "$APP_ID" android.permission.CAMERA || echo "warning: could not pre-grant CAMERA permission"

echo "Launching $MAIN_ACTIVITY..."
"$ADB" shell am start -n "$MAIN_ACTIVITY"
