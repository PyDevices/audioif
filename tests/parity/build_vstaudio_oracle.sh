#!/usr/bin/env bash
# Build the MicroPython binary that runs the *original* Dynamics and Splitter,
# for capturing the audiodynamics/audioroute goldens. See
# vstaudio_oracle/module.c for what it contains and why it exists.
#
#   tests/parity/build_vstaudio_oracle.sh
#   → cmods/micropython/ports/unix/build-vstaudio-oracle/micropython
#
# The usermod search path is a scratch tree of symlinks rather than the real
# workspace: MicroPython discovers usermods by globbing USER_C_MODULES one
# level deep, so an oracle living in the workspace would end up compiled into
# every interpreter this workspace builds.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
AUDIOIF=$(cd "$HERE/../.." && pwd)
WORKSPACE=$(cd "$AUDIOIF/.." && pwd)
MP_UNIX="$WORKSPACE/cmods/micropython/ports/unix"
VST3="${VST3:-$WORKSPACE/micropython-vst3}"
BUILD_DIR="${BUILD_DIR:-$MP_UNIX/build-vstaudio-oracle}"
MODULES=$(mktemp -d)
trap 'rm -rf "$MODULES"' EXIT

for missing in "$MP_UNIX/Makefile" "$VST3/usermods/vstaudio/vstaudio_dsp.c"; do
    [[ -e "$missing" ]] || { echo "not found: $missing" >&2; exit 1; }
done

ln -s "$AUDIOIF" "$MODULES/audioif"
ln -s "$WORKSPACE/cmods/ulab" "$MODULES/ulab"
ln -s "$VST3" "$MODULES/micropython-vst3"
ln -s "$HERE/vstaudio_oracle" "$MODULES/vstaudio_oracle"

make -C "$MP_UNIX" -j"$(nproc)" \
    BUILD="$BUILD_DIR" USER_C_MODULES="$MODULES" FROZEN_MANIFEST= "$@"

echo
echo "oracle interpreter: $BUILD_DIR/micropython"
