# audioeffects

Thirty-nine effect classes built out of audioif's audio nodes, for any host
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

Two nodes make the deeper processors possible: `audiodynamics.Dynamics` (an
envelope-follower gain computer with sidechain filtering) and
`audioroute.Splitter` (fans one stream out to parallel branches that a Mixer
then sums).

## Catalogue

### Dynamic range - `dynamics.py`
| Class | Notes |
|---|---|
| `Compressor` | `character="vca"/"fet"/"optical"/"varimu"` presets shape attack/release/knee |
| `Limiter` | brickwall: instant attack against a hard ceiling |
| `Expander` | downward: below threshold, quiet gets quieter |
| `NoiseGate` | mutes below threshold |
| `DeEsser` | detector high-passed at `frequency`, so only sibilance ducks the signal |
| `TransientShaper` | independent attack/sustain gain, level-independent |
| `MultibandCompressor` | 3 bands split/compressed/summed (2nd-order crossovers: near-flat recombine) |

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
| `DigitalDelay` `SlapbackDelay` | clean repeats |
| `TapeDelay` | LFO wow with doppler, darkening tone filter (post-chain, not per-repeat) |
| `PingPongDelay` | L at t, R at 2t, hard-panned (no true cross-feedback) |
| `MultiTapDelay` | `(position, level)` tap patterns |

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

### Drive - `drive.py`
| Class | Notes |
|---|---|
| `Overdrive` | soft clip with tone control; `drive` is pre-gain into a fixed curve |
| `Distortion` | hard clip |
| `Fuzz` | pre-gained into a square |
| `Saturation` | `character="tube"/"tape"/"console"`, mostly dry |
| `Bitcrusher` | bit-depth reduction, by `bits` (2..16) or `crush` |
| `Exciter` | overdriven high-passed branch blended under the dry |

The three saturation characters are different curves, not one curve with
presets. `tube` runs the engine's asymmetric OVERDRIVE, so it generates a
2nd harmonic level with the 3rd; `tape` and `console` run its
odd-symmetric WAVESHAPE, whose 2nd harmonic measures 66 dB lower - the
numerical floor. On top of that `tape` loses 2.6 dB by 16 kHz and
`console` gains half a decibel there, and `console` is the gentlest of the
three by about 4 dB of THD. All three are level-matched to within 0.3 dB,
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

- **Convolution reverb** - no impulse-response engine in the palette.
- **Pitch correction** - needs pitch detection the engine does not have.
- **Ring modulation of the input** - stream-by-oscillator multiplication
  is not available (synthio ring mod applies to synthesized notes only).
- **Sample-rate reduction** - the other half of a lo-fi box. The engine's
  LOFI mode masks low bits and nothing else; decimation needs a
  sample-and-hold that is not in the palette. `Bitcrusher` does the bit
  depth alone.
- LFO-driven parameters update at the block rate (~187 Hz at 48 kHz),
  plenty for sweep rates but not audio-rate modulation.

## A note on how low a filter can go

Every biquad in the engine keeps its coefficients as Q15 integers, which
is the right trade on a microcontroller and costs low frequencies. Below
about 300 Hz the coefficients quantize into something that is no longer
the filter you asked for, and it fails quietly rather than loudly: a
`LowPass` at 100 Hz returns **silence**, a `HighPass` at 30 Hz returns
**+20 dB of noise**, and a low shelf at 80 Hz lifts the whole band by 13
dB instead of its 1.5. From 400 Hz up everything is accurate to a fraction
of a decibel.

So: keep `LowPass`, `HighPass`, `BandPass`, `Notch`, `LadderFilter`, and
`ParametricEQ` bands at 400 Hz or above, and expect a swept filter to stop
behaving as it goes under that. Two classes here carry the consequence in
their defaults - `GraphicEQ`'s bottom three ISO bands (31.5, 63, 125 Hz)
are wrong by +6.1, +1.0 and −2.9 dB on a +6 dB request, and
`MultibandCompressor`'s default `low_hz=200` leaves a +5 dB bump under 100
Hz. Nothing refuses a low frequency, because a `LadderFilter` sweeping
down through it is a legitimate thing to do; the failure is graceless, not
fatal. `docs/upstream-diff.md`, "The biquads are Q15, so they cannot go
low", has the coefficient arithmetic and the full measurement table.

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

This library used to compensate for both - halving every frequency on the
way in, and synthesizing bells out of notch and band-pass sections. It no
longer does, because the engine is right. See `docs/upstream-diff.md` for
the measurements and the one-line coefficient fix.

## Testing

`tests/test_cpython_effects_library.py` builds and renders every class.
micropython-vst3's `tools/test-effects-lib.py` additionally runs them
inside a real VST3 host, feeding a quiet-then-loud sine and asserting
per-class behaviour: compressors and limiters squeeze the loud half,
gates and expanders mute the quiet one, everything else passes signal.
