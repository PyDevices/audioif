# audioif

CircuitPython's audio system for MicroPython and CPython — `audiocore`,
`audiomixer`, `synthio` (including `MidiTrack`), the effects modules
(`audiofilters`, `audiodelays`, `audiofreeverb`, `audiospeed`), `audiomp3`,
and CircuitPython `play()`/`stop()`/`pause()`/`resume()` output semantics.
Import names stay `audiocore`/`synthio`/etc., matching CircuitPython for
source compatibility.

## Installation

**MicroPython** consumes this repository as `USER_C_MODULES`. For a Make port
that is fully standalone — no other repository is required. For a CMake port
(esp32, rp2), point `USER_C_MODULES` straight at this checkout; note that
`micropython.cmake` currently locates `ulab` only as a sibling checkout (or
via an aggregator that globs one), not from `.deps/` — so on CMake ports
`synthtools`' `import ulab.numpy` needs `../ulab` beside this repo until
[#18](https://github.com/PyDevices/audioif/issues/18) closes:

```sh
idf.py build -DUSER_C_MODULES=<path to audioif>
```

For a Make port (unix, windows, webassembly), MicroPython's own build glob
looks one level down, so point `USER_C_MODULES` at this checkout's
*parent* directory instead:

```sh
git clone https://github.com/PyDevices/audioif ~/build/audioif
cd ~/build/audioif && ./scripts/fetch_deps.sh
git clone https://github.com/micropython/micropython ~/build/micropython
cd ~/build/micropython/mpy-cross && make
cd ~/build/micropython/ports/unix && make submodules
make USER_C_MODULES=~/build
```

`./scripts/fetch_deps.sh` fetches the two pinned native dependencies —
`ulab` (so `synthtools`'s `import ulab.numpy` works) and `mp3` (the
`audiomp3` tier's decoder) — into `.deps/`, pinned by
[DEPENDENCIES.lock](DEPENDENCIES.lock). To build without them, skip the
fetch and pass `AUDIOIF_OPTIONAL_DEPS=1` to the **build** step instead
(`make USER_C_MODULES=~/build AUDIOIF_OPTIONAL_DEPS=1`); the variable is
read by `micropython.mk`/`micropython.cmake`, not by `fetch_deps.sh`, and
it builds every module except `audiomp3` with no clone beyond this
repository. See [docs/porting-plan.md](docs/porting-plan.md)
for the architecture, module tiers, phased plan, and testing strategy.

**CPython 3.10+** installs from TestPyPI:

```sh
python -m pip install --index-url https://test.pypi.org/simple/ pydevices-audioif
```

This gets you `audiocore`, `synthio`, `audiomixer`, `audiofilters`,
`audiodelays`, `audiofreeverb`, `audiospeed`, `audiodynamics`, `audioroute`,
`audiomath`, `audioecho`, `audioconvolve`, and the `audiorender` package.
`audiomp3` remains firmware-only. The distribution has no runtime
dependencies and does not itself publish an `audioif` import; its version is
the `VERSION` file, which is also what `_audioif.__version__` reports.

The instrument and effect libraries — `audioinstruments` (53 synthesizers,
keyboards and drum machines) and `audioeffects` (46 effect classes, racks
included) — are not part of this distribution. They live in the
[audiocomponents](https://github.com/PyDevices/audiocomponents) repository
as their own packages, each depending on `pydevices-audioif`; see that
repository for how to install them.

## What's here

One pure-Python tier sits on top of the CircuitPython-compatible core:

- **`lib/audiorender/`** — renders a whole composition offline: tracks,
  tempo map, notes and automation in, a mixed stereo master and a level
  report out. This is the one part of the repository written for a desktop
  rather than a board — numpy throughout, a whole song in memory — so it
  ships in the wheel and is never frozen into firmware. It has its own
  README.

The instrument and effect libraries that used to sit beside it —
`audioinstruments` and `audioeffects` — now live in the
[audiocomponents](https://github.com/PyDevices/audiocomponents) repository,
together with the audio component contract they implement: the metadata
manifest
([docs/audio-components.md](https://github.com/PyDevices/audiocomponents/blob/main/docs/audio-components.md))
and the runtime API
([docs/audio-component-api.md](https://github.com/PyDevices/audiocomponents/blob/main/docs/audio-component-api.md)).
`audiorender` drives any component that speaks that API and does not need
those packages installed.

## Additions beyond CircuitPython

Five things here are not CircuitPython's. `audiodynamics` (compression,
limiting, expansion, gating, transient shaping) and `audioroute` (fan one
stream out to parallel branches) come from micropython-vst3's audio engine,
which had them and CircuitPython does not. `audiomath` (multiply one stream
by another — ring and amplitude modulation), `audioecho` (a delay with a
filter, a soft-clip and a cross-feed inside its feedback loop) and
`audioconvolve` (apply a measured or synthesized impulse response, by
partitioned FFT) have no ancestor anywhere and are audioif's own.
`apply_cp_patches.sh` adds all five to a CircuitPython tree too.

## Status

**MicroPython:** all module tiers ported and oracle-diffed byte-for-byte
against `bin/circuitpython` on unix; DSP parity re-verified on windows and
wasm; built and measured on two real mcu targets, ESP32-P4
(hardware-confirmed by ear) and RP2040 (build-only). See
[docs/porting-plan.md](docs/porting-plan.md) for the full phased history
and [docs/upstream-diff.md](docs/upstream-diff.md) for every deliberate
deviation from upstream CircuitPython.

**CPython:** the public surface and wheel plumbing are present, and the
committed synthesis, mixer, MIDI, streaming, and effects fixtures match
CircuitPython 10.2.1 PCM byte-for-byte. Import/API smoke success is not used
as a substitute for those oracle comparisons.

`ulab` and `mp3` (the vendored Adafruit_MP3/Helix decoder `audiomp3`
depends on, RPSL/RCSL-licensed — not MIT, carried unmodified per upstream's
own terms) are consumed as cloned sibling dependencies in the parent
workspace, same pattern as `pygraphics`/`displayif`, not vendored into this
repo.

The playback-facing pull protocol (`audiocore.get_buffer`/`reset_buffer`)
is consumed by `pydevices`' `lib/audiodev` package (`AudioOut` in
`sample_out.py`), which pumps any audiosample into any of `audiodev`'s
existing push-PCM transports (sdl2/win/wasm/i2s/emulated) — see that
package's own docs for the playback-side contract this repo's protocol
implementation is built to satisfy.

Acceptance target: todbot's
[`synthtools`](https://github.com/todbot/CircuitPython_SynthTools) running
unmodified, with rendered PCM diffed against `bin/circuitpython`'s own unix
coverage build (which already contains the entire DSP stack — the parity
oracle for this whole port).

## Sound stability

The API is our contract with you: class names, signatures, metadata, and
macro surfaces stay stable and change only deliberately. The *sound* is
not part of that contract. These components sound great, but they are not
all as accurate as they could be, and implementations will keep being
refined as the library matures — so a component may render audibly
differently from one release to the next. If a composition depends on the
exact sound of a release, pin that release rather than tracking the
latest; the code of every release stays available for exactly this
reason.

Beneath the components sits a harder guarantee: the audioif core — the
CircuitPython-compatible `synthio`/`audiocore`/effects-module layer — is
held bit-exact to CircuitPython itself, verified by parity gates, and
that never changes release to release. Where we find CircuitPython and
audioif disagree, we treat it as a bug and report it upstream. The
components are where the sound evolves; the floor they stand on does
not.
