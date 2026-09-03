# audioinstruments

Fifty-three classic synthesizers, electromechanical keyboards and drum
machines, each a self-contained `synthio` program. No samples: every voice is
oscillators, envelopes and filters, so the whole library is a few hundred
kilobytes of Python and runs anywhere audioif does.

## Installation

CPython 3.10+ installs from TestPyPI:

```sh
python -m pip install --index-url https://test.pypi.org/simple/ pydevices-audioinstruments
```

This pulls in `pydevices-audioif` automatically — see the
[audioif README](../../README.md#installation) for what that distribution
provides.

On MicroPython, `audioinstruments` arrives by `mip` from
`<repo>/lib/audioinstruments`, like the rest of PyDevices' Python tiers. It
can also be frozen into firmware with `AUDIOIF_FREEZE_LIBS=1` — about
236 KB of bytecode — see `manifest.py`; `mip` stays the default so a frozen
copy can't shadow a newer installed one.

## Quick start

```python
import audioinstruments

inst = audioinstruments.create("tr808", 48000)
inst.note_on(36)                 # bass drum, full velocity
inst.set_macro(2, 96)            # BD Tune
audio_out.play(inst.output)
```

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

## The instrument API

This package follows audioif's audio component metadata manifest. Every
instrument module explicitly declares `NAME`, `MACRO_LABELS`,
`MACRO_MODES`, and `PATCHES`; percussion modules also declare `NOTE_MAP`.
The complete provider rules are in `docs/audio-components.md`.

A module is one instrument and exposes
`create(sample_rate, channel_count=2, transport=None)`;
`audioinstruments.create(name, sample_rate, channel_count=2, transport=None,
**options)` is the lookup helper for hosts (extra keyword options pass
through to the module's `create`). Either returns an `Instrument`
implementing the audio component API — `docs/audio-component-api.md` is the
authority; this table is the summary:

| Method | |
|---|---|
| `note_on(pitch, velocity=127, detune=0.0, channel=0, note_id=-1, sample_position=0)` | `detune` offsets the pitch in semitones; velocity 0 releases, as on the wire |
| `note_off(pitch, channel=0, note_id=-1, sample_position=0)` | releases the matching `(channel, note_id)`, or `(channel, pitch)` when no note id was supplied |
| `all_notes_off()` | releases everything still held |
| `set_macro(index, value, channel=0, note_id=-1, sample_position=0)` | value 0-127, int or float |
| `get_macro(index)` | the current value, possibly fractional |
| `program_change(index, channel=0, note_id=-1, sample_position=0)` | applies a known patch; an unknown index is safely ignored |
| `pitch_bend(value, channel=0, sample_position=0)` | unsigned `0..16383`, center `8192` |
| `control_change(controller, value, channel=0, sample_position=0)` | controller and value `0..127` |
| `channel_pressure(value, channel=0, sample_position=0)` / `poly_pressure(pitch, value, channel=0, note_id=-1, sample_position=0)` | delivered to the few instruments that read aftertouch; safe no-ops elsewhere |
| `reset()` | releases all notes, clears state, restores patch 0 |
| `deinit()` | idempotent; any other use afterward raises `RuntimeError` |

`output` is the chain tail to hand to a mixer or an output device; `synth` is
the underlying `synthio.Synthesizer` for anything the wrapper does not cover.
The read-only properties `sample_rate`, `channel_count`, `latency_samples`,
`tail_samples`, `capabilities`, and `patch_index` round out the component
surface.

Everything is MIDI 0-127, because that is what a keyboard, a sequencer and a
saved patch all speak. Floats are accepted wherever an int is: an automation
lane with more than 7 bits of resolution keeps it, since the value is divided
by 127.0 rather than quantized. See `midi_cc.py` for the same split drawn
across the whole MIDI 1.0 controller table.

## What each module exports

| | |
|---|---|
| `MACRO_LABELS` | tuple of zero to sixteen macro names |
| `MACRO_MODES` | index to `UNIPOLAR`, `BIPOLAR`, or `TOGGLE` |
| `PATCHES` | `{index: (name, (values, 0-127))}`; patch 0 is what a fresh instrument plays |
| `NOTE_MAP` | percussion only: `((midi_note, label), ...)` for the voices it maps |
| `create(sample_rate, channel_count=2, transport=None)` | |

`transport` is an optional callable returning the host's playback position
as `(playing, seconds, bpm, ts_numerator, ts_denominator)`. Every
instrument accepts and stores it, but none reads it yet — no shipped
instrument is tempo-synced (see the shipped-status note in
`docs/audio-component-api.md`).

`audioinstruments.ALL`, `DRUM_MACHINES` and `MELODIC` list the modules;
`load(name)` imports one without instantiating it.

## Drum machines

- **`cr78`** - Roland CR-78 CompuRhythm. 14 voices, 16 macros.
- **`dmx`** - Oberheim DMX. 13 voices, 16 macros.
- **`drumtraks`** - Sequential Circuits Drumtraks. 7 voices, 8 macros.
- **`linndrum`** - Linn LinnDrum. 16 voices, 16 macros.
- **`simmons_sdsv`** - Simmons SDS-V. 8 voices, 16 macros.
- **`sp1200`** - E-mu SP-1200. 4 voices, 8 macros.
- **`tr606`** - Roland TR-606 Drumatix. 7 voices, 16 macros.
- **`tr707`** - Roland TR-707 Rhythm Composer. 8 voices, 8 macros.
- **`tr808`** - Roland TR-808 Rhythm Composer. 12 voices, 16 macros.
- **`tr909`** - Roland TR-909 Rhythm Composer. 11 voices, 16 macros.

Each maps its voices to the note numbers the hardware used, so a pattern
written for one machine plays on another wherever the voices line up. Notes a
machine does not map are answered by its own fallback, or by silence - both
deliberate, and both pinned by the parity tests.

## Synthesizers and keyboards

- **`andromeda`** - Alesis Andromeda A6. 16 macros.
- **`arp2600`** - ARP 2600. 16 macros.
- **`b3`** - Hammond B-3 tonewheel organ. 11 macros.
- **`clavinet`** - Hohner Clavinet D6. 11 macros.
- **`cp70`** - Yamaha CP-70 electric grand. 9 macros.
- **`cs80`** - Yamaha CS-80. 16 macros.
- **`cz101`** - Casio CZ-101 phase distortion synthesizer. 12 macros.
- **`d50`** - Roland D-50 linear synthesizer. 12 macros.
- **`dx7`** - Yamaha DX7. 16 macros.
- **`emulator2`** - E-mu Emulator II. 11 macros.
- **`fairlight`** - Fairlight CMI. 10 macros.
- **`farfisa`** - Farfisa Compact combo organ. 10 macros.
- **`fs1r`** - Yamaha FS1R formant synthesizer. 11 macros.
- **`jp8000`** - Roland JP-8000. 16 macros.
- **`juno106`** - Roland Juno-106. 16 macros.
- **`jupiter8`** - Roland Jupiter-8. 16 macros.
- **`k2600`** - Kurzweil K2600. 16 macros.
- **`karplus`** - Plucked string, Karplus-Strong style. 7 macros.
- **`mellotron`** - Mellotron M400. 8 macros.
- **`microwave`** - Waldorf Microwave. 12 macros.
- **`minimoog`** - Moog Minimoog Model D. 16 macros, 3 patches.
- **`ms20`** - Korg MS-20. 16 macros.
- **`ms2000`** - Korg MS2000. 12 macros.
- **`music_easel`** - Buchla Music Easel. 10 macros.
- **`nord_lead`** - Clavia Nord Lead. 16 macros.
- **`obxa`** - Oberheim OB-Xa. 11 macros.
- **`odyssey`** - ARP Odyssey. 16 macros.
- **`pianet`** - Hohner Pianet. 10 macros.
- **`polysix`** - Korg Polysix. 11 macros.
- **`ppg_wave`** - PPG Wave 2.2. 12 macros.
- **`prophet5`** - Sequential Circuits Prophet-5. 16 macros.
- **`prophet_vs`** - Sequential Circuits Prophet VS vector synthesizer. 16 macros.
- **`rhodes`** - Fender Rhodes electric piano. 13 macros.
- **`sh101`** - Roland SH-101. 8 macros.
- **`solina`** - ARP/Eminent Solina String Ensemble. 9 macros.
- **`taurus`** - Moog Taurus bass pedals. 12 macros.
- **`tb303`** - Roland TB-303 Bass Line. 9 macros.
- **`virus`** - Access Virus. 12 macros.
- **`vl1`** - Yamaha VL1 physical modelling synthesizer. 10 macros.
- **`vox_continental`** - Vox Continental combo organ. 9 macros.
- **`vp330`** - Roland VP-330 Vocoder Plus. 12 macros.
- **`wasp`** - EDP Wasp. 10 macros.
- **`wurlitzer`** - Wurlitzer 200A electric piano. 10 macros.

## Where these came from

They were written for micropython-vst3, where each was a script bound to that
plug-in's host module. Moving them here made them host-neutral; the parity
harness (`tests/parity/run_instruments_parity.py`) renders every original
script and holds the ported module to it byte for byte, on each interpreter
separately.
