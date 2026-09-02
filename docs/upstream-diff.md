# Deltas from upstream CircuitPython

Running log of every place this port's behavior deliberately differs from
CircuitPython's, or needed a workspace-side fix that isn't a plain port.
Goal: keep this list short. Python-level API and behavior match CP unless
noted here.

Six of the entries below are upstream bugs rather than divergences, written up
in [upstream-reports/](upstream-reports/). **Five have been filed with
CircuitPython and four are merged** (see that directory's README for the
issue and PR numbers): peaking-eq-sign, dds-oscillator-off-by-one,
distortion-soft-clip-union and biquad-reset are fixed upstream;
biquad-band-edges remains open, awaiting maintainer appetite on a
three-option ask. **The numbers here were measured on this port and are not
upstream's** -- the reports carry figures measured on a build of upstream
`main`, which differ.

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
**Sharper than the phase-8d writeup, found 2026-08-27 while drafting the
upstream report**: this is not wasm-only, and "no unix impact" was too kind.
The default reads correctly everywhere because `mp_arg_parse_all()` copies the
*whole* union for a defaulted argument, and the static `{.u_bool = false}` is
zero-filled. A **supplied** argument only has its one `bool` byte written into
an uninitialised stack union, so `.u_obj` is a pointer made of one meaningful
byte and seven stale ones. On this port's own x86-64 oracle build,
`Distortion(soft_clip=False)` reads back **`True`** -- the one case a user
would reach for to get the hard curve is the one case that cannot be right
except by luck. Drafted:
`docs/upstream-reports/distortion-soft-clip-union.md`.

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

Drafted for upstream: `docs/upstream-reports/dds-oscillator-off-by-one.md`,
with a repro that keeps the errant read *inside* the buffer (a loop end short
of the buffer end) so it is deterministic. Still present on `main` 2026-08-27,
at four sites.

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

## `audiomath`: audioif's own, with no ancestor anywhere (phase 9)

`audiodynamics` and `audioroute` above are at least *someone's* code moved.
`audiomath` is not: nothing in CircuitPython and nothing in
micropython-vst3's engine multiplies one audio stream by another, so there is
no oracle to diff against and this section records a new module rather than a
deviation.

`Multiply(source, modulator, mix=1.0)` writes `source * modulator`, blended
back against the untouched source by `mix`. That is ring modulation, and with
a modulator that does not cross zero it is amplitude modulation. The palette
could not do either:

- **`synthio` rings a *note*** against an oscillator. It reaches synthesized
  notes and nothing else -- not a microphone, not a sample, not the output of
  another effect.
- **An LFO-driven parameter updates once per block**, about 187 Hz at 48 kHz.
  `audioeffects.Tremolo` is exactly this effect inside that ceiling; a ring
  modulator wants hundreds of hertz and a carrier of a few kilohertz.

The arithmetic is `shared/audioif_multiply.c`, Q15 and stateless: the product
is `(a * b) >> 15`, blended `(dry * a + wet * product) >> 15`, clamped. The
two negative rails are the one product that lands outside `int16`, which is
what the clamp is for; `tests/parity/multiply_probe.py` drives it there
deliberately rather than assuming.

**The two inputs fail in opposite directions, on purpose.** A source that runs
dry gives silence, the way every other node in the palette does. A modulator
that is absent, or has stopped, lets the signal through **untouched** --
`audioif_multiply_passthrough_s16()`. This is the one place where "no input"
and "an input of zero" must not mean the same thing: a missing modulator that
muted the signal would make every dropout a hard gate.

A modulator is normally a short looping table, and looping is free here rather
than a feature: `audiocore.RawSample` returns `GET_BUFFER_DONE` with its whole
buffer every time it is asked, so pulling one repeatedly *is* the loop. The
carrier `audioeffects.RingMod` builds therefore holds a whole number of cycles
(`modulation.py`, `_carrier`), because a partial one would step the phase once
per table and buzz at the table rate.

`verify_dsp.py` covers it, but differently from its two neighbours: with no
oracle, the golden is captured from the port under CPython and what it proves
is cross-interpreter agreement and no accidental drift, not fidelity to
something older. All three interpreters render it identically.

### `apply_cp_patches.sh` could not add a module to a tree it had already
### patched

Found while landing this one, and worth recording because it failed quietly.
`insert_block_after` skipped any file whose `audioif-cp begin` marker was
already there, so extending a block -- which is exactly what adding a module
does -- reached a fresh CircuitPython tree and no other. `CIRCUITPY_AUDIOMATH`
never landed, and the build then failed a long way from the cause. It now
rewrites the contents between the markers when they differ, and reports
`current` / `updated` / `patched` so the three cases are distinguishable.

## `audioecho`: a delay with a filter inside its feedback loop (phase 10)

`audiodelays.Echo` exists upstream, and its feedback path is `echo * decay`
and nothing else. Everything a delay is actually *named* after falls out of
what happens in that path, so without it there is one delay with a level
knob:

- **Tape.** Every pass through a tape machine loses top and bottom and
  softens. Filtering the delay's output once, after the fact, is not the same
  thing: it darkens the first repeat exactly as much as the tenth.
- **Analog / BBD.** The same, further. A bucket-brigade line is band-limited
  by construction and its clock drifts.
- **Ping-pong.** Repeats alternating between the speakers needs each
  channel's output fed into the *other* channel's line. Two delays panned
  hard apart, which is all the palette could do, gives repeats on both sides
  at once.

`audioecho.FeedbackDelay` puts a one-pole low-pass (`damping_hz`), a one-pole
high-pass (`cut_hz`), a cubic soft-clip (`loop_drive`), a per-sample delay
modulation (`wow_hz`/`wow_depth_ms`) and a cross-feed (`cross_feed`,
`input_pan`) in the loop. `shared/audioif_feedback_delay.c`, `float` working
precision to match `audioif_dynamics.c`.

**A new module rather than arguments on `Echo`, deliberately.** An argument
added to audioif's copy of a CircuitPython module would not exist on a stock
board, so a `TapeDelay` written against it would silently be a different
effect there -- the exact failure `apply_cp_patches.sh` exists to avoid. A
new module either installs whole or is absent and says so on import.

Two details worth recording:

- **The wow oscillator is a magic-circle resonator**, two states rotated by a
  constant each frame, not `sinf()`. Per-sample modulation is the point (an
  LFO-driven `delay_ms` updates once per block, about 187 Hz at 48 kHz, so it
  steps rather than glides and there is no doppler), and a library call per
  sample would not be affordable on the parts this has to run on.
- **`reset_buffer` really does drop everything**, unlike `audiodynamics`,
  which keeps its sidechain filter and last gain. A delay's whole state is
  audible: a chain restarted with the old repeats still in the line plays the
  previous take over the new one.

Verified by `tests/parity/feedback_delay_probe.py` through `verify_dsp.py`,
with no oracle -- the golden is captured from the port. That is a weaker
claim than the `audiodynamics` fixtures make, but a stricter cross-interpreter
one than anything else in the suite: the loop is recursive and runs in
`float`, so a one-ulp disagreement between two builds would be fed back and
amplified rather than staying one ulp. All three render it identically.

### `audioeffects.TapeDelay` was low-passing the dry signal

Found while rebuilding it, and it had been there since the class was written.
The tone filter sat *after* the delay node, and the delay node had already
blended dry with wet -- so the filter darkened the untouched signal along
with the repeats. At the class's own defaults, and worse at the low mixes the
soundtrack uses:

| tone through `TapeDelay(mix=0.14, tone_hz=3800)` | before | after |
|---|---|---|
| 1 kHz | -0.02 dB | -1.30 dB |
| 4.3 kHz | -4.28 dB | -1.30 dB |
| 10 kHz | **-19.26 dB** | -1.31 dB |
| 16 kHz | **-33.33 dB** | -1.31 dB |

("after" is the mix attenuation, flat across the band, which is what a delay
at 14% wet should cost.) Three racks in the soundtrack used it, so their
renders move -- that is the fix arriving, not a regression.

## `audiodynamics` gains lookahead and true-peak detection (phase 11)

Additive, and both default off, so a `Dynamics` built the way the original was
*is* the original -- `tests/parity/dynamics_probe.py`'s hash is unchanged
across this phase, which is the check that says so. The new paths get their
own fixture (`dynamics_extras_probe.py`) rather than joining that one, because
that one is held against `vstaudio_dsp.c` compiled unmodified and may only use
forms the original accepts.

- **`lookahead_ms`** holds the audio back while the detector reads ahead of
  it, so the gain is already down when the transient arrives rather than a
  fraction of a millisecond after it. Without it, brickwall limiting always
  overshoots the first cycle of every attack. Capped at 50 ms: it is latency
  the whole chain pays, and past a few milliseconds a limiter stops sounding
  like a limiter and starts sounding like it is ducking before the note.
- **`true_peak`** adds the level *between* samples to what the detector sees,
  by four-point half-band interpolation of the midpoint. A signal can pass
  through the ceiling between one sample and the next with no sample over it,
  and a converter downstream reproduces that peak; sample-peak limiting cannot
  see it at all. This is an estimate, not ITU-R BS.1770 true-peak metering,
  which oversamples by four -- it is the cheapest version worth having.

**The lookahead buffer is allocated by the bindings, not the DSP**, and only
when someone asks for one. 50 ms of stereo is 9.6 KB and `audioeffects` builds
nine `Dynamics` instances, so an unconditional buffer would cost 86 KB for a
feature almost nothing uses. `audioif_dynamics_lookahead_frames()` tells a
binding how much to hand over; the DSP uses whatever it has, so a binding that
allocates nothing gets no lookahead rather than reading off the end of one.

One deliberate difference from the node's documented reset behaviour: the
sidechain filter's memory and the last reported gain reduction still survive
`reset_buffer`, but **what is in the lookahead buffer does not**. That is
audio in flight, and a chain restarted with the previous take still queued
would play it.

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

## Resetting a Mixer silenced it, permanently (audioeffects tier)

`audiomixer.Mixer`'s `reset_buffer` stops every voice upstream:

```c
for (uint8_t i = 0; i < self->voice_count; i++) {
    common_hal_audiomixer_mixervoice_stop(self->voice[i]);   // sample = NULL
}
```

Every other source in the stack treats `reset_buffer` as "rewind to the
beginning". This one drops what was playing and never picks it up again, so a
Mixer that has been reset renders zeros for the rest of its life.

That is not a corner case, because *pulling from a source resets it first*.
`Filter.play(sample)`, `Echo.play(sample)`, every effect's `play()` and every
output's, all call `reset_buffer` on what they were handed. So

```python
mixer.voice[0].play(source)
effect.play(mixer)          # <- silences the mixer here
```

renders silence, and always has. It went unnoticed because a Mixer is normally
the last node before the output, and because `MixerVoice.play()` re-primes the
voice, so a voice started *after* the reset works fine — which is how every
example is written.

Found while moving micropython-vst3's effects library into `audioeffects`:
`ParametricEQ` sums its boost branches in a Mixer and then chains the cut
sections after it, so any curve with both a boost and a cut was silent.
Confirmed against `bin/circuitpython` directly — the oracle does the same
thing.

Fixed here by rewinding instead of stopping: a new
`common_hal_audiomixer_mixervoice_reset()` (`src/audiomixer/MixerVoice.c`,
and `MixerVoice.reset()` in `audiomixer.py`) does exactly what
`MixerVoice.play()` already does — reset the sample, re-prime the voice's
buffer — for each voice that is still playing. A stopped voice stays stopped.
Every committed parity fixture still matches its recorded hash, because none
of them reset a Mixer with voices playing.

**Not applied to the CircuitPython target.** `apply_cp_patches.sh` only adds
modules; the one CircuitPython source it rewrites is `audiocore.get_buffer`'s
return type, which the parity harness needs to compare like with like. Fixing
DSP inside the oracle would erase the divergence this file exists to record.
The consequence is real and worth stating: on CircuitPython, an effect chained
directly after a Mixer is still silent. Anything in `audioeffects` that ends in
a Mixer — `MultibandCompressor`, `Harmonizer`, `Octaver`, `StereoWidener`,
`DynamicEQ`, `PingPongDelay`, `Exciter` — can be the last node in a chain
there, but not the middle of one. (`ParametricEQ` was on that list until the
peaking-EQ fix below let it drop the Mixer entirely.)

## Peaking EQ computed `b2` with the wrong sign (effects-extension tier)

`audioif_biquad_configure_w0()` builds a peaking bell (mode 4) from the RBJ
cookbook. Upstream computes

```c
b0 = 1 + alpha * A; b1 = -2 * cos; b2 = 1 + alpha * A;
a0 = 1 + alpha / A; a1 = -2 * cos; a2 = 1 - alpha / A;
```

`b2` is `1 - alpha * A`. The sign is not cosmetic: it is what makes numerator
and denominator sum to the same value at DC and again at Nyquist, which is the
entire premise of a peaking filter — unity everywhere except the band around
`f0`. With the plus, the numerator picks up `2 * alpha * A` at DC that the
denominator does not, and since `1 - cos(W0)` is very small at low
frequencies, that term dominates. The DC gain becomes
`1 + alpha * A / (1 - cos(W0))`, so a +6 dB bell at 1 kHz with Q of 1 at
48 kHz arrives as roughly **+21 dB at DC**, and it worsens as `f0` drops. It is
not a bell with a blemish; it is a bass shelf with a bell buried in it.

Measured through the built extension after the fix, a +6 dB bell at 1200 Hz
(Q 1, 8 kHz) reads +6.00 dB at center and 0.00 dB at DC and Nyquist, and a
−6 dB cut reads −6.000 dB. Before it, DC read +21.42 dB.

This is upstream's bug, not a porting error: CircuitPython 10.2.1 carries the
identical lines at `shared-module/synthio/Biquad.c:157-159`. It survived
because `PEAKING_EQ` is the one mode a synthesis library rarely reaches for —
nothing in this repository, in `audioeffects`, or in micropython-vst3's
instruments or soundtrack used it. `audioeffects.ParametricEQ` worked around
it by synthesizing bells out of notch and band-pass sections instead — cuts
as notches blended to depth through the Filter's `mix`, boosts as band-passed
Splitter branches summed back over the dry signal through a Mixer, which is
why it was capped at three boosts (a Splitter has four taps). All of that is
now one Biquad per band in a single Filter cascade.

**Deviation**: fixed here, so `PEAKING_EQ` diverges from `bin/circuitpython`.
Nothing else moves — no existing fixture reached mode 4, which is also why
`tests/parity/biquad_component_probe.py` now walks all seven modes.

Still present in upstream `main` as of 2026-08-27, not just in the pinned
10.2.1, so this one is worth reporting rather than waiting out. Drafted:
`docs/upstream-reports/peaking-eq-sign.md`.

## A stereo `Filter` shared one biquad state between the channels (effects-extension tier)

A biquad is a recursion: each output sample is computed from the two input and
two output samples before it. Upstream's `audiofilters.Filter` allocates one
`biquad_filter_state` per cascade stage and runs it across the whole
*interleaved* buffer, so when it processes a left sample, the "two samples
before it" are the previous right sample and the previous left one.

Two consequences, both measured:

- **Every frequency lands an octave high.** The recursion advances twice per
  stereo frame, so the filter effectively runs at double the rate its
  coefficients were computed for. A bell asked for 1200 Hz peaked near
  2400 Hz. `audioeffects` compensated for this with a `SPECTRAL_SCALE = 0.5`
  factor applied to every frequency before handing it to a Biquad.
- **The channels are not independent.** With left fed 2400 Hz, the left output
  measured +3.63 dB when the right carried 300 Hz and +4.89 dB when the right
  carried 2400 Hz — the left channel's level moved 1.26 dB because of a change
  the right channel made. Identical input in both channels came out 3.3 dB
  apart at 3 kHz. No scale factor can correct this one.

**This one is a catch-up, not a divergence.** Upstream fixed it after 10.2.1:
current `main` allocates through `audiofilters_assign_filter_chain(..., channel_count)`
and indexes `filter.states[j * channel_count + k]` against a per-channel
`filter_buffer + k * SYNTHIO_MAX_DUR`. Our CP tree is pinned at 10.2.1
(`bcfcb51`), which still has the single interleaved state, so the port
inherited it. The fix here was arrived at independently and lands on the same
design, which is reassuring about both. **When the CP pin moves past that
commit this entry stops describing a difference at all** — at which point
prefer upstream's exact shape (one `SYNTHIO_MAX_DUR * channel_count` buffer
deinterleaved in a single pass) over ours (one `SYNTHIO_MAX_DUR` buffer reused
per channel) so the files converge and future pin bumps stay clean.

**Change**: one state per stage *per channel*, indexed
`[stage * channels + channel]`, with the buffer deinterleaved per channel and
chunked in whole frames so the channels stay in lockstep across chunk
boundaries. `filter_states_len` still counts stages, so callers are unchanged.
Fixed in both implementations — the usermod (`src/audiofilters/Filter.c`) and
the CPython extension (`BiquadState.process_s16` in `src/cpython/_audioif.c`,
which gained a `channels` argument). The two agree byte-for-byte.

After the fix the same bell peaks at 1200 Hz where it was asked to, both
channels read identically for identical input, and the left channel's level is
unchanged by the right channel's content. Mono and stereo now agree exactly;
`SPECTRAL_SCALE` and `_core.filter_hz()` are gone from `audioeffects`.

**Not affected**: synthio's per-note filters. `synthio_synth_synthesize()`
filters a *mono* `tmp_buffer32` with a per-note state and only then expands to
stereo (`src/synthio/__init__.c`), so every instrument renders identically
before and after. The blast radius was the `audiofilters.Filter` sites in
`audioeffects`.

Stereo `Filter` had no fixture anywhere in this repository before this change —
its only two uses in the suite pass `channel_count=1` — which is how both of
these survived. `tests/parity/biquad_component_probe.py` covers mono and stereo
across all seven modes, and its golden is captured from this port rather than
from CircuitPython, because of the two deviations above.

### What the two fixes changed in `audioeffects`

`SPECTRAL_SCALE` and `_core.filter_hz()` are deleted along with their thirteen
call sites, so a frequency handed to any class in the library is now the
frequency it filters at. `_core.check_hz()` replaces them: halving everything
kept the library clear of Nyquist by accident, and a biquad configured above
Nyquist folds its coefficients and produces noise silently, so the library now
refuses instead. `GraphicEQ` drops ISO bands that a low configured rate puts
out of range — the 16 kHz band needs better than 32 kHz to exist.

`ParametricEQ` is one Biquad per band in one Filter cascade, bells and shelves
alike; it no longer builds a Splitter or a Mixer, no longer caps boosts at
three, and exposes the sections as `.biquads` for parameter binding. An EQ with
every band flat returns its source untouched rather than a chain of unity
sections. `GraphicEQ` inherits all of it. `DynamicEQ` keeps its topology but is
no longer an approximation: RBJ's notch and 0 dB-peak band-pass share a
denominator and their numerators sum to it, so with the compressor idle the
split reconstructs the input — measured flat to 0.03 dB from 100 Hz to 8 kHz,
where before the shared biquad state leaked each channel's band into the
other's notch.

Measured after the sweep at 48 kHz: a +6 dB / Q 2 bell at 1 kHz reads +5.98 dB
at 1 kHz and ±0.1 dB two octaves out either way; a −9 dB / Q 1.4 cut at 500 Hz
reads −9.05 dB; `LowPass` at 1 kHz reads −3.00 dB at cutoff and −12.33 dB an
octave above. `tests/test_cpython_effects_library.py` pins the bell placement,
the flat-EQ passthrough, and the Nyquist refusal.

## The biquads were Q15, so they could not go low (third approved deviation)

Found while looking for somewhere to put a tape head bump, recorded as a
limitation, and then fixed one phase later once the user approved a third
deviation from the oracle. The section keeps its original measurements as the
"before" column, because the failure was silent and worth being able to
recognise again.

### What was wrong

`audioif_biquad_configure_w0()` stored its five coefficients as Q15 integers
(`AUDIOIF_BIQUAD_SHIFT = 15`, `scale()` rounding `value * 32768` to an
`int32_t`), and `audioif_biquad_process()` accumulated the five products in
`int32_t`. Both came straight from CircuitPython's
`shared-module/synthio/Biquad.c`, and both are defensible on a
microcontroller. The cost is that low-frequency sections are unrepresentable:
as `W0` goes to zero a low-pass's `b0 = (1 - cos W0) / 2` goes with it, and at
100 Hz / 48 kHz it is `4.3e-5`, which is 1.4 in Q15 and rounds to 1. Meanwhile
`a1` approaches `-2` and its product with a full-scale sample approaches
`INT32_MAX` on its own, so the accumulator has nothing left for the other four
terms.

There was a **second, independent** cause, found while fixing the first and
approved with it. `fast_sincos()` fits one 5th-order polynomial to both sine
and cosine over `[0, pi/2]`, and it is wrong at both ends of the audio band
for two different reasons:

- Its cosine carries up to `2.3e-5` of absolute error over the quarter it is
  fitted to, and `5.4e-6` at the `W0` a 100 Hz corner uses. Every low-pass,
  notch and shelf coefficient is built from `1 - cos W0`, which at 100 Hz /
  48 kHz is `8.6e-5` -- so that error is 6 percent of the answer, 13 percent at
  50 Hz and 34 percent at 20 Hz. Widening the fixed-point format alone would
  have left a 1 dB error at 50 Hz.
- `pi/2` in `W0` is only 12 kHz at 48 kHz, and above that the fit is
  **extrapolating**. At 20 kHz its sine is off by 6.6 percent and `1 + cos W0`
  by 15 percent; at 22 kHz, by 31 and 128. This half had never been noticed at
  all: a `HIGH_PASS` at 22 kHz passed its entire stopband.

### What it measured, before and after

At 48 kHz, one biquad, Q 0.707 unless stated, against the double-precision
closed form:

| asked for | before | after | ideal |
|---|---|---|---|
| `LOW_PASS` 50 Hz, at cutoff | -- | −2.99 | −3.01 |
| `LOW_PASS` 100 Hz, at cutoff | **silence** | −3.02 | −3.01 |
| `LOW_PASS` 200 Hz, two octaves below | **+1.25** | −0.03 | −0.02 |
| `HIGH_PASS` 30 Hz, at cutoff | **+21.6** | −3.04 | −3.01 |
| `HIGH_PASS` 100 Hz, at cutoff | **+6.24** | −3.02 | −3.01 |
| `LOW_SHELF` 80 Hz / +1.5 dB, at 20 Hz | **+13.4** | +1.50 | +1.49 |
| `LOW_PASS` 20 kHz, at cutoff | −3.71 | −3.01 | −3.01 |
| `LOW_PASS` 22 kHz, at cutoff | **−7.29** | −3.01 | −3.01 |
| `HIGH_PASS` 22 kHz, at cutoff | **+0.06** | −3.01 | −3.01 |

Everything from 50 Hz to 22 kHz now lands within 0.03 dB of the closed form.
The old usable floor was about 300 Hz, and 400 Hz for anything under half a
decibel of error.

**That "before" column is this port's, not upstream's**, and the two do not
match: measured on a build of upstream `main`, a `LOW_PASS` at 100 Hz reads
-3.94 dB rather than silence and a `HIGH_PASS` at 30 Hz reads +9.03 rather
than +21.6. Same two causes, same conclusion, different arithmetic on the way
(this port had already moved to per-channel state and computes its
coefficients in `double`, where `mp_float_t` on a board is `float`). The
upstream numbers, and a repro that produces them, are in
`docs/upstream-reports/biquad-band-edges.md`. **Do not quote this table
upstream.**

### The fix

`src/shared/audioif_biquad.c`, three changes:

1. **Per-filter coefficient format instead of a fixed Q15.**
   `choose_shift()` takes the largest of the five normalised coefficients and
   gives them all as many fractional bits as that one has room for in an
   `int32_t`, capped at 30. A plain low-pass tops out near 2 (that is `a1`)
   and gets 29 bits; a 20 dB shelf reaches ~200 and gets 23. Fixing one
   format for every filter would mean giving them all the shelf's. The chosen
   shift travels with the coefficients, so `synthio_biquad_t` caches it
   alongside `a1..b2` -- they are meaningless apart.
2. **`int64_t` accumulator, and a feedback state with 12 fractional bits below
   the sample grid** (`AUDIOIF_BIQUAD_STATE_SHIFT`). The second half matters
   more than it looks: a biquad low down has both poles close to the unit
   circle, and `1/A(z)` -- the gain the loop applies to whatever error is fed
   back into it -- is 4000 at DC for a 100 Hz low-pass and 43000 for a 30 Hz
   high-pass. Rounding the feedback to whole samples, as upstream does, hands
   that gain half an LSB of error to amplify.
3. **`fast_sincos()` replaced by `sine_and_cosine()`**: reflect into
   `[0, pi/2]` (`sin(pi - t) = sin t`, `cos(pi - t) = -cos t`) and evaluate
   the two Taylor series properly, seven terms each. Worst error across
   20 Hz -- 24 kHz falls from `5.4e-6` to `6.3e-9`, and it stays accurate past
   Nyquist, so a frequency asked for above Nyquist is now merely wrong rather
   than absurd. Deliberately **not** libm: glibc, newlib and MicroPython's own
   `sin`/`cos` differ in the last place, and `verify_dsp`'s one-hash-covers-
   every-interpreter rule depends on this being the same function everywhere.

### What it cost

Measured by cross-compiling `audioif_biquad.c` at `-Os` and counting
`audioif_biquad_process()`:

| core | before | after | note |
|---|---|---|---|
| Cortex-M4 / M7 | 37 instructions | 76 | no library calls -- `SMULL`/`SMLAL` |
| Cortex-M0+ | 55 instructions | 154 | 5 `__aeabi_lmul` + 1 `__aeabi_lasr` |

So roughly 2x on anything with a long multiply, and closer to 4x on
Cortex-M0+, which has none -- one stereo biquad at 22050 Hz goes from about
5 percent of a 48 MHz M0+ to about 17. That is the trade upstream made when it
chose Q15, and it is a real one on an RP2040. It is accepted here rather than
made conditional: a filter that sounds different on a Pico than on an ESP32-S3
would be worse than either. If it ever needs clawing back, the products are
32x32 into 64 and could be hand-written for M0 rather than going through
`__aeabi_lmul`.

### Consequences inside `audioeffects`

- `GraphicEQ`'s bottom three ISO bands were wrong. Asked for +6 dB and
  measured at its own center, the 31.5 Hz band gave **+12.14 dB**, 63 Hz
  +6.96, 125 Hz +3.07. All ten bands now read **+6.01 dB or better**.
- `MultibandCompressor`'s default `low_hz=200.0` crossover mis-split, leaving
  a **+5.2 dB** bump below 100 Hz. That is gone -- and with the filters
  working it exposed a separate defect underneath, a **3.4 dB dip** at the
  crossover, because the low band cascaded two Butterworth low-passes against
  the mid band's single high-pass. Both sides are Linkwitz-Riley pairs now and
  the three bands recombine flat to 0.23 dB from 30 Hz to 8 kHz.

Worth noting on the timing: before the effects-extension tier,
`_core.filter_hz` halved every frequency on the way in, so *both* of those ran
an octave lower still -- `GraphicEQ`'s 63 Hz band was configured at 31.5 Hz,
and the multiband low band was a 100 Hz low-pass, i.e. silent. Removing that
workaround moved them up out of the worst of it by accident.

### What moved, and what did not

- `golden/biquad_component.json` re-captured. The probe gained `biquad_edge`,
  seven modes across four centers from 60 Hz to 3600 Hz at an 8 kHz rate, so
  both ends are pinned by a fixture for the first time. Every one of the 28
  mode/center pairs moved.
- `golden/synthtools_acceptance.json` re-captured, and **it is no longer a
  byte-for-byte CircuitPython match** -- the first fixture in the suite to
  lose that. Three checksums moved: lead +0.020 percent, bend +0.24, bass
  **+1.50**. The bass is the tell: it is a Q 6.0 low-pass sweeping downward
  from 300 Hz at 22050 Hz, which is precisely the case that could not be
  represented before. `verify_acceptance.py` now keeps the oracle's own
  answer beside the port's under `circuitpython_stdout` rather than
  discarding it.
- All four `golden/instruments_*.json` re-captured, all 93 instruments. Every
  one of them builds a `synthio.Biquad`, so every one moved -- but both sides
  of that comparison run through the same engine, so the property the fixture
  exists to prove is untouched: **186 comparisons, 0 failures** after
  re-capture.
- **Not** `verify_dsp`, `verify_effects` or `verify_streaming`: no filter in
  any of their probes.
- Stock CircuitPython does not get this. `apply_cp_patches.sh` only *adds*
  modules to a CP tree; `synthio` and `audiofilters` there are upstream's, so
  a CP board still cannot filter below a few hundred hertz. See the effects
  README, "A note on filters off a stock CircuitPython board".

## `Distortion` ignores `drive` in OVERDRIVE mode (upstream, worked around)

`shared-module/audiofilters/Distortion.c` never reads `drive` in the
`DISTORTION_MODE_OVERDRIVE` branch -- the curve is a fixed shape. CLIP and
WAVESHAPE both use it, and the `drive` docstring says it is "the amount of
distortion" without noting the exception, so the argument looks connected and
is not. Measured: `drive` 0.0 / 0.2 / 0.5 / 0.9 in OVERDRIVE render byte-
identical output, while the same four in WAVESHAPE differ.

Still present on `main` 2026-08-27. Drafted for upstream as "wire it up or
document it": `docs/upstream-reports/distortion-overdrive-drive.md`. It may
well be intentional, which is why the draft asks rather than patches.

**Not fixed in the C here either.** `audioeffects` works around it instead --
`drive.py`'s `_push()` maps a 0..1 drive knob onto `pre_gain`, which is the
only way into that curve, with the level put back so the historical default
stays bit-identical. See phase 8 in the plan, and the `drive.py` docstring.

## A biquad reset cleared half its state (fifth approved deviation)

Found while preparing the upstream drafts. `synthio_biquad_filter_reset()`
does

```c
memset(&st->x, 0, 4 * sizeof(int16_t));
```

and `biquad_filter_state` is `int32_t x[2], y[2]` -- sixteen bytes, of which
that clears eight. `x[0]` and `x[1]` go; **`y[0]` and `y[1]` keep the previous
output history**, which is the filter's feedback memory. The `int16_t` looks
like a leftover from a time when the state was 16-bit.

Measured through `audiofilters.Filter`: fill the filter with a 200 Hz tone at
30000, call `reset_buffer`, then feed pure silence, and the first block comes
back with a peak of **28072** -- a clean exponential decay of the audio that
was supposed to have been cleared, at -1.3 dBFS. Both callers mean a full
reset (`audiofilters_filter_reset_buffer`, and `synthio.Note` when a note's
filter is initialised).

The fix is one line (`memset(st, 0, sizeof(*st))`), and it was verified here
by applying it to this port's `audioif_biquad_reset()` and re-running that
measurement: 28072 -> 0.

**Fixed here** -- the fifth approved deviation, taken 2026-08-27 --
and reported upstream as `docs/upstream-reports/biquad-reset.md`.

**Nothing moved.** Every golden held without re-capture: `verify_biquad`,
`verify_effects`, `verify_streaming`, `verify_acceptance`, `verify_dsp` on all
three interpreters, and all 93 instrument comparisons. That is worth
recording, because `synthio_note_start()` resets a note's filter on every
press and the obvious worry was that a re-pressed voice inheriting the
previous note's tail was baked into the fixtures. It was not: nowhere in the
suite does a biquad get reset with a non-zero `y`. So this deviation changes
what happens in the one case upstream leaves undefined and nothing else.

**Stock CircuitPython does not get it**, same as the other four:
`apply_cp_patches.sh` only *adds* modules, and `synthio`/`audiofilters` on a
CP board are upstream's. `bin/circuitpython` therefore still exhibits the bug,
which is correct -- it is the oracle.

Note that `common_hal_audiofilters_filter_play()` does *not* call
`audiofilters_filter_reset_buffer()`; it resets the source only. So a plain
`filter.play(other)` carrying filter memory over is by design, and is not this
bug.

## `audioconvolve`: audioif's own, and the one thing the palette could not fake (phase 12)

Nothing in CircuitPython transforms anything, and neither did
micropython-vst3's engine. `audioconvolve.Convolver` applies an impulse
response by uniform-partitioned overlap-save FFT convolution:
`shared/audioif_convolve.c` over `shared/audioif_fft.c`, `float` throughout.

**Why it is not a preset over the existing reverb.** `audiofreeverb` is a
fixed network of delay lines. It sounds like a room, and with the right
settings it sounds like a plausible room, but it cannot sound like a
*particular* one. Convolving with a plate's recorded impulse *is* that plate,
and the same node is then a hall, a guitar cabinet, a spring tank or a
telephone depending only on which impulse it was handed. That is a different
kind of thing from a preset, and it is the last entry on the catalogue that
the rest of the library genuinely could not approximate.

### The transform

`shared/audioif_fft.c` is a radix-2 Cooley-Tukey with a bit-reversal pass,
wrapped in the usual real-input packing: an N-point real transform runs on an
N/2-point complex one, so it costs half of what a naive complex transform of
the same block would. There is no split-radix and no hand-unrolled first
stage, because the honest bottleneck in a convolver is the pointwise multiply
across the partitions, not the two transforms either side of it.

Two decisions worth recording:

- **`float`, not `double`.** A double transform doubles the memory of every
  stored partition, and memory is what decides whether an impulse fits on a
  board at all. float32 gives ~7 digits and the transform's error grows as
  sqrt(log2 N), so a 512-point transform of int16 audio lands ~1e-3 out of a
  full-scale 32768 -- five orders of magnitude below the samples it is made
  of. Measured against numpy's `rfft`: 1.1e-7 relative at N=512.
- **The twiddles come from a series, not libm.** Same rule as the biquad's
  (see "The biquads are Q15" above): a golden hash of one probe has to match
  on CPython, MicroPython and CircuitPython, and three libms agree to within
  an ulp and differ in the last place. That is what
  `shared/audioif_trig.c` is for.

### `shared/audioif_trig.c` — extracted, not changed

The deterministic sine and cosine used to be `static` inside
`audioif_biquad.c`. The FFT needs the same guarantee for the same reason, so
they moved to a file of their own. **The biquad's arithmetic is unchanged**:
`audioif_sincos_reflect()` is the old function operation for operation,
reflecting about pi/2 only, and it is deliberately *not* "fixed" to
full-circle reduction -- a frequency above Nyquist would then get a different
wrong answer, and several goldens are pinned to this one. `audioif_sincos()`
is the new full-circle entry point, used only by the twiddle tables.
`verify_biquad`, `verify_effects`, `verify_acceptance` and all four
`instruments_*.json` were unchanged by the extraction, which is the check
that says so.

### Design decisions in the convolver

- **One partition of latency, accepted.** A block cannot be transformed until
  it is complete, so the output trails the input by 256 frames (5.3 ms at
  48 kHz). Removing that means a non-uniform partitioning scheme -- a few
  direct taps, then small partitions, then large -- which is roughly triple
  the code for a saving that matters only when monitoring a live player. A
  convolver with **no impulse loaded is a bypass with no latency at all**:
  an impulse that has not arrived is a missing setting, not a null room, and
  a chain built before its impulse arrives must not drift against its
  neighbours.
- **`mix` follows `audiofreeverb`, not `audiodelays`.** 0..1 with the dry at
  unity until halfway, rather than `Echo`'s 0..2. This is a reverb; matching
  the other reverb matters more than matching the delays.
- **The synthesized room is normalized to unit energy, in two passes.** A
  tail of unit-amplitude noise convolved with anything is enormous -- 48000
  taps near full scale sum to tens of thousands of times the input -- so an
  unnormalized synthetic room is not a quiet room, it is a clipped one. The
  partitions are transformed as they are generated and there is nowhere to
  keep the taps, so the deterministic generator simply runs twice: once to
  measure the energy, once to write it scaled. The second pass costs only the
  noise, not the transforms.
- **The noise is xorshift32 and the exponentials are a series**, for the
  determinism reason again. A room that is not bit-identical between builds
  is not a room, it is three rooms.
- **`reset_buffer` drops the history and keeps the impulse.** One is audio in
  flight; the other is a setting, and reloading a room because playback
  restarted would be both wrong and expensive.

### What it costs, which is the whole story on a board

Each partition holds 257 complex floats, about 2 KB, and there is one
frequency-delay line per audio channel plus one stored impulse per impulse
channel. So:

| impulse | partitions | memory | arithmetic |
|---|---|---|---|
| 1024 taps (21 ms) — a cabinet | 4 | ~25 KB | ~3 MFLOPS |
| 4096 taps (85 ms) | 16 | ~100 KB | ~12 MFLOPS |
| 1 second, stereo | 188 | ~1.5 MB | ~150 MFLOPS |

A cabinet is comfortable on a microcontroller. A second of stereo reverb is a
desktop or a render, or a board with PSRAM and nothing else to do. Both are
in `audioeffects`: `drive.CabinetSim` and `reverb.ConvolutionReverb`, and
each says so in its docstring.

### `audioeffects.CabinetSim` builds a filter's impulse, not a bell's

Worth recording because the first cut got it wrong. A cabinet's response was
modelled as a sum of damped sinusoids -- box resonance, presence peak, top
roll-off -- with decay times chosen by ear from the description. That gives
resonances of Q 17 and a peak gain of **818** at the box frequency: a bell,
not a box. Rebuilt as the impulse response of the filter cascade the
description actually names (a high-pass under the resonance, two peaking
bells, and two cascaded low-passes for the 24 dB/octave a cone rolls off at),
run over a unit impulse in float.

And the normalizer has to be the *response*, not the tallest tap: the cascade
sits several dB above unity at its bump, and a cabinet that multiplies
everything by four is a cabinet that clips. `_peak_response` sweeps the
cascade's magnitude at 48 log-spaced frequencies and normalizes by the
largest. Measured, `4x12 Stack`: +0 dB at 100 Hz, -3.9 at 1 kHz, -10.9 at
5 kHz, -27.0 at 8 kHz, -45.7 at 12 kHz.

Verified by `tests/parity/convolve_probe.py` through `verify_dsp.py`, with no
oracle -- the golden is captured from the port. It is the most
float-dependent fixture in the suite: every output sample is a sum of
hundreds of float products routed through two transforms. All three
interpreters render it identically, synthesized rooms included.

## Press semantics: two CPython-target divergences fixed (2026-09-01)

Issues #8 and #9, found by the accuracy program's fixed-circuit drum
rebuilds. The CPython target's `Synthesizer.press` deviated from
`synthio_span_change_note` three ways: it evicted the oldest note when
full (upstream refuses the new press), it evicted a bystander and leaked
a slot when a *member* was re-pressed at the cap, and it re-initialized
the envelope from zero on re-press where upstream re-enters ATTACK from
the current level with the oscillator phase intact. All three now mirror
the oracle and the re-press render is byte-identical with a built
CircuitPython (`tests/test_cpython_press_semantics.py` holds the
behaviors). MicroPython was already correct.

## Extension: `Note.filter` accepts a serial Biquad cascade (2026-09-01)

Issue #11, a deliberate extension beyond the oracle (like `audioecho`):
`Note.filter` also accepts a tuple/list of up to four `Biquad`s applied
in series, each stage with its own state — steeper slopes than one
biquad's 12 dB/oct can give a noise voice. A single filter behaves
exactly as stock CircuitPython, which never sees the extension: code
that must run on stock CP passes one Biquad (the usual portability
posture). MicroPython and CPython render cascades byte-identically;
per-note cost is one biquad pass per stage, and the resident state is
four biquad states per note on MicroPython (`SYNTHIO_NOTE_MAX_FILTER_STAGES`).

## Re-pressing a finished note drops it entirely (2026-09-02)

**Deviation from the oracle** (the sixth), and reported upstream.

Pressing a note that still holds its channel slot takes the fast path in
`synthio_span_change_note`, which sets `ATTACK` but deliberately leaves
`level` alone — correct while the note is still sounding, so it swells
back up from where it is and keeps its oscillator phase. But a note whose
envelope has already run down to 0 is *finished, merely not yet
collected*, and upstream treats it the same way: `ATTACK` with the level
left at 0. The reaper at the top of the render then tests `level == 0`
before anything steps the envelope, frees the slot and `continue`s, and
the envelope-advance loop skips freed slots — so the note is deleted
without ever being stepped. **The press renders byte-identical to never
having pressed at all.**

It is a one-block race: a block earlier the level is still above 0 and
the note re-attacks normally; a block later the slot has already been
reclaimed and the press takes the init path and works. Measured window,
sweeping the re-press block and reading the level at press time (oracle
and, before this fix, our MicroPython port):

| re-press at | level at press | note audible after |
|---|---|---|
| block 2 | 0.289 | yes |
| **block 3** | **0.000** | **no — silently dropped** |
| block 4+ | 0.000 (slot already reclaimed) | yes |

Musically this is a missed drum hit: every fixed-circuit instrument
presses several notes per circuit (a bass drum is body + noise click),
and a note-off followed by a re-strike onto the same circuit lands in
that window often enough to be heard.

**The fix, in both targets:** a re-press of a note whose level is 0 is a
*new hit*, not a swell — re-initialise its envelope and reset its phase,
exactly as a press on an already-reclaimed slot does. Applying the same
rule to both targets also makes the *timing* of slot collection
unobservable, which is why it does not matter that the C implementation
frees a slot as soon as the level reaches 0 while the CPython
reimplementation keeps a note until it is released: a silent note
contributes nothing either way, and the only thing that could depend on
whether its slot had been reclaimed was which press branch ran later.

`level == 0` is being used as a proxy for "finished", and during ATTACK it is
not one — the reaper's own comment says "note is truly finished", and a
note re-pressed one call earlier is not.

**Not closed by this:** the two targets are still not bit-identical on
full instrument sequences. That is a series of smaller lifecycle
differences between the C implementation and the Python reimplementation,
tracked separately; this entry covers only the dropped-note defect.
