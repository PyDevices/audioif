# audioif

CircuitPython's audio system, ported to MicroPython — `audiocore`,
`audiomixer`, `synthio` (including `MidiTrack`), the effects modules
(`audiofilters`, `audiodelays`, `audiofreeverb`, `audiospeed`), `audiomp3`,
and CircuitPython `play()`/`stop()`/`pause()`/`resume()` output semantics,
as `USER_C_MODULES` MicroPython usermods for the mcu, unix, and windows
ports. Import names stay `audiocore`/`synthio`/etc., matching CircuitPython,
for source compatibility.

**Status:** all module tiers ported and oracle-diffed byte-for-byte against
`bin/circuitpython` on unix; DSP parity re-verified on windows and wasm;
built and measured on two real mcu targets, ESP32-P4 (hardware-confirmed
by ear) and RP2040 (build-only). See
[docs/porting-plan.md](docs/porting-plan.md) for the full phased history
and [docs/upstream-diff.md](docs/upstream-diff.md) for every deliberate
deviation from upstream CircuitPython.

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
