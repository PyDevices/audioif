# Deltas from upstream CircuitPython

Running log of every place this port's behavior deliberately differs from
CircuitPython's, or needed a workspace-side fix that isn't a plain port.
Goal: keep this list short. Python-level API and behavior match CP unless
noted here.

## Property invocation needs an explicit `attr` slot (tier 0/1, all tiers after)

CircuitPython's `MP_PROPERTY_GETTER`/`MP_PROPERTY_GETSET` (declared via
`py/objproperty.h`) only work in CircuitPython because CP patches its own
`py/runtime.c` (`mp_convert_member_lookup`, tagged `CIRCUITPY-CHANGE`) to
recognize a `mp_type_property` value sitting in a *native* type's
`locals_dict` and invoke its getter/setter. Mainline MicroPython's
`mp_convert_member_lookup` has no such case — confirmed by reading it
directly, not assumed. Discovered the hard way: a first pass at
`audiocore.RawSample` built cleanly but `sample_rate` returned the raw
property object (`<property>`) instead of its value, and assigning to it
raised `AttributeError`.

Can't carry CP's core patch (no edits to `micropython/`). Fix lives entirely
in this usermod: `cp_compat_attr` (`src/cp_compat/objproperty.c`)
reimplements the same lookup-and-invoke logic from usermod code, using
mainline's own supported extension point for this — a type's `attr` slot
(the same mechanism mainline's own `examples/usercmodule/cexample`
demonstrates for its `AdvancedTimer.seconds` property).

**Consequence for every future tier**: every `MP_DEFINE_CONST_OBJ_TYPE(...)`
call for a type that uses `MP_PROPERTY_GETTER`/`GETSET` in its
`locals_dict` must add `attr, cp_compat_attr` to that type's slot list, or
the property is silently unreadable/unwritable at runtime (it builds fine —
this doesn't show up as a compile error). `RawSample` and `WaveFile` do
this; use them as the reference when porting `Note`, `Synthesizer`, `Mixer`,
`MixerVoice`, and the effects types.

## WaveFile: portable stream I/O instead of direct FatFS calls (tier 1)

CircuitPython's `audiocore.WaveFile` reads its file via raw FatFS calls
(`f_read`/`f_lseek`/`f_tell` against a `pyb_file_obj_t`'s embedded `.fp`),
and its constructor hard-requires `mp_obj_is_type(arg, &mp_type_vfs_fat_fileio)`.
This only works when the mounted filesystem is FatFS — confirmed by testing
directly: even CircuitPython's own unix `coverage` build (`bin/circuitpython`
in this workspace, used as the parity oracle everywhere else) raises
`TypeError: file must be a file opened in byte mode` for `WaveFile(path)`
*and* `WaveFile(open(path, "rb"))`, because the unix port's `open()` returns
a POSIX-backed file object, not a `vfs_fat_fileio` one. WaveFile is
effectively FAT/MCU-only upstream, undocumented as such.

This port's `WaveFile` (`src/audiocore/WaveFile.c`) reads through
MicroPython's generic stream protocol instead (`mp_stream_read_exactly` +
an `ioctl(MP_STREAM_SEEK)`), which works over any VFS a port has mounted
(POSIX files on unix/windows, littlefs or FAT on mcu boards). The WAV chunk
parsing and the double-buffered refill/`get_buffer` state machine are an
unchanged, mechanical port — verified byte-for-byte against Python's own
`wave` module output for a generated test tone (`nbytes`/checksum/first-
and-last-32-bytes all matched exactly). Because CircuitPython's own unix
build can't open a WaveFile at all, a true CP-oracle diff for WaveFile PCM
output isn't possible on this port; if a FAT-mounted test fixture becomes
available later (real MCU or a FAT disk image), redo this comparison
directly against CP for full confidence — it's expected to match, since the
buffer/refill logic itself is unmodified, but it hasn't been checked yet
that way.

## `synthio.from_file`: same portable-stream deviation as WaveFile (tier 2)

`synthio.from_file()` (loads a `MidiTrack` from an SMF file) has the exact
same FatFS coupling as `audiocore.WaveFile` — same fix, same rationale: see
"WaveFile: portable stream I/O instead of direct FatFS calls" above. Only
this one function needed it in tier 2; `synthio.MidiTrack(buffer, tempo)`
itself (constructing from an in-memory buffer, no file I/O) is an unchanged
mechanical port. Verified functionally with a hand-built SMF fixture
(`from_file` accepts both a path string and an already-open file object);
no CP-oracle comparison possible here either, for the same reason as
WaveFile.

## `fpclassify()` triggers a false-positive `-Wfloat-conversion` here (tier 2)

`synthio/Math.c`'s `OP_MUL_DIV`/`OP_DIV_ADD`/`OP_ADD_DIV` cases used
upstream's `fpclassify(x) == FP_ZERO` to test for exact zero. This port's
unix build enables `-Wfloat-conversion -Werror` (`ports/unix/Makefile`),
and glibc's type-generic `fpclassify()` macro expands to a ternary across
`__fpclassifyf`/`__fpclassify`/`__fpclassifyl` (float/double/long double)
that GCC apparently still type-checks on the untaken branches, so it
flags a double truncating to float even though `mp_float_t` is `double`
here. Replaced with a direct `x == 0` comparison — exactly equivalent for
testing "is this float exactly zero" (`+0.0 == -0.0` is true in IEEE 754,
same outcome `fpclassify` would give), and avoids the compiler-specific
warning. If a future mcu toolchain doesn't hit this warning, the direct
comparison is still correct there, so no port-specific `#ifdef` needed.

## `audiomixer`: synthio block-input made unconditional, ARM CMSIS dropped (tier 3)

Two deviations, both mechanical:

- CircuitPython guards `MixerVoice.level`/`.panning` as `synthio_block_slot_t`
  behind `#if CIRCUITPY_SYNTHIO` (some CP boards omit synthio entirely) and
  falls back to plain scaled-uint16 fields otherwise. This port always
  builds synthio (tier 2), so the block-input path
  (`src/audiomixer/MixerVoice.h/.c`) is unconditional; the plain-float
  fallback fields and branches in `mix_down_one_voice`
  (`src/audiomixer/Mixer.c`) are dropped rather than carried as dead code.
- `Mixer.c`'s bit-twiddling helpers (`add16signed`, `mult16signed`,
  `tounsigned8/16`, `tosigned16`) have ARM Cortex-M4/M7 CMSIS DSP intrinsic
  fast paths (`__QADD16`, `__UADD8`, `__UADD16`, gated on
  `__ARM_ARCH_7EM__`) plus a top-of-file `#include "cmsis_compiler.h"`
  gated on `__arm__`. Dropped in favor of the portable C fallback
  unconditionally: numerically identical (verified via oracle-diff, not
  just assumed), and this port doesn't vendor CMSIS, so the include would
  be a dangling dependency on any ARM mcu build (phase 9) that doesn't
  happen to have it on the include path -- including non-DSP cores like
  Cortex-M0+ (rp2), where `__QADD16` isn't even a valid instruction.

Verified via oracle-diff against `bin/circuitpython` across every branch
`mix_down_one_voice`/`audiomixer_mixer_get_buffer` can take: mono source
into mono mixer, mono source upmixed into a stereo mixer with panning,
16-bit signed, 8-bit unsigned, single- and multi-voice mixdown (verbatim-
copy vs. add-mixed paths), looping, and `level`/`panning` driven by a
`synthio.LFO`/`synthio.Math` block input instead of a plain float -- all
byte-for-byte identical, including the `Mixer.reset_buffer` semantics
(stops every voice; call it before attaching voices, exactly like an
output device's `play()` would, not after -- documented here because a
first draft of the parity test called it in the wrong order and produced
an all-zero-but-still-oracle-matching result, which was CP's real
behavior for that call order, not a bug).

## Tier 4 effects: `audiospeed`, `audiofreeverb`, `audiofilters`, `audiodelays`

Nine types across four modules, all mechanical ports with the same fix
pattern as every prior tier (`m_malloc_without_collect` -> `m_malloc`,
`attr, cp_compat_attr` added to every type registration). Module-specific
notes:

- **`audiospeed.SpeedChanger`** has no oracle in the canonical
  `bin/circuitpython`: `CIRCUITPY_AUDIOSPEED` is gated per-port (only
  `ports/raspberrypi/mpconfigport.mk` sets it), and this workspace's unix
  coverage variant (`circuitpython/ports/unix/variants/coverage/mpconfigvariant.mk`)
  hand-lists its `SRC_C` files rather than using the `CIRCUITPY_AUDIOSPEED`
  Make-variable cascade, so simply passing the flag on the command line
  doesn't pull the module in. Verified anyway: built a *temporary* oracle
  by adding `shared-bindings/audiospeed/{__init__,SpeedChanger}.c` and
  `shared-module/audiospeed/{__init__,SpeedChanger}.c` to that variant file
  and rebuilding into a scratch `ports/unix/build-coverage-audiospeed/`
  directory (never touching the canonical `build-coverage/`), diffed
  byte-for-byte, then reverted the variant-file edit and deleted the
  scratch build -- `cmods/circuitpython` is back to its pre-existing local
  patch state, unmodified beyond that one-off test. Also needed the same
  `0.001`/`1000.0` -> `0`/`1000` literal-truncation fix as this port's
  `rate_to_fp` for `mp_arg_validate_obj_float_range`'s int-typed min/max
  (this is a *stock upstream* compile hazard under `-Wfloat-conversion
  -Werror`, not something introduced by the port -- confirmed by building
  CircuitPython's own unmodified `SpeedChanger.c` and hitting the same
  error; it has apparently never been caught because unix is the only
  build that enables that warning and unix never compiles this module by
  default).
- **`audiofreeverb.Freeverb`** ported unchanged, including upstream's own
  `combfitlers` identifier typo and the type's lowercase `MP_QSTR_freeverb`
  name (so `type(x).__name__` prints `"freeverb"` even though the class is
  `audiofreeverb.Freeverb`) -- both kept verbatim for parity, confirmed
  genuine upstream quirks (not transcription errors) by reading the
  original source directly.
- **`audiofilters.Distortion`** originally had two verbatim-kept upstream
  oddities; one was later reversed (see "Distortion soft_clip" below, phase
  8d) once it turned out to be architecture-dependent rather than a stable
  quirk. The one still kept verbatim: the unsigned-16-bit silence path's
  `memset(word_buffer, 32768, ...)`, which -- because `memset`'s fill value
  truncates to an `unsigned char` -- actually writes zero bytes, not the
  intended `0x8000` "quiet" level. `audiodelays.PitchShift` has the same
  `memset(..., 32768, ...)` quirk in its own silence path, plus a separate
  one: its per-sample `buf_offset` calculation ignores
  `single_channel_output` entirely (`channel == 1 || i % channel_count == 1`,
  unlike every sibling effect's
  `(single_channel_output && channel == 1) || (!single_channel_output && ...)`
  pattern) -- upstream's own inconsistency between effects, not a port bug.
- **`audiodelays.Chorus`** and **`audiodelays.PitchShift`** each define a
  custom `__exit__` that calls `common_hal_..._deinit(args[0])` directly
  instead of using the shared `default___exit___obj` method-dispatch
  helper every other type in this port uses -- kept verbatim as upstream's
  own micro-optimization for those two types specifically, not a port
  artifact.

All nine types (`SpeedChanger`, `Freeverb`, `Filter`, `Distortion`,
`Phaser`, `Chorus`, `Echo`, `MultiTapDelay`, `PitchShift`) verified
byte-for-byte against the oracle across mono/stereo, 8/16-bit
signed/unsigned, looping, block-input-driven (`synthio.LFO`) parameters,
mid-stream parameter changes, `stop()`/tail-drain behavior, and (for
`MultiTapDelay`) invalid-input error paths -- including the exact error
message text (a CRLF-vs-LF difference in how each interpreter's traceback
printer formats output was the only non-match found anywhere in this tier,
confirmed as a REPL-layer difference between CircuitPython and mainline
MicroPython, unrelated to any ported module).

## Phase 7: `synthtools` end-to-end acceptance test

`tests/vendor/synthtools` is todbot's
[`CircuitPython_SynthTools`](https://github.com/todbot/CircuitPython_SynthTools)
(MIT, commit recorded in `tests/vendor/SYNTHTOOLS_COMMIT.txt`), vendored
unmodified -- the `synthtools/` package only, not `examples/`/`tests/`/
`docs/`, since the acceptance script (`tests/parity/synthtools_acceptance.py`)
is this port's own, not upstream's. It drives `SubtractiveSynth` (dual
detuned oscillators, filter envelope, vibrato, pitch envelope, an
LFO-driven cutoff sweep, live mid-note parameter writes, a JSON patch
round-trip) and `BasslineSynth` (mono, decay-only filter envelope, glide)
through a real `synthio.Synthesizer` + `audiomixer.Mixer`, with an
`EffectsChain` wiring in `audiofilters.Filter` (via `tracking_filter()`),
`audiofilters.Distortion`, and `audiodelays.Echo` -- i.e. tiers 2/3/4 all
exercised together through an unmodified third-party engine, which is what
"full parity" is actually for. Runs unchanged on both interpreters; the
runner diffs stdout.

**Found and fixed a real port bug, not a verbatim-kept quirk:**
`src/synthio/__init__.h` defines `CIRCUITPY_SYNTHIO_MAX_CHANNELS` (max
concurrent `Note`s across one `Synthesizer`, not per-key) defaulting to 2 --
correctly mirroring CP's own conservative default
(`py/circuitpy_mpconfig.mk`). But this port's unix/windows build never
overrode it, while this workspace's CircuitPython oracle
(`cmods/circuitpython`'s unix `coverage` variant, `bin/circuitpython`) is
itself built with `-DCIRCUITPY_SYNTHIO_MAX_CHANNELS=14`
(`ports/unix/variants/coverage/mpconfigvariant.mk`). At 2, anything past
the first two concurrently-alive `Note`s (e.g. two held notes on a
detuned/dual-oscillator patch -- already 4 `Note`s) silently truncates
voices, and every `synthio.LFO`/`synthio.Math` block nested under an
evicted voice desyncs from the oracle from that point on. Isolated via
binary search on `tests/parity/synthtools_acceptance.py`'s divergence: a
single note-lifecycle (attack through release, no overlap) matched
byte-for-byte on this port's *unpatched* build; 2 overlapping plain notes
(no modulation) also matched; 3+ overlapping notes, or 2 overlapping
notes on a detuned (2-oscillator) patch, diverged -- both cross the
2-concurrent-`Note` ceiling. Fixed by setting
`CFLAGS_USERMOD += -DCIRCUITPY_SYNTHIO_MAX_CHANNELS=14` in
`micropython.mk` (unix/windows only, matching the oracle's own build
choice so voice-stealing arithmetic lines up exactly, not just "enough
channels"); `micropython.cmake` (mcu/CMake ports) deliberately leaves the
header's conservative default of 2 alone, since the right value there is
a phase 10 (port matrix) RAM/polyphony tradeoff, not this one. Rebuilt
`bin/micropython` and reran the full tier 0-4 parity suite plus the LVGL
smoke test after the change: clean, no regressions.

**Test-harness-only, not a port deviation:** `synthtools/waves.py`'s
`random_phase_wave()` (used by `SubtractiveSynth._make_notes()` on every
note-on, by design -- see its docstring) calls `random.randint()` to pick
each oscillator's starting phase. MicroPython's and CircuitPython's
`random` modules implement different PRNGs, so the same script would
legitimately render different-but-valid PCM on each interpreter and defeat
a byte-exact diff. Neither interpreter's built-in `random` module allows
monkeypatching an attribute onto it directly (both raise `AttributeError`
on `random.randint = ...`), so `synthtools_acceptance.py` pre-seeds a tiny
deterministic-LCG substitute into `sys.modules["random"]` before importing
`synthtools` -- import picks up the substitute via the module cache, no
vendored file touched. This is a property of the test script, not of
`synthtools` or of the port.

Verified byte-for-byte against `bin/circuitpython`: the full acceptance
script's stdout (four `SubtractiveSynth` notes with a mid-run live
`filt_f`/`wave` change, a `pitch_bend()` sweep, a `Patch` JSON round-trip
reconstructing an equivalent synth, four `BasslineSynth` steps with
glide, `all_notes_off()`/`voice.stop()` tail-drain, and final `Mixer`
state) is identical after the `CIRCUITPY_SYNTHIO_MAX_CHANNELS` fix.

## Tier 5 audiomp3: license

CircuitPython's `lib/mp3` (upstream `adafruit/Adafruit_MP3`, cloned here as
`cmods/mp3` pinned to the same commit, `aac02afd9f24d2ee930f650156654ab9211a306a`)
is the Helix fixed-point MP3 decoder, originally developed by RealNetworks in
2003. Every core decoder source file (`bitstream.c` through `statname.h`,
i.e. everything actually compiled -- not `Adafruit_MP3.cpp`/`.h`, Adafruit's
own Arduino wrapper, which neither CircuitPython nor this port uses) carries
a `RCSL 1.0/RPSL 1.0` SPDX-style header block, not MIT:

    Portions Copyright (c) 1995-2002 RealNetworks, Inc. All Rights Reserved.
    ... subject to the current version of the RealNetworks Public Source
    License Version 1.0 (the "RPSL") ... or ... the RealNetworks Community
    Source License Version 1.0 (the "RCSL") ...

RPSL 1.0 is an OSI-approved open-source license; the obligation it places is
on *modifications to the licensed files themselves* (publish them under
RPSL), not on other code that merely links against or calls into them --
this is exactly the same relationship a project has with any vendored
GPL-incompatible-but-OSI-approved C library, and it is precisely how
CircuitPython itself (MIT overall) carries this dependency: unmodified,
under its own original headers, no relicensing attempted, no separate
top-level LICENSE entry for it either (confirmed -- CircuitPython's own repo
has no `lib/mp3`-specific license documentation beyond the per-file
headers). This port does the same: `cmods/mp3` is vendored verbatim (one
local patch, see below, kept as narrow as possible and documented inline),
its RPSL/RCSL headers untouched, and this section is the disclosure.
`cmods/mp3/examples/test.mp3` (Adafruit's own bundled test fixture, used for
oracle-diff verification below) ships alongside it, license unclear but
not carried into this repo's own source tree -- it's a test fixture read at
test time from the cloned sibling, not vendored content.

## Tier 5 audiomp3: three Windows-only local fixes, no unix impact

All three were found only when building/running this workspace's Windows
MicroPython target (`mp-windows`/mingw-w64) -- CircuitPython has no Windows
port, so none was ever reachable upstream:

- **`cmods/mp3/src/assembly.h`** picks an MSVC-only inline-`__asm{}` code
  path (plus an MSVC-only `#pragma warning`) whenever `_WIN32` is defined
  and `_WIN32_WCE` isn't. mingw-w64 GCC also defines `_WIN32` (confirmed:
  `echo | x86_64-w64-mingw32-gcc -dM -E - | grep _WIN32` -> `#define _WIN32
  1`), so it hit that branch and failed to compile (`__asm { mov eax, x ...
  }` is not valid GCC syntax under any target). Local patch: added
  `&& !defined(__GNUC__)` to the branch's condition, falling through to the
  file's portable C implementation (`FASTABS`/`MULSHIFT32`/`CLZ` as plain C,
  no inline asm) -- the same path this port's unix build already takes,
  since `_WIN32` is never defined there. Patch is inline-commented in the
  file itself with a pointer back to this section.
- **This port's own `src/audiomp3/mp3_alloc.c`** (`mp3_alloc`/`mp3_free`,
  standing in for CP's `shared-module/audiomp3/__init__.c`) dropped
  upstream's `MP_WEAK` (`__attribute__((weak))`). Upstream needs it so a
  board can override the allocator via `CIRCUITPY_AUDIOMP3_USE_PORT_ALLOCATOR`;
  this port has no such opt-in, so there is never a second, strong
  definition anywhere in the link. `x86_64-w64-mingw32-ld` failed with
  "undefined reference to `mp3_alloc`/`mp3_free`" during `micropython.exe`
  linking even though `mp3_alloc.o` compiled cleanly and `nm` showed both
  symbols correctly emitted as PE weak externals (`.weak.mp3_alloc.` /
  `w mp3_alloc`) -- a lone weak definition with nothing else in the link
  strongly referencing it is a known mingw-w64/GNU-ld PE-COFF gap, distinct
  from ELF (this port's own unix build resolves the identical weak-only
  definition without issue). Dropping `MP_WEAK` entirely -- correct here
  since nothing in this port ever needs to override these two one-line
  wrappers -- fixed the windows link with no effect on unix.
- **`src/audiomp3/MP3Decoder.c`'s `stream_readable()`** (ported from CP's
  own `MP3Decoder.c`) calls `stream_p->ioctl(stream, MP_STREAM_POLL, ...)`
  to check whether the input stream has data ready before attempting a
  read. Found by running the phase 7/9 oracle-diff parity scripts under
  `bin/micropython.exe` for the first time (phase 8c) -- previously only
  verified on unix and against `bin/circuitpython`, neither of which
  exercises this path the same way. Mainline's own
  `extmod/vfs_posix_file.c` raises `NotImplementedError("poll on file not
  available on win32")` from `MP_STREAM_POLL` for a real POSIX-style file
  object (not a socket) on `_WIN32` -- not a bug in this port, a documented
  gap in mainline's own windows-port VFS ioctl implementation, confirmed by
  reading that file directly. Every successful frame decode from a real
  file calls this (via the synchronous `background_callback_add` stub --
  see `cp_compat/background_callback.h`), so `MP3Decoder` reading from an
  `open()`ed file was completely broken on `micropython.exe` before this
  fix: the very first `get_buffer()` past the first frame raised. Local fix:
  `stream_readable()` now has an `#ifdef _WIN32` branch that skips the poll
  call and returns `true` unconditionally, exactly the same fallback
  already used a few lines below for a stream with no `ioctl` slot at all --
  `mp3file_update_inbuf_always()`'s own non-blocking-read handling
  (`mp_is_nonblocking_error`) is what actually prevents a stall either way,
  so this is a false-availability-check removal, not a correctness change.
  Verified: `parity_mp3decoder.py`/`parity_mp3decoder2.py`, previously
  untested on windows, now pass byte-for-byte against `bin/circuitpython`
  under `micropython.exe`; unix behavior (and the `_WIN32` branch never
  taken there) is unaffected, confirmed by re-running the full tier 0-5
  parity suite plus the LVGL smoke test on unix after the change.

## Tier 5 audiomp3: allocator wiring diverges from upstream (both are correct)

Upstream's Make glue picks between two different `MPDEC_ALLOCATOR(x)`/
`MPDEC_FREE(x)` wirings for `lib/mp3/src/buffers.c` depending on build
variant: the unix `coverage` variant (this workspace's oracle,
`bin/circuitpython`) wires straight to `malloc(x)`/`free(x)`; every other
CP port wires through `mp3_alloc(x)`/`mp3_free(x)`
(`shared-module/audiomp3/__init__.c`, `MP_WEAK`, defaulting to
`m_malloc_maybe`/`m_free`). This port always uses the second (production)
path -- see docs/porting-plan.md, "Tier 5" -- since it changes only where
the Helix decoder's internal buffers come from (GC heap vs. the C heap),
never the rendered PCM, confirmed by the byte-exact oracle diffs below
against a `bin/circuitpython` that itself takes the *other* path: this is a
build-configuration choice invisible to output, not a parity-relevant
deviation. `mp3_free` itself also isn't a literal port of CP's version --
see the previous section and the `mp3_alloc.c` header comment for why it
uses `gc_free` rather than a direct `m_free(ptr)` call (mainline's `m_free`
needs an explicit size on this workspace's unix port, which `mp3_free`'s
callers never have in scope).

## Tier 5 audiomp3 verified against the oracle

`MP3Decoder` oracle-diffed byte-for-byte against `bin/circuitpython` using
`cmods/mp3/examples/test.mp3` (Adafruit's own bundled fixture, ID3v2.3,
MPEG1 Layer III, 40 kbps CBR, 44.1 kHz stereo, ~12s): full-track decode via
`reset_buffer`/`get_buffer` (checksum + byte count identical), `rms_level`
and `samples_decoded` at multiple points, construction from a filename
string vs. an already-open binary stream vs. a caller-supplied pre-allocated
buffer (all three produce identical PCM), the `file` property's getter and
setter, explicit `open()`, the deinit guard, and error paths (`TypeError`
for a text-mode file, `RuntimeError("Failed to parse MP3 file")` for
non-MP3 data). One behavior was deliberately NOT "fixed" because it isn't
broken: calling `reset_buffer` again after a full decode to EOF and
decoding a second time produces a *different* total byte count than the
first pass (1048320 bytes first pass vs. 1078272 second, on the test
fixture) -- confirmed byte-for-byte identical on both interpreters,
including down to the exact discrepancy, so this is a genuine,
faithfully-reproduced characteristic of the real decoder/ID3-skip
interaction, not a port bug.

## Phase 8d: WASM build fixes

Rebuilding `micropython.mjs`/`.wasm` (the depth-1 `USER_C_MODULES` glob picks
up `audioif` automatically once built; it just hadn't been
rebuilt since the usermod landed) surfaced a batch of portability bugs,
none reachable on unix or windows before now:

- **`cmods/mp3/src/mp3dec.h`** picks its fixed-point/asm path from a closed
  list of `(__GNUC__, arch)` combinations, `#error`ing on anything else --
  with an explicit `MP3DEC_GENERIC` escape hatch for exactly this case.
  wasm32 matches none of the listed architectures. Fixed in
  `micropython.mk`: `-DMP3DEC_GENERIC` added, but only when building for
  the `webassembly` port specifically (detected the same way
  `cmods/wasmbridge/micropython.mk` detects it: `$(findstring
  /ports/webassembly,$(abspath $(CURDIR)))`) -- unix and windows both
  already match a named `__GNUC__`/arch branch and must keep using it, not
  silently fall back to the generic path.
- **`src/synthio/__init__.h`'s `synthio_synth_t`, and
  `src/synthio/Note.h`'s `synthio_bend_mode_t`** were each declared with
  two `typedef`s of the same name -- a forward declaration plus the real
  definition, exactly mirroring how CircuitPython spells the same thing
  across its separate `shared-bindings`/`shared-module` header pair. Two
  `typedef`s of an identical type are legal under GNU extensions/C11 (and
  never even co-occur in one CP translation unit, since CP never merges
  those two headers), but a hard error under emscripten's strict `-std=c99
  -Werror`, which this port's merged-into-one-file convention exposes for
  the first time. Fixed by dropping the second (redundant) `typedef` in
  each case -- the type is already complete by then either way.
- **`src/synthio/Biquad.c`** used `M_PI`, a glibc/mingw `<math.h>`
  extension, not ISO C99 -- present transitively on unix/windows, absent
  under emscripten's stricter libc. Fixed with a local `#ifndef M_PI
  #define M_PI ... #endif` guard.
- **`src/audiomixer/Mixer.c`'s `copy8lsb`/`copy8msb`** are genuinely dead
  code -- confirmed by reading CircuitPython's own `Mixer.c` directly, which
  defines the identical pair, also unused (only `copy16lsb`/`copy16msb` are
  called; these look like a leftover from a since-removed 8-bit-native
  mixdown path). Not a port bug, but unix/windows's compilers apparently
  don't enable `-Wunused-function` as an error here while emscripten's
  `-Wall -Werror` does. Fixed with `__attribute__((unused))` rather than
  deleting faithfully-ported (if currently unreachable) code.
- **`src/audiomp3/MP3Decoder.c`** needed an explicit `#include <errno.h>`
  for the bare `EINVAL` it uses (matching upstream, which also uses it
  bare rather than `MP_EINVAL`) -- glibc and mingw-w64 expose it
  transitively through `<sys/types.h>`/`<unistd.h>` already; emscripten's
  libc does not. Also needed an explicit `(mp_float_t)` cast on
  `common_hal_audiomp3_mp3file_get_rms_level(self)`'s `float` return value
  before `mp_obj_new_float()` (which takes `mp_float_t`, `double` on every
  build in this workspace) -- the implicit widening is fine under GCC's
  default warning set but trips `-Wdouble-promotion -Werror` under clang.

Full DSP parity suite (all of tiers 0-5, plus `synthtools_acceptance.py`)
re-run against the rebuilt wasm interpreter via a headless Node driver
(`loadMicroPython()` from `micropython.mjs`, since there is no
`micropython`-style CLI binary for this port) and diffed against
`bin/circuitpython`: byte-for-byte identical on every script except two
environment-only gaps, neither a DSP bug --
`parity_mp3decoder.py`/`parity_mp3decoder2.py` need a real file
(`mp3/examples/test.mp3`) on disk, which this ad hoc Node harness never
staged into wasm's virtual filesystem (already separately verified on
unix/windows against the same oracle); and `parity_multitapdelay.py`'s
error-path case shows a differently-formatted traceback (`PythonError:
Traceback ...` from the JS loader wrapping the exception, vs. the
interpreter's own native traceback text) -- the same category of
REPL/host-layer artifact as the CRLF-vs-LF difference documented for tier 4,
not a module bug. `synthtools_acceptance.py` (phase 7) also does not run
byte-for-byte under this harness: it computes its vendor path from
`__file__`, and `mp.runPythonAsync(source_string)` (this Node driver, since
there is no wasm-equivalent of a `micropython script.py` CLI invocation)
executes the script as a REPL-style source string with no `__file__`
bound, unlike the other three interpreters invoked with a real path
argument. Not a DSP issue -- every DSP-only script above ran and diffed
cleanly through the same harness -- just a limitation of this one ad hoc
test driver, left as a documented gap rather than built out further this
phase.

## Distortion soft_clip: verbatim-kept union type-pun turned out to be architecture-dependent (phase 8d)

Tier 4's original decision (see above) kept upstream's `args[ARG_soft_clip]
.u_obj` type-pun (reading an `mp_arg_val_t` union through the wrong member)
verbatim, on the grounds that it reproduced the oracle's output
byte-for-byte -- true, but only ever checked on x86-64 (this port's
unix/windows targets and CP's own unix `coverage` oracle, all the same
architecture and calling convention). Running the same parity script
(`parity_distortion.py`) against the newly-rebuilt wasm32 interpreter
(phase 8d) exposed the actual bug: constructing `Distortion()` with no
`soft_clip` argument at all (default `False`) reported `soft_clip == True`
on the wasm build, because the union-punned read happened to interpret
`args[ARG_soft_clip].u_obj`'s *default* value (a boxed `mp_obj_t`, not a
real bool) as truthy there, where x86-64's specific pointer-truncation
behavior for that same default value happened to read as falsy.

Fixed to `args[ARG_soft_clip].u_bool` (see `src/audiofilters/Distortion.c`)
rather than kept verbatim a second time, for two reasons: it is
unambiguously what upstream's own C function signature (`bool soft_clip`)
intends, and every *real* CircuitPython board is 32-bit ARM, not x86-64 --
so the byte-exact-on-unix result was already the architecture-unrepresentative
case, not evidence the quirk was safe to standardize on. Verified after the
fix: `soft_clip` now reads correctly (matching caller intent) and produces
*identical* checksums across all three of this port's targets (unix,
windows, wasm) for the same script -- a stronger three-architecture
consistency check than the tier 4 verification had access to at the time.
This is now a deliberate, documented divergence from the x86-64 CP oracle
for this one field (the oracle still exhibits the original bug); the
`memset(word_buffer, 32768, ...)` truncation quirk noted alongside it in
tier 4 was re-checked and is *not* similarly architecture-dependent (`memset`
truncating its fill value to `unsigned char` is guaranteed by the C standard
everywhere), so it remains kept verbatim.

## Tier 5 audiomp3 on CMake/mcu ports: mp3dec.h's platform list, and a QSTR-extraction blind spot (phase 10)

Wiring tier 5 into `micropython.cmake` (deferred at phase 8e, closed at
phase 10 -- see docs/porting-plan.md) surfaced two separate issues, one
upstream (Adafruit_MP3/Helix, vendored as `cmods/mp3`) and one in mainline
MicroPython's own CMake glue (`py/mkrules.cmake`, `py/py.cmake`).

**`mp3dec.h`'s closed `(__GNUC__, arch)` platform list has no Xtensa
branch, not just no RISC-V branch.** The phase 8e writeup (building the
ESP32-P4) only identified RISC-V as the gap, since that was the one board
being built at the time. Actually wiring tier 5 for CMake ports generally
showed the real shape of the problem: the list covers `ARM`, `__ARMEL__`,
`__i386__`, `__amd64__`, `__AVR32_UC__`, and a couple of named
microcontrollers -- Xtensa (esp32/esp32s2/esp32s3, not just the RISC-V
esp32 variants) was never covered either, matching wasm32 for the same
reason: it's just not `-D`efined into the pinned Helix decoder's platform
list. So `-DMP3DEC_GENERIC` is needed for every esp32 target this
workspace builds, Xtensa and RISC-V alike; only rp2 (RP2040/RP2350, ARM
Cortex-M, `__GNUC__ && __ARMEL__`) matches natively. Gated in
`audioif/micropython.cmake` on ESP-IDF's own
`CONFIG_IDF_TARGET_ARCH_RISCV`/`CONFIG_IDF_TARGET_ARCH_XTENSA` sdkconfig
variables (the same ones `esp32_common.cmake` branches on for its own
`MICROPY_CROSS_FLAGS` selection), not a bespoke detection mechanism.

**QSTR extraction on ESP-IDF CMake builds does not see INTERFACE-library
compile definitions the way the real compile does.** Setting
`target_compile_definitions(usermod_mpaudio INTERFACE MP3DEC_GENERIC)`
alone was *not* sufficient, even though the real per-object compile picked
it up correctly (confirmed present in `build.ninja`'s `DEFINES` for every
mp3 `.o`). MicroPython's own `py/mkrules.cmake` runs a separate
QSTR-extraction preprocessing pass (`makeqstrdefs.py pp ... -E ...`,
producing `qstr.i.last`) that builds its own flag list from a raw
`get_target_property(${MICROPY_TARGET} COMPILE_DEFINITIONS)` call --
which, per ordinary CMake semantics, returns only that target's own
directly-set definitions, not ones contributed transitively by a linked
`INTERFACE` library several links down the chain
(`usermod_mpaudio` → `usermod` → `MICROPY_TARGET`). That pass still fully
preprocesses every source (it needs real macro expansion to find `MP_QSTR_`
tokens), so it hit `mp3dec.h`'s `#error No platform defined` directly,
independent of whether the actual object compile would have succeeded.
Confirmed by diffing the qstr pass's actual `gcc -E ...` invocation
against the real compile rule for the same file: `-DMP3DEC_GENERIC` present
in the latter's `DEFINES`, absent from the former's flags entirely.

MicroPython's own `py/py.cmake` already has a helper for exactly this
class of problem -- `micropy_gather_target_properties(targ)`, which reads
`INTERFACE_COMPILE_DEFINITIONS` for `INTERFACE_LIBRARY`-typed targets and
folds them into `MICROPY_CPP_DEF_EXTRA` (the same accumulator
`mkrules.cmake` appends into `MICROPY_CPP_DEF` before building
`MICROPY_CPP_FLAGS`). But `esp32_common.cmake` only calls it in a loop over
`__COMPONENT_NAMES_RESOLVED` -- registered ESP-IDF components -- and
`usermod`/`usermod_mpaudio` are plain CMake targets created inside the
*main* component's own CMakeLists.txt, not components in their own right,
so that loop never reaches them. This is a real, if narrow, gap in
mainline MicroPython's ESP-IDF CMake glue, not anything specific to this
usermod -- any usermod defining `INTERFACE`-scoped compile definitions
needed for QSTR-sensitive preprocessing on ESP-IDF would hit the same
blind spot.

Fixed on our side, without touching mainline files: append
`MP3DEC_GENERIC` directly to `MICROPY_CPP_DEF_EXTRA` from
`audioif/micropython.cmake` when the arch check fires. This
works because `usermod.cmake` (and our aggregator beneath it) is
`include()`d into the port's CMakeLists, not `add_subdirectory()`d -- plain
(non-cache) CMake variables set here are visible later when
`mkrules.cmake` reads `MICROPY_CPP_DEF_EXTRA`, in the same directory scope,
regardless of the gather-loop's component-only reach. Verified end to end
by rebuilding both mcu data points from a clean build directory: ESP32-P4
(`MP3DEC_GENERIC` branch) and RPI_PICO (native-ARM branch, exercising the
"don't need the define, don't break anything" path) both built clean with
tier 5 now included -- see docs/porting-plan.md phase 10 for the exact
before/after firmware sizes.

## `RawSample` verified against the oracle directly (tier 1, for calibration)

Unlike `WaveFile`, `audiocore.RawSample` needed no adaptation and diffs
byte-for-byte against `bin/circuitpython` (10.2.1) for construction,
`sample_rate`/`bits_per_sample`/`channel_count` properties (get and set),
the deinit guard, the context-manager protocol, and rendered PCM via
`get_buffer`/`reset_buffer`. This is the calibration case: when a tier's
oracle diff matches this cleanly, the port is source-faithful, not just
"looks right."

## The oscillator wraps its accumulator one sample late, and reads off the end of the waveform (instruments tier)

Upstream's DDS loop (`shared-module/synthio/__init__.c`, and the ring
modulator beside it) advances a fixed-point accumulator and wraps it with

```c
if (accum > lim) { accum = accum - lim + offset; }
int16_t idx = accum >> SYNTHIO_FREQUENCY_SHIFT;
out_buffer32[i] = waveform[idx];
```

`lim` is `waveform_end << SHIFT`, and `waveform_end` is an exclusive bound --
the samples a note may read are `[waveform_start, waveform_end)`. Wrapping on
`>` rather than `>=` lets the accumulator sit *exactly* on `lim`, so that
iteration indexes `waveform[waveform_end]`: one past the loop, and for the
common case of a note looping an entire table, one past the end of the buffer
itself. The read is out of bounds, and what it returns is whatever the
allocator happened to leave after the array.

This is not a rare edge. Any note whose `dds_rate` is an exact multiple of the
sample step lands on the boundary on a schedule -- the noise tables the drum
machines play at `sample_rate / 8192` advance exactly one sample per frame and
hit it every 8192 frames, and each voice hits it at its own offset. The
practical consequence is that a render is not reproducible: the same script,
same events, same interpreter produced different PCM depending on how the heap
happened to be laid out. Confirmed directly on CPython -- rendering one TR-909
sequence gave different output under `PYTHONMALLOC=default`, `malloc`, and
`debug`, and changed again if unrelated objects were allocated beforehand.

Fixed here (`audioif_oscillator_fill()` in `src/shared/audioif_synth_dsp.c`,
shared by the MicroPython usermod and the CPython extension, plus the
MicroPython ring-modulator loop in `src/synthio/__init__.c`) by wrapping on
`>=` and subtracting the loop span, and by reducing an out-of-range incoming
accumulator into `[offset, limit)` rather than into `[0, limit) + offset`.

Kept upstream's structure otherwise; this is a correctness fix, not a
behavioral redesign. It is a deliberate divergence from the oracle only where
the oracle's behavior is undefined: every committed parity fixture
(`verify_effects`, `verify_streaming`, `verify_acceptance`, and the CPython API
tests) still matches its recorded hash after the change, because those
fixtures' waveforms and rates never land on the boundary. Where the boundary
*is* hit, there is no oracle value to be faithful to -- upstream is reading
memory it does not own.

Note for anyone diffing instruments against `bin/circuitpython`: the oracle
build still has this bug, so CircuitPython's own renders of boundary-hitting
material remain sensitive to its heap layout. Instrument parity runs treat
CircuitPython as advisory for that reason; CPython and MicroPython (both of
which take the fix) are the enforced targets.

## `audiodynamics` and `audioroute`: not CircuitPython ports at all (dsp-nodes tier)

Every other module here is CircuitPython's, moved. These two are not: they come
from micropython-vst3's `vstaudio` usermod (`usermods/vstaudio/vstaudio_dsp.c`),
where its effects library's compressors, limiters, gates, de-essers and
parallel branches were built. CircuitPython has no equivalent and never had
one, so there is no oracle in `cmods/circuitpython` to diff against and nothing
in this section is an upstream deviation. What it records instead is where the
port differs from *its* original.

The DSP itself is unchanged, `float` working precision included -- doubles
would be a better filter and a different one. It lives in
`src/shared/audioif_dynamics.c` and `src/shared/audioif_splitter.c`, so the
MicroPython usermod, the CPython extension and the CircuitPython spike all run
the same arithmetic; the per-runtime code is only the loop that pulls the
source. `tests/parity/verify_dsp.py` holds all three to what the original
rendered, byte for byte, by compiling `vstaudio_dsp.c` itself -- unmodified,
straight out of the sibling checkout -- into a throwaway interpreter
(`tests/parity/build_vstaudio_oracle.sh`). The usermod that publishes those
types cannot be imported directly: it is the plugin sidecar, and it wants a
shared memory mapping that a VST host created.

Two deliberate changes:

- **`Splitter(source, taps=n)` accepts the tap count as a keyword.** The
  original was positional-only, which reads badly at the effects library's call
  sites.
- **A tap holds a real object reference to its Splitter**, not the raw C
  pointer the original stored. Handing a tap to a `Mixer` and dropping every
  other name for the Splitter is the ordinary case, not an unusual one, and the
  collector has to be able to see that the 32 KB ring is still in use.

Quirks kept on purpose, because the effects library is written around them:

- Neither node ever reports `GET_BUFFER_DONE`. A starved chain gets silence.
  Both sit in the middle of a live graph, which is still running.
- `Dynamics` hands out at most 256 frames per call, and carries leftover source
  frames across output blocks.
- `Dynamics.reset_buffer` drops the detector envelopes but keeps the sidechain
  filter's memory and the last reported gain reduction.
- An `attack_ms` so long that its coefficient rounds to zero silently gets the
  10 ms default instead. This is why `audioif_dynamics_config_finish()` is a
  separate call rather than part of the initial state.
- Writing past a laggard tap's cursor drags that cursor forward and drops what
  it never collected; the branch skips ahead rather than stalling the graph.
- `SplitterTap.reset_buffer` does nothing. The cursors belong to the Splitter,
  and the other branches are still reading against them.

Neither node has `deinit`/`__enter__`/`__exit__`, unlike the ported
CircuitPython effects around them. The originals had no lifecycle, and giving
one to three implementations to keep in step buys nothing the collector does
not already do.

## `audiocore.get_buffer` returns a byte view (CircuitPython patch)

The one place `apply_cp_patches.sh` changes code CircuitPython already had,
rather than adding to it. Upstream returns a `memoryview` typed by the sample's
width, so `len()` counts samples while the C protocol's `buffer_length` counts
bytes -- every byte calculation downstream is then wrong by the sample width, a
silent 2x for ordinary 16-bit audio. This port's own `audiocore.get_buffer`
returns a byte view (audioif 413d87a), and the parity probes compare `len()`
and slices across all three interpreters, so the oracle has to agree.

The rewrite lives in `src/circuitpython_spike/apply_replacements.py` with the
upstream text it replaces. It is idempotent, and it fails loudly rather than
quietly if neither its marker nor the original text is present -- that means
the file moved upstream and a person should re-read it.
