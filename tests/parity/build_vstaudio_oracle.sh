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
#
# The source comes out of micropython-vst3's git history, not its working
# tree. That repository imports audiodynamics and audioroute now and deleted
# its own copy, so its tree is no longer independent of what it is meant to
# check. VSTAUDIO_REV is the last revision that still had it; an oracle
# pinned to a revision cannot drift.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
AUDIOIF=$(cd "$HERE/../.." && pwd)
WORKSPACE=$(cd "$AUDIOIF/.." && pwd)
MP_UNIX="$WORKSPACE/cmods/micropython/ports/unix"
VST3="${VST3:-$WORKSPACE/micropython-vst3}"
VSTAUDIO_REV="${VSTAUDIO_REV:-ac87f13}"
VSTAUDIO_PATH=usermods/vstaudio/vstaudio_dsp.c
BUILD_DIR="${BUILD_DIR:-$MP_UNIX/build-vstaudio-oracle}"
MODULES=$(mktemp -d)
trap 'rm -rf "$MODULES"' EXIT

[[ -e "$MP_UNIX/Makefile" ]] || { echo "not found: $MP_UNIX/Makefile" >&2; exit 1; }
if ! git -C "$VST3" cat-file -e "$VSTAUDIO_REV:$VSTAUDIO_PATH" 2>/dev/null; then
    echo "not in $VST3 at $VSTAUDIO_REV: $VSTAUDIO_PATH" >&2
    exit 1
fi

# Stand the file up where the usermod expects it, out of history.
mkdir -p "$MODULES/micropython-vst3/usermods/vstaudio"
git -C "$VST3" show "$VSTAUDIO_REV:$VSTAUDIO_PATH" \
    > "$MODULES/micropython-vst3/$VSTAUDIO_PATH"

ln -s "$AUDIOIF" "$MODULES/audioif"
ln -s "$WORKSPACE/cmods/ulab" "$MODULES/ulab"
ln -s "$HERE/vstaudio_oracle" "$MODULES/vstaudio_oracle"

make -C "$MP_UNIX" -j"$(nproc)" \
    BUILD="$BUILD_DIR" USER_C_MODULES="$MODULES" FROZEN_MANIFEST= "$@"

echo
echo "oracle interpreter: $BUILD_DIR/micropython"
