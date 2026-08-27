# audioif

CircuitPython's audio system for MicroPython and CPython — `audiocore`,
`audiomixer`, `synthio` (including `MidiTrack`), the effects modules
(`audiofilters`, `audiodelays`, `audiofreeverb`, `audiospeed`), `audiomp3`,
and CircuitPython `play()`/`stop()`/`pause()`/`resume()` output semantics.
Import names stay `audiocore`/`synthio`/etc., matching CircuitPython for
source compatibility.

Three things here are not CircuitPython's. `audiodynamics` (compression,
limiting, expansion, gating, transient shaping) and `audioroute` (fan one
stream out to parallel branches) come from micropython-vst3's audio engine,
which had them and CircuitPython does not; `audiomath` (multiply one stream by
another — ring and amplitude modulation) has no ancestor anywhere and is
audioif's own. `apply_cp_patches.sh` adds all three to a CircuitPython tree
too. And `lib/audioinstruments/` is a pure-Python library of
53 classic synthesizers, keyboards and drum machines built entirely out of
`synthio` — no samples — with a MIDI-shaped API:

```python
import audioinstruments
inst = audioinstruments.create("tr808", 48000)
inst.note_on(36)                 # bass drum, full velocity
inst.set_macro(2, 96)            # BD Tune, on the 0-127 scale
audio_out.play(inst.output)
```

Two more pure-Python tiers sit on top of it. `lib/audioeffects/` is 40 effect
classes — compressors, delays, reverbs, EQ, modulation, pitch — each taking a
source and exposing its chain tail as `.output`. `lib/audiorender/` renders a
whole composition offline: tracks, tempo map, notes and automation in, a mixed
stereo master and a level report out. Each has its own README.

`audiorender` is the one part of this repository written for a desktop rather
than a board — numpy throughout, a whole song in memory — so it ships in the
wheel and is never frozen into firmware.

MicroPython consumes this repository as `USER_C_MODULES`. CPython 3.10+
installs the separately versioned native distribution from TestPyPI:

```sh
python -m pip install --index-url https://test.pypi.org/simple/ pydevices-audioif
```

The CPython distribution contains `audiocore`, `synthio`, `audiomixer`,
`audiofilters`, `audiodelays`, `audiofreeverb`, `audiospeed`, `audiodynamics`,
`audioroute`, `audiomath`, and the `audioinstruments`, `audioeffects` and
`audiorender` packages. `audiomp3` remains
firmware-only. The distribution has no runtime dependencies and does not
publish an `audioif` import; its version is the `VERSION` file, which is also
what `_audioif.__version__` reports.

**MicroPython status:** all module tiers ported and oracle-diffed byte-for-byte against
`bin/circuitpython` on unix; DSP parity re-verified on windows and wasm;
built and measured on two real mcu targets, ESP32-P4 (hardware-confirmed
by ear) and RP2040 (build-only). See
[docs/porting-plan.md](docs/porting-plan.md) for the full phased history
and [docs/upstream-diff.md](docs/upstream-diff.md) for every deliberate
deviation from upstream CircuitPython.

**CPython status:** the public surface and wheel plumbing are present, and the
committed synthesis, mixer, MIDI, streaming, and effects fixtures match
CircuitPython 10.2.1 PCM byte-for-byte. Import/API smoke success is not used as
a substitute for those oracle comparisons.

`ulab` and `cmods/mp3` (the vendored Adafruit_MP3/Helix decoder `audiomp3`
depends on, RPSL/RCSL-licensed — not MIT, carried unmodified per upstream's
own terms) are consumed as cloned sibling dependencies, same pattern as
`pygraphics`/`displayif`, not vendored into this repo.

The playback-facing pull protocol (`audiocore.get_buffer`/`reset_buffer`)
is consumed by `pydevices`' `lib/audiodev` package
(`AudioOut` in `sample_out.py`), which pumps any audiosample into any of
`audiodev`'s existing push-PCM transports (sdl2/win/wasm/i2s/emulated) —
see that package's own docs for the playback-side contract this repo's
protocol implementation is built to satisfy.

Acceptance target: todbot's
[`synthtools`](https://github.com/todbot/CircuitPython_SynthTools) running
unmodified, with rendered PCM diffed against `bin/circuitpython`'s own
unix coverage build (which already contains the entire DSP stack — the
parity oracle for this whole port).

See [docs/porting-plan.md](docs/porting-plan.md) for the architecture,
module tiers, phased plan, and testing strategy.
