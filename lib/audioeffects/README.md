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
| `DynamicEQ` | notch+band split, band compressed, summed (approximation) |
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
| `Overdrive` | soft clip with tone control |
| `Distortion` | hard clip |
| `Fuzz` | pre-gained into a square |
| `Saturation` | subtle soft clip, mostly dry |
| `Bitcrusher` | lo-fi bit/rate degradation |
| `Exciter` | overdriven high-passed branch blended under the dry |

### Pitch and stereo - `pitch.py`
| Class | Notes |
|---|---|
| `PitchShifter` | time-independent shift |
| `Harmonizer` | dry + up to three fixed intervals |
| `Octaver` | -12 and +12 branches |
| `StereoWidener` | Haas: short-delayed copy panned wide against the dry |

## Deliberately absent

- **Convolution reverb** - no impulse-response engine in the palette.
- **Pitch correction** - needs pitch detection the engine does not have.
- **Ring modulation of the input** - stream-by-oscillator multiplication
  is not available (synthio ring mod applies to synthesized notes only).
- LFO-driven parameters update at the engine block rate (~187 Hz at
  48 kHz), plenty for sweep rates but not audio-rate modulation.

## Testing

`tools/test-effects-lib.py` instantiates every class through the real
MicroPython sidecar inside the VST3 effect (via the smoke host's
`--effect-script` probe), feeding a quiet-then-loud sine and asserting
per-class behaviour: compressors and limiters squeeze the loud half,
gates and expanders mute the quiet one, everything else passes signal.
