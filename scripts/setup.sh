#!/usr/bin/env bash
# Reproduce the verified Leap + Hyperion Python environment.
# See docs/context/environment.md for why each step exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="${LEAPSDK_INSTALL_LOCATION:-/Applications/Ultraleap Hand Tracking.app/Contents/LeapSDK}"
VENDOR="$ROOT/vendor/LeapMotion-Python-Hyperion"
VENV="$ROOT/.venv"

[ -d "$SDK" ] || { echo "FAIL: no LeapSDK at $SDK — install Ultraleap Hyperion 6.2+"; exit 1; }

# The bundled CFFI module is built for CPython 3.12 only. This pin is not negotiable
# unless you rebuild leapc-cffi from source.
if [ ! -d "$VENV" ]; then
  uv venv --python 3.12 "$VENV"
fi

# Hyperion ships libLeapC.6; the official ultraleap/leapc-python-bindings expects .5.
# This fork is the Hyperion-updated one.
if [ ! -d "$VENDOR" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --depth 1 https://github.com/DDlabAU/LeapMotion-Python-Hyperion.git "$VENDOR"
fi

export VIRTUAL_ENV="$VENV"
# cffi is required but not declared by the bindings package.
uv pip install -q cffi pyobjc-framework-Quartz pyobjc-framework-Cocoa \
                  pyobjc-framework-ApplicationServices
uv pip install -q -e "$VENDOR/leapc-python-api"

# Use the SDK's prebuilt CFFI extension rather than compiling our own.
SITE="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
rm -rf "$SITE/leapc_cffi"
cp -R "$SDK/leapc_cffi" "$SITE/"

echo "OK: environment ready at $VENV"
"$ROOT/scripts/verify-env.sh"
