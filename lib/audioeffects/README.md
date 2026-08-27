# audioeffects

Forty-three effect classes built out of audioif's audio nodes, for any host
that can pull an audiosample:

```python
import audioeffects
from audioeffects import Compressor, TapeDelay, Reverb

audioeffects.configure(48000)
comp = Compressor(source, threshold_db=-20, ratio=3, character="optical")
tape = TapeDelay(comp.output, time_ms=340, feedback=0.4, mix=0.25)
hall = Reverb(tape.output, preset="hall", mix=0.3)
audio_out.play(hall.output)
```

`configure()` sets the sample rate every effect built after it runs at. Call
it once, before building anything; a process only ever has one.

Every class takes its audio source as the first argument - a synthesizer, an
`audioinstruments` instrument's `output`, a host input, or another effect's
`.output` - and exposes its chain tail as `.output`. The underlying nodes are
kept as attributes (`.node`, `.mixer`, `.cutoff`, ...) so applications can
bind parameters straight to them; the classes with a natural swept control
also expose `set_*` helpers (`LadderFilter.set_cutoff`,
`DigitalDelay.set_time`, ...).

Five nodes make the deeper processors possible: `audiodynamics.Dynamics` (an
envelope-follower gain computer with sidechain filtering, lookahead and
true-peak detection), `audioroute.Splitter` (fans one stream out to parallel
branches that a Mixer then sums), `audiomath.Multiply` (one stream times
another, which is ring modulation), `audioecho.FeedbackDelay` (a delay with
a filter, a soft-clip and a cross-feed inside its loop) and
`audioconvolve.Convolver` (an impulse response applied by partitioned FFT).
None of the five is CircuitPython's; a stock board does not have them.

## Catalogue

### Dynamic range - `dynamics.py`
| Class | Notes |
|---|---|
| `Compressor` | `character="vca"/"fet"/"optical"/"varimu"` presets shape attack/release/knee; **patches** |
| `Limiter` | brickwall, with optional lookahead and true-peak detection; **patches** |
| `Expander` | downward: below threshold, quiet gets quieter |
| `NoiseGate` | mutes below threshold |
| `DeEsser` | detector high-passed at `frequency`, so only sibilance ducks the signal |
| `TransientShaper` | independent attack/sustain gain, level-independent |
| `MultibandCompressor` | 3 bands split/compressed/summed (Linkwitz-Riley crossovers: flat recombine) |

### Frequency and EQ - `eq.py`
| Class | Notes |
|---|---|
| `ParametricEQ` | peaking bands `(freq, gain_db, q)` plus optional shelves |
| `GraphicEQ` | ten fixed ISO bands |
| `DynamicEQ` | notch+band split, band compressed, summed (the split is exact) |
| `LowPass` `HighPass` `BandPass` `Notch` | single swept biquads |
| `LadderFilter` | Moog-style 4-stage cascade, 24 dB/oct, resonant |
| `CombFilter` | tuned short feedback delay |

### Time and space - `reverb.py`, `delay.py`
| Class | Notes |
|---|---|
| `Reverb` | presets `room` `chamber` `hall` `plate` `spring` (spring adds pre-flutter) |
| `ConvolutionReverb` | a real impulse response, measured or synthesized; **patches** |
| `DigitalDelay` `SlapbackDelay` | clean repeats |
| `TapeDelay` | in-loop low-pass, soft-clip and per-sample wow; **patches** |
| `AnalogDelay` | BBD: band-limited both ends, `age` over the lot; **patches** |
| `PingPongDelay` | true cross-feed - repeats alternate sides; **patches** |
| `MultiTapDelay` | `(position, level)` tap patterns |

The delays split two ways. `DigitalDelay`, `SlapbackDelay` and
`MultiTapDelay` are clean and run on `audiodelays`, whose feedback path is
the echo times a decay. The other three are named after something that
happens *inside* that path - a filter taking a little more off each pass, a
soft-clip rounding it, a cross-feed sending it to the other speaker - so they
run on `audioecho.FeedbackDelay`, which is where audioif puts those. A
coloured delay's `max_time_ms` sizes its line and cannot change afterwards;
at 48 kHz a second of stereo line is 192 KB, so ask for what will be used.

The two reverbs are not the same kind of thing. `Reverb` is `audiofreeverb`:
a fixed network of delay lines that costs the same on a Cortex-M0 as on a
workstation, and that sounds like a plausible room. `ConvolutionReverb` is
`audioconvolve`: it applies an actual impulse response, so it sounds like a
*particular* room - and one second of stereo impulse is about 1.5 MB and
~150 MFLOPS, which is a desktop or an offline render. Reach for `Reverb`
first. The microcontroller-scale use of convolution is a **short** impulse:
`CabinetSim` is 1024 taps and about 3 MFLOPS.

`ConvolutionReverb`'s `seconds` is an allocation, not a setting - it fixes how
long an impulse that instance can ever hold, because the storage is carved
once and the audio path may already be pulling. Its Decay macro then works
within that allocation, which is why it is a proportion rather than a time.
Both convolution classes trail their input by `audioconvolve.FRAMES` (5.3 ms
at 48 kHz) once an impulse is loaded, and by nothing at all before one is.

### Modulation - `modulation.py`
| Class | Notes |
|---|---|
| `Chorus` | multi-voice with LFO-animated delay |
| `Flanger` | short modulated delay with feedback and doppler - the real swept comb |
| `Phaser` | all-pass stages with swept center |
| `Tremolo` | amplitude LFO |
| `Vibrato` | pitch LFO through the pitch shifter |
| `AutoPan` | panning LFO |
| `Rotary` | vibrato + tremolo + auto-pan at a shared slow/fast speed |
| `RingMod` | audio-rate multiply against a sine carrier; **patches** |

### Drive - `drive.py`
| Class | Notes |
|---|---|
| `Overdrive` | soft clip with tone control; `drive` is pre-gain into a fixed curve |
| `Distortion` | hard clip |
| `Fuzz` | pre-gained into a square |
| `Saturation` | `character="tube"/"tape"/"console"`, mostly dry |
| `Bitcrusher` | bit-depth reduction, by `bits` (2..16) or `crush` |
| `Exciter` | overdriven high-passed branch blended under the dry |
| `CabinetSim` | speaker cabinet by convolution with a short designed impulse; **patches** |

The three saturation characters are different curves, not one curve with
presets. `tube` runs the engine's asymmetric OVERDRIVE, so it generates a
2nd harmonic level with the 3rd; `tape` and `console` run its
odd-symmetric WAVESHAPE, whose 2nd harmonic measures 66 dB lower - the
numerical floor. On top of that `tape` has the head bump and the gap loss
that come with the medium (+1.4 dB at 40 Hz, −2.9 dB at 16 kHz) while
`console` gains a little air on top and nothing at the bottom, and
`console` is the gentlest of the three by about 4 dB of THD. All three are
level-matched at 1 kHz to within 0.3 dB,
so auditioning one against another does not mean re-balancing. `amount`
scales the whole character, tone shaping included.

### Pitch and stereo - `pitch.py`
| Class | Notes |
|---|---|
| `PitchShifter` | time-independent shift |
| `Harmonizer` | dry + up to three fixed intervals |
| `Octaver` | one or two octaves either way; only the branches asked for are built |
| `StereoWidener` | Haas: short-delayed copy panned wide against the dry |

## Deliberately absent

- **Pitch correction** - needs pitch detection (YIN or autocorrelation), and
  that is off the roadmap for good rather than pending. `PitchShifter` will
  shift by an interval you name; nothing here works out what interval to ask
  for.
- **Sample-rate reduction** - the other half of a lo-fi box. The engine's
  LOFI mode masks low bits and nothing else; decimation needs a
  sample-and-hold that is not in the palette. `Bitcrusher` does the bit
  depth alone.
- LFO-driven parameters update at the block rate (~187 Hz at 48 kHz),
  plenty for sweep rates but not audio-rate modulation. `RingMod` is the
  exception and does not use an LFO at all - see below.

## A note on how low a filter can go

Anywhere in the band, is the short answer - but it is worth knowing that
this was not always true, because the failure was silent and you may still
meet it on a stock CircuitPython board (below).

Every biquad in the engine used to keep its coefficients as Q15 integers,
which is the right trade on a microcontroller and costs low frequencies.
Below about 300 Hz they quantized into something that was no longer the
filter you asked for: a `LowPass` at 100 Hz returned **silence**, a
`HighPass` at 30 Hz returned **+21 dB of noise**, and a low shelf at 80 Hz
lifted the whole band by 13.4 dB instead of its 1.5. A second, unrelated
shortcut in the same file - one polynomial fitted to sine and cosine over
[0, π/2], which is only 12 kHz at 48 kHz - broke the *top* of the band too,
badly enough that a `HighPass` at 22 kHz passed its entire stopband.

Both are fixed. Coefficients now get as many fractional bits as each
individual filter has room for, the recursion accumulates in 64 bits and
keeps its feedback below the sample grid, and the trigonometry is a proper
series. Measured against the closed-form response, every mode lands within
**0.03 dB from 50 Hz to 22 kHz**. `GraphicEQ`'s ten ISO bands all read
+6.01 dB or better on a +6 dB request; `MultibandCompressor`'s three bands
recombine flat to 0.23 dB from 30 Hz to 8 kHz. `docs/upstream-diff.md`,
"The biquads were Q15, so they could not go low", has the arithmetic, the
before-and-after table, and what it cost in instructions on an M0.

Nothing refuses a low frequency and nothing ever did, because a
`LadderFilter` sweeping down through 40 Hz is a legitimate thing to do.
The only remaining rule is the one that was always real: stay below
Nyquist, which `check_hz` enforces.

## A note on patches

Some classes carry **patches**: named settings on the same 0-127 MIDI grid
`audioinstruments` uses, so a host or an app can offer presets and automate
knobs without knowing what any particular effect's arguments mean.

```python
mod = audioeffects.RingMod(source, patch=1)   # "Dalek"
mod.set_macro(0, 96)                          # Frequency, MIDI scale
name, values = audioeffects.RingMod.PATCHES[2]
```

A patchable class declares `MACRO_LABELS` (the knob names), `MACRO_RANGES`
(what each spans, linear or logarithmic), and `PATCHES`
(`{index: (name, (values,))}`). `set_macro(index, value)` takes the MIDI
scale and accepts floats, so a host with finer resolution need not quantize;
`macro(index)` reads a knob back in its own units; `program_change(index)`
applies a patch and ignores an index the class does not have, the way an
instrument does.

**Patch 0 is always the constructor's own defaults**, rendered onto the 7-bit
grid - close to a fresh instance, not identical to one, because 128 steps
cannot land exactly on every default. Constructor arguments are *not*
quantized: `RingMod(src, frequency=440)` gets 440 Hz, while patch 0's nearest
grid point for the 220 Hz default is 215.7.

It is optional, and most classes do not have one yet. A class without
`MACRO_LABELS` raises rather than pretending: `set_macro` on it is an
application bug, not a wire message.

### Known gap: a *rack* cannot have patches

Patches live on a class. A **rack** - several of these classes wired
together, with a `handle_event` mapping incoming macros onto whichever knobs
of whichever nodes the author chose - is a script, not a class, so there is
nothing for `MACRO_LABELS`/`PATCHES` to attach to. Every rack in
`micropython-vst3/soundtrack/` is one of these, and none of them can offer a
preset.

That is the gap, found 2026-08-27 while auditioning
`soundtrack/Perihelion/fx_shimmer.py` (a choir into an octave-up tape echo
into a long hall). The user's words: *"This effect needs presets to be very
usable."* The composed thing is what a musician actually reaches for, and it
is exactly the layer with no preset story.

**Deliberately not solved here.** It wants its own plan: a rack needs a
declared identity (labels, ranges, patches) that survives being a plain
script the sidecar `exec`s, and the answer probably looks like the
`create()` factory convention `audioinstruments` uses rather than anything
in this package. Sketched, not designed: a rack module declaring
`MACRO_LABELS`/`MACRO_RANGES`/`PATCHES` at module scope and a
`create(source, sample_rate)` returning an object with the same
`set_macro`/`program_change` surface as an `Effect`, so hosts cannot tell a
rack from a single class. That would also give `render_preview.py` and
`generate_project.py` one thing to read instead of two.

## A note on chaining after a Mixer

Several classes here end in an `audiomixer.Mixer` - anything that splits
into parallel branches and sums them. On MicroPython and CPython you can
chain freely after one. On CircuitPython you cannot: its Mixer stops its
voices when it is reset, and every effect resets its source when you
`play()` it, so the chain goes silent. audioif fixes that for its own
builds; see `docs/upstream-diff.md`, "Resetting a Mixer silenced it".

## A note on filters off a stock CircuitPython board

Every frequency in this library is the frequency you get - on audioif.
On stock CircuitPython two engine bugs are still in the way, and they
change what these classes sound like rather than breaking them, so they
are worth knowing about:

- A stereo `audiofilters.Filter` runs **one** biquad state across the
  interleaved stream, so the recursion advances twice per frame and every
  filter sits an **octave above** where it was asked to sit - and the
  feedback path leaks each channel into the other. Fixed upstream after
  10.2.1, so a current CircuitPython is fine; 10.2.1 itself is not.
- `PEAKING_EQ` computes `b2` with the wrong sign, which costs the filter
  its unity-outside-the-band property: a +6 dB bell at 1 kHz / Q 1 is
  about **+21 dB at DC**, worse the lower the center. Still present
  upstream. `ParametricEQ`, `GraphicEQ`, and every shelf-free bell here
  depend on it.
- Biquad coefficients are Q15 and the recursion accumulates in 32 bits, so
  nothing below roughly 300 Hz is the filter it was asked to be, and one
  polynomial covers sine and cosine only as far as π/2 - 12 kHz at 48 kHz -
  so nothing near Nyquist is either. Both ends fail quietly. Still present
  upstream, and the section above is what a filter does here instead.

This library used to compensate for both - halving every frequency on the
way in, and synthesizing bells out of notch and band-pass sections. It no
longer does, because the engine is right. See `docs/upstream-diff.md` for
the measurements and the one-line coefficient fix.

## Testing

`tests/test_cpython_effects_library.py` builds and renders every class and
measures what it does, under CPython. `tests/parity/effects_library_smoke.py`
is the coarse half of that in portable Python, so MicroPython and patched
CircuitPython can walk the same catalogue - every class, and every patch of
every patchable class. micropython-vst3's `tools/test-effects-lib.py`
additionally runs them inside a real VST3 host, feeding a quiet-then-loud sine and asserting
per-class behaviour: compressors and limiters squeeze the loud half,
gates and expanders mute the quiet one, everything else passes signal.
