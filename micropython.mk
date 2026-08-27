# MicroPython Make-based build glue for audioif (unix, windows).
# For CMake-based ports (esp32, rp2, …), see micropython.cmake in this dir.
#
# Discovered via USER_C_MODULES pointing at the workspace directory that
# contains this repo (its parent) — see cmods/build_mp.sh.

MPAUDIO_MOD_DIR := $(USERMOD_DIR)
MPAUDIO_SRC_DIR := $(MPAUDIO_MOD_DIR)/src

CFLAGS_USERMOD += -I$(MPAUDIO_SRC_DIR)

# --- cp_compat: small shims for CircuitPython-only helpers (mp_arg_validate_*,
#     cp_enum, MP_PROPERTY_GETTER/GETSET, default___enter__/__exit__) that the
#     ported CircuitPython audio/synthio sources call directly. See
#     docs/porting-plan.md tier 0 and src/cp_compat/*.h for provenance.
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/cp_compat/argcheck.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/enum.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/context_manager_helpers.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/proto.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/util.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/objproperty.c \
    $(MPAUDIO_SRC_DIR)/cp_compat/namedtuple.c

# --- runtime-neutral sample protocol/state shared with the CPython wheel
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/shared/audioif_sample.c \
    $(MPAUDIO_SRC_DIR)/shared/audioif_rawsample.c \
    $(MPAUDIO_SRC_DIR)/shared/audioif_synth_dsp.c \
    $(MPAUDIO_SRC_DIR)/shared/audioif_envelope.c \
    $(MPAUDIO_SRC_DIR)/shared/audioif_distortion.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_biquad.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_echo.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_phaser.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_chorus.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_multitap.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_pitchshift.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_freeverb.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_dynamics.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_splitter.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_multiply.c
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/shared/audioif_feedback_delay.c

# --- ulab (numpy-alike): cloned sibling dependency, pinned to match this
#     workspace's CircuitPython checkout (see docs/porting-plan.md). Its own
#     code/micropython.mk expects USERMOD_DIR to point at ulab/code; the
#     workspace CMake aggregator finds ulab/code/micropython.cmake on its
#     own (mindepth 2/maxdepth 3), but py.mk's Make-port loop only globs
#     $(USER_C_MODULES)/*/micropython.mk at depth 1, so chain it in here.
#     USERMOD_DIR is restored below since ulab's makefile does not save it.
MPAUDIO_ULAB_CODE_DIR := $(abspath $(MPAUDIO_MOD_DIR)/../ulab/code)
ifneq ($(wildcard $(MPAUDIO_ULAB_CODE_DIR)/ulab.c),)
USERMOD_DIR := $(MPAUDIO_ULAB_CODE_DIR)
include $(MPAUDIO_ULAB_CODE_DIR)/micropython.mk
USERMOD_DIR := $(MPAUDIO_MOD_DIR)

# `import ulab.numpy` / `import ulab.scipy` are dotted submodule imports of a
# built-in (ulab's globals dict has `numpy`/`scipy` as plain module-typed
# entries, same shape CircuitPython relies on for its own dotted built-ins).
# Mainline only walks that path when MICROPY_MODULE_BUILTIN_SUBPACKAGES is
# on (py/builtinimport.c, process_import_at_level); off by default outside
# the "everything" ROM level. CFLAGS_EXTRA reaches every compiled object for
# this port (see ports/unix/Makefile), not just usermod sources, so this
# turns it on build-wide -- confirmed needed by testing `import ulab.numpy`
# against this exact ulab pin on the unix standard variant.
override CFLAGS_EXTRA += -DMICROPY_MODULE_BUILTIN_SUBPACKAGES=1
endif

# --- module skeleton: empty `import <name>` targets for every top-level
#     module this tree will grow into (see docs/porting-plan.md). Tiers add
#     real classes/functions by editing mpaudio_modules.c's globals tables
#     directly, so this stays the single source of each module's contents.
SRC_USERMOD_C += $(MPAUDIO_SRC_DIR)/mpaudio_modules.c

# --- tier 1: audiocore (the audiosample protocol, RawSample, WaveFile) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiocore/__init__.c \
    $(MPAUDIO_SRC_DIR)/audiocore/RawSample.c \
    $(MPAUDIO_SRC_DIR)/audiocore/WaveFile.c \
    $(MPAUDIO_SRC_DIR)/audiocore/module.c

# --- tier 2: synthio (block layer, Math, LFO, Biquad, Note, Synthesizer,
#     MidiTrack) ---
#
# CIRCUITPY_SYNTHIO_MAX_CHANNELS: src/synthio/__init__.h defaults this to 2
# (CP's own conservative default -- see the comment there), which caps
# concurrent Notes across an entire Synthesizer, not per-key. Any
# realistic polyphonic patch blows past 2 immediately (two notes held on a
# 2-oscillator/detuned voice is already 4 concurrent Notes), silently
# stealing/truncating voices well before it looks polyphonic. Upstream
# handles this per-port (ports/raspberrypi/mpconfigport.mk: 24,
# ports/nordic: 12, ...); this workspace's CircuitPython parity oracle
# (cmods/circuitpython's unix `coverage` variant, bin/circuitpython) is
# itself built with 14 (ports/unix/variants/coverage/mpconfigvariant.mk).
# unix/windows/wasm (every port this Make-based file covers) match that so
# oracle-diff parity tests (see tests/parity/synthtools_acceptance.py, phase
# 7) exercise -- and byte-diff -- genuine polyphony instead of silently
# degrading it; an mcu board's own value (micropython.cmake, CMake ports)
# is a phase 10 (port matrix) decision, not this one.
CFLAGS_USERMOD += -DCIRCUITPY_SYNTHIO_MAX_CHANNELS=14
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/synthio/__init__.c \
    $(MPAUDIO_SRC_DIR)/synthio/Math.c \
    $(MPAUDIO_SRC_DIR)/synthio/LFO.c \
    $(MPAUDIO_SRC_DIR)/synthio/Biquad.c \
    $(MPAUDIO_SRC_DIR)/synthio/Note.c \
    $(MPAUDIO_SRC_DIR)/synthio/Synthesizer.c \
    $(MPAUDIO_SRC_DIR)/synthio/MidiTrack.c

# --- tier 3: audiomixer (Mixer, MixerVoice) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiomixer/Mixer.c \
    $(MPAUDIO_SRC_DIR)/audiomixer/MixerVoice.c \
    $(MPAUDIO_SRC_DIR)/audiomixer/module.c

# --- tier 4: effects (audiospeed) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiospeed/SpeedChanger.c \
    $(MPAUDIO_SRC_DIR)/audiospeed/module.c

# --- tier 4: effects (audiofreeverb) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiofreeverb/Freeverb.c \
    $(MPAUDIO_SRC_DIR)/audiofreeverb/module.c

# --- tier 4: effects (audiofilters) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiofilters/Filter.c \
    $(MPAUDIO_SRC_DIR)/audiofilters/Distortion.c \
    $(MPAUDIO_SRC_DIR)/audiofilters/Phaser.c \
    $(MPAUDIO_SRC_DIR)/audiofilters/module.c

# --- tier 4: effects (audiodelays) ---
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiodelays/Chorus.c \
    $(MPAUDIO_SRC_DIR)/audiodelays/Echo.c \
    $(MPAUDIO_SRC_DIR)/audiodelays/MultiTapDelay.c \
    $(MPAUDIO_SRC_DIR)/audiodelays/PitchShift.c \
    $(MPAUDIO_SRC_DIR)/audiodelays/module.c

# --- tier 6: audiodynamics (Dynamics, DYN_*), audioroute (Splitter) and
#     audiomath (Multiply) ---
#
# The modules here are not CircuitPython ports. The first two come from
# micropython-vst3's `vstaudio` usermod, which grew them for its effects
# library; audiomath is audioif's own, and is the only way to modulate a
# stream at audio rate. See docs/upstream-diff.md.
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiodynamics/Dynamics.c \
    $(MPAUDIO_SRC_DIR)/audiodynamics/module.c
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audioroute/Splitter.c \
    $(MPAUDIO_SRC_DIR)/audioroute/SplitterTap.c \
    $(MPAUDIO_SRC_DIR)/audioroute/module.c
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiomath/Multiply.c \
    $(MPAUDIO_SRC_DIR)/audiomath/module.c
SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audioecho/FeedbackDelay.c \
    $(MPAUDIO_SRC_DIR)/audioecho/module.c

# --- tier 5: audiomp3 (MP3Decoder) ---
#
# lib/mp3: a cloned sibling dependency at cmods/mp3 (the upstream
# adafruit/Adafruit_MP3 repo, pinned to the exact commit
# cmods/circuitpython/lib/mp3 vendors), not a port -- same treatment as
# ulab above. Its `src/` is the Helix fixed-point MP3 decoder (RealNetworks,
# 2003), under RPSL 1.0/RCSL 1.0 per-file headers, NOT MIT; CircuitPython
# itself carries it unmodified under those terms rather than relicensing it,
# and so does this port -- see docs/upstream-diff.md, "Tier 5 audiomp3:
# license" for the full check. One local patch was needed on top of the
# pinned commit (cmods/mp3/src/assembly.h): its MSVC-only inline-asm branch
# guards on `defined _WIN32`, which mingw-w64 GCC (this workspace's Windows
# MicroPython target) also defines, so it now also excludes __GNUC__ and
# falls through to the portable C path instead -- CircuitPython itself never
# hits this, since it has no Windows port. See docs/upstream-diff.md for the
# full patch rationale.
# mp3dec.h picks its platform-specific fixed-point/asm path by matching a
# closed list of (__GNUC__ + arch) combinations, with an explicit
# MP3DEC_GENERIC escape hatch for anything else -- `#error No platform
# defined` otherwise. Emscripten/wasm32 matches none of the listed
# combinations (it's not __i386__/__amd64__/ARM), so it needs that escape
# hatch; unix (__amd64__) and windows/mingw-w64 (__i386__ or __amd64__,
# already covered by the same __GNUC__ branches unix uses) both match a
# named branch already and must NOT get this -- it would silently swap
# their working platform-specific path for the portable fallback. Detect
# the wasm port the same way cmods/wasmbridge/micropython.mk does, since
# there's no other reliable way to ask "which port is this" from inside a
# Make port's shared USER_C_MODULES glue.
MPAUDIO_WASM_PORT := $(findstring /ports/webassembly,$(abspath $(CURDIR)))
ifneq ($(MPAUDIO_WASM_PORT),)
CFLAGS_USERMOD += -DMP3DEC_GENERIC
endif

MPAUDIO_MP3_SRC_DIR := $(abspath $(MPAUDIO_MOD_DIR)/../mp3/src)
ifneq ($(wildcard $(MPAUDIO_MP3_SRC_DIR)/mp3dec.c),)
CFLAGS_USERMOD += -I$(MPAUDIO_MP3_SRC_DIR)
SRC_USERMOD_C += $(addprefix $(MPAUDIO_MP3_SRC_DIR)/, \
    bitstream.c \
    buffers.c \
    dct32.c \
    dequant.c \
    dqchan.c \
    huffman.c \
    hufftabs.c \
    imdct.c \
    mp3dec.c \
    mp3tabs.c \
    polyphase.c \
    scalfact.c \
    stproc.c \
    subband.c \
    trigtabs.c \
    )

# buffers.c's MPDEC_ALLOCATOR(x)/MPDEC_FREE(x) macros (used nowhere else in
# lib/mp3) route through this port's own mp3_alloc()/mp3_free()
# (src/audiomp3/mp3_alloc.h -> m_malloc_maybe/m_free), matching upstream's
# own production (non-coverage-build) allocator wiring exactly, including
# the -fwrapv upstream applies to this one file only (Helix's fixed-point
# DSP relies on defined signed-overflow wraparound here).
$(BUILD)/mp3/src/buffers.o: CFLAGS += -include "$(MPAUDIO_SRC_DIR)/audiomp3/mp3_alloc.h" -D'MPDEC_ALLOCATOR(x)=mp3_alloc(x)' -D'MPDEC_FREE(x)=mp3_free(x)' -fwrapv

SRC_USERMOD_C += \
    $(MPAUDIO_SRC_DIR)/audiomp3/mp3_alloc.c \
    $(MPAUDIO_SRC_DIR)/audiomp3/MP3Decoder.c \
    $(MPAUDIO_SRC_DIR)/audiomp3/module.c
endif
