#!/bin/bash
# SPDX-License-Identifier: MIT
# omamobile-keys' volume keys: a photo while the Camera app (omacam) is in
# front of an unlocked phone, once per press; the volume otherwise. The power
# key: lock dark, wake lit with the brightness back. Stand-ins for hyprctl,
# omacam, omarchy-shell, omarchy-audio-output-volume and the brightness and
# lock commands record what was called.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
mkdir -p "$t/bin" "$t/run"
log=$t/calls
cat >"$t/bin/hyprctl" <<STUB
#!/bin/bash
if [[ \$1 == monitors ]]; then
  printf '[{"dpmsStatus": %s}]\n' "\$(cat "$t/dpms")"
else
  printf '{"class": "%s"}\n' "\$(cat "$t/class")"
fi
STUB
cat >"$t/bin/omacam" <<STUB
#!/bin/bash
echo "omacam \$*" >>"$log"
STUB
cat >"$t/bin/omarchy-audio-output-volume" <<STUB
#!/bin/bash
echo "volume \$*" >>"$log"
STUB
cat >"$t/bin/omarchy-shell" <<STUB
#!/bin/bash
case "\$*" in
  "lock wake") echo "lock wake" >>"$log"; exit "\$(cat "$t/wakerc")" ;;
  *) cat "$t/locked" ;;
esac
STUB
cat >"$t/bin/omarchy-hw-display" <<STUB
#!/bin/bash
echo panel
STUB
cat >"$t/bin/brightnessctl" <<STUB
#!/bin/bash
[[ \$1 == -q ]] && shift
case "\$3" in
  get) cat "$t/level" ;;
  set) echo "\$4" >"$t/level"; echo "brightness \$4" >>"$log" ;;
esac
STUB
cat >"$t/bin/omarchy-brightness-display" <<STUB
#!/bin/bash
echo "display \$1" >>"$log"
STUB
cat >"$t/bin/omarchy-system-lock" <<STUB
#!/bin/bash
echo lock >>"$log"; echo true >"$t/locked"
STUB
chmod +x "$t"/bin/*
export PATH="$t/bin:$PATH" XDG_RUNTIME_DIR="$t/run"
keys() { bash "$here/bin/omamobile-keys" "$@"; }
fail() { printf 'not ok - %s\n' "$1" >&2; cat "$log" >&2 2>/dev/null; exit 1; }
reset() { : >"$log"; rm -rf "$t/run/omamobile-keys"; }

echo foot >"$t/class"; echo false >"$t/locked"; echo true >"$t/dpms"; echo 0 >"$t/wakerc"
reset; keys volume-up; [[ $(cat "$log") == "volume raise" ]] || fail "volume up raises the volume"
reset; keys volume-down; sleep 0.4; [[ $(cat "$log") == "volume lower" ]] || fail "volume down lowers the volume"

echo omacam >"$t/class"
reset; keys volume-up; [[ $(cat "$log") == "omacam --remote shutter" ]] || fail "volume up takes a photo in the camera"
reset; keys volume-down; sleep 0.4; [[ $(cat "$log") == "omacam --remote shutter" ]] || fail "volume down takes a photo in the camera"
reset; keys volume-up; keys volume-up; keys volume-up
[[ $(grep -c shutter "$log") == 1 ]] || fail "a held key takes one photo"

echo true >"$t/locked"
reset; keys volume-up; [[ $(cat "$log") == "volume raise" ]] || fail "a locked phone changes the volume, never takes a photo"
echo "ok - volume keys: camera shutter in front, volume otherwise"

# Power, short, unlocked: dark at once, lock, panel off, brightness back
echo foot >"$t/class"; echo false >"$t/locked"; echo 120 >"$t/level"
reset; keys power-down; keys power-up
[[ $(cat "$log" | tr '\n' ' ') == "brightness 0 lock display off brightness 120 " ]] || fail "power locks dark and puts the brightness back"
[[ -e $t/run/omamobile-keys/level || -e $t/run/omamobile-keys/power ]] && fail "a finished lock leaves no level or held marker"

# Power, short, locked with the display off: lit even when the lock's wake
# fails, and a brightness left at 0 comes back
echo true >"$t/locked"; echo false >"$t/dpms"; echo 1 >"$t/wakerc"; echo 0 >"$t/level"
reset; mkdir -p "$t/run/omamobile-keys"; echo 120 >"$t/run/omamobile-keys/level"
keys power-down; keys power-up
[[ $(cat "$log" | tr '\n' ' ') == "lock wake display on brightness 120 " ]] || fail "power wakes the locked display with its brightness"

# Power, short, locked with the display on: off
echo true >"$t/dpms"; echo 0 >"$t/wakerc"
reset; keys power-down; keys power-up
[[ $(cat "$log") == "display off" ]] || fail "power turns a lit locked display off"
echo "ok - power key: locks dark, wakes lit with the brightness back"
