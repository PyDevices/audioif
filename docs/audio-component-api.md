# Audio component runtime API

This document defines the runtime contract for an **audio component**: an
instrument, an effect, or an effect rack. The metadata contract is documented
separately in `audio-components.md`.

The contract is structural. A provider does not have to inherit from an
`audioif` helper class, but it must expose the required attributes and methods.
The helper classes in `audioinstruments._support` and `audioeffects._core` are
implementation conveniences, not a requirement imposed on consumers.

## Construction

The package factories are the canonical consumer entry points. They discover
the provider from its stable `NAME`, construct a live component, and return it
without requiring the consumer to know the source module or class.

```python
instrument = audioinstruments.create(
    "minimoog", sample_rate=48000, channel_count=2,
    transport=transport,
)

effect = audioeffects.create(
    "Reverb", instrument.output, sample_rate=48000,
    transport=transport, preset="hall",
)
```

An instrument factory has this shape:

```python
create(sample_rate, channel_count=2, transport=None, **options)
```

An effect or rack factory has this shape:

```python
create(source, sample_rate, transport=None, **options)
```

`sample_rate` is a positive integer; audioif v1 supports `channel_count` 1 or
2. An instrument creates audio at the requested rate and channel count. An
effect obtains its channel count from `source` and preserves it. The source
must have the requested sample rate; construction must reject a mismatch
rather than silently
resampling, downmixing, or upmixing.

`options` are provider-specific construction options. They may allocate or
select resources needed to build the graph, such as a convolution impulse
length or a fixed topology. Musical behavior that a user should change while
the component is running belongs in macros and patches instead. Options must
be portable values or explicitly documented portable services; a consumer
must not need a CPython-only object to construct a component.

An effect borrows `source`. It owns the nodes it creates, but its `deinit()`
must not deinitialize the source. This permits explicit graph teardown,
fan-out, and sharing one source between branches.

Provider-level class or module factories may remain available for local code,
but consumers use `audioinstruments.create()` and `audioeffects.create()`.
`audioinstruments.ALL` and `audioeffects.ALL` enumerate the stable names
accepted by those factories without constructing audio graphs.

## Common live component surface

Every live component provides:

```python
component.output             # audioif-compatible pull source
component.sample_rate        # read-only integer
component.channel_count      # read-only integer
component.latency_samples    # read-only non-negative integer
component.tail_samples       # read-only non-negative integer or None
component.capabilities       # read-only tuple of strings
component.patch_index         # integer, or None for custom macro state

component.set_macro(index, value, sample_position=0)
component.program_change(index, sample_position=0)
component.get_macro(index)
component.reset()
component.deinit()
```

The current method names are part of API v1. New optional arguments may be
added compatibly, but existing names and their basic call patterns remain
valid.

`output` is the only audio-processing interface. It is an audioif-compatible
pull source suitable for `audio_out.play()` and for the surrounding audioif
graph. Components do not exchange NumPy arrays, ulab arrays, or
runtime-specific buffers at the public boundary. A provider may use NumPy on
CPython or ulab on MicroPython/CircuitPython internally only when it supplies
the portable fallback required by the provider contract.

`sample_rate` and `channel_count` describe `output`. An effect or rack reports
the same channel count as its source. `latency_samples` is input-to-output
latency at the component's sample rate. Instruments normally report zero. A
finite effect tail is reported in samples; `None` means that the tail is
unknown or not finitely bounded. A rack reports the latency and tail of its
complete graph.

`capabilities` is a static tuple of ASCII strings. An empty tuple is valid.
Names describe meaningful optional behavior, for example
`"polyphonic"`, `"pitch_bend"`, `"control_change"`, `"channel_pressure"`,
`"poly_pressure"`, or `"tempo_sync"`. Capability discovery is advisory; the
optional methods remain safe to call even when a capability is absent.

**Shipped status:** the vocabulary above is specified, but no shipped
component declares a capability yet — every provider currently reports the
empty tuple (the `CAPABILITIES = ()` default in `lib/audioeffects/_core.py`
and the `capabilities=()` default in `lib/audioinstruments/_support.py` are
never overridden). Hosts therefore cannot yet use capability discovery to
find, say, pitch-bend-aware or tempo-synced components; declaring
capabilities across the shipped libraries is deferred to future component
work, not dropped.

## MIDI and control methods

All public control values use MIDI-native units:

| Value | API range/unit |
| --- | --- |
| note pitch | integer `0..127` |
| velocity | `0..127` |
| channel | integer `0..15` |
| controller and CC value | integer `0..127` |
| macro value | `0..127`; fractional values may be accepted for fine automation |
| channel/poly pressure | `0..127` |
| pitch bend | unsigned `0..16383`, center `8192` |
| program/patch index | non-negative integer |
| detune | floating-point semitones |
| sample position | non-negative frame offset |

An instrument provides these required methods:

```python
note_on(pitch, velocity=127, detune=0.0, channel=0, note_id=-1,
        sample_position=0)
note_off(pitch, channel=0, note_id=-1, sample_position=0)
all_notes_off()
```

It also provides the optional MIDI methods below. They are present as safe
no-ops when the instrument does not use a message:

```python
pitch_bend(value, channel=0, sample_position=0)
control_change(controller, value, channel=0, sample_position=0)
channel_pressure(value, channel=0, sample_position=0)
poly_pressure(pitch, value, channel=0, note_id=-1, sample_position=0)
```

Effects and racks never receive notes. They provide the same non-note control
methods as safe no-ops or meaningful handlers, plus the common macro and
program methods. `set_macro()` is the stable control surface. The API does
not assign MIDI CC numbers to macro indices; a host, sequencer, or controller
maps CCs explicitly. `midi_cc.py` may convert between normalized values and
MIDI values, but it does not define a hidden CC-to-macro map.

`detune` is a pitch offset in semitones and is not a controller value. A note
with velocity zero is equivalent to `note_off()`.

**Known seam gap:** this API defines component *methods*, not a MIDI wire
intake. No shared adapter from MIDI bytes or event streams to these methods
ships yet: each consumer hand-rolls its own dispatch (micropython-vst3's
`mpvst_adapter` does, and so does `deliver()` in
`lib/audiorender/events.py`), and pairings that need a wire decoder in
front of a component — for example, playing a Standard MIDI File straight
into an instrument — are consequently undelivered. A shared intake is
future work owned by this message model; until it exists, budget for
writing the dispatch loop yourself.

Notes are identified by `(channel, note_id)` when `note_id >= 0`. If no note
ID is supplied (`note_id == -1`), the identity is `(channel, pitch)`. A note
off releases only the matching identity, allowing overlapping same-pitch
notes when a host supplies note IDs.

Macros are global component state. Channel and note identifiers carried with a
macro event are context, not a request for per-channel or per-note macro
storage. Program changes are also global to one live component instance.

`sample_position` is a frame offset within the current render/event interval.
Zero means the first frame. Providers must honor non-zero positions rather
than interpreting them as seconds; an adapter may establish the current
interval and schedule the event at that frame. Callers that do not schedule
within a block use the default zero.

## Macro and patch state

`get_macro(index)` returns the current public macro value in MIDI units. The
value may be fractional even though patch declarations use integer MIDI
values. An invalid macro index raises `IndexError`.

Construction applies patch `0` automatically. A fresh component and a fresh
component followed by `program_change(0)` have the same observable state.
`program_change(index)` applies a known patch and safely ignores an unknown
index. Applying a patch sets `patch_index` to that index. Changing any macro
manually sets `patch_index` to `None`, meaning custom state.

`reset()` releases all instrument notes, clears component DSP history, and
restores patch `0`. It leaves the component constructed and ready for use.

`deinit()` releases resources owned by the component but not a borrowed effect
source. It is idempotent. After the first deinitialization, further use raises
a clear `RuntimeError` (or the equivalent runtime-specific error), except that
calling `deinit()` again remains safe.

## Timing, transport, and real-time behavior

`transport` is an optional callable shared by instruments, effects, and racks.
It returns:

```python
(playing, position_seconds, bpm,
 time_signature_numerator, time_signature_denominator)
```

When omitted, the component sees `(False, 0.0, 120.0, 4, 4)`. Components may
ignore transport. A tempo-aware component advertises `"tempo_sync"`.

**Shipped status:** the producer side of this contract exists —
`lib/audiorender/tempo.py` supplies a real transport during offline
rendering, and every shipped component accepts the `transport` argument —
but no shipped component consumes it: instruments and effects store the
callable and never call it (only the `static_transport` defaults in
`lib/audioinstruments/_support.py` and `lib/audioeffects/_core.py` exist).
Tempo-synced effects and instruments are specified here but unimplemented;
they are deferred to future component work, not excluded by design.

Construction may allocate the complete graph and bounded resources. Pulling
from `output` must not allocate, block, perform I/O, or depend on garbage
collection. Event methods may update state and perform bounded voice work, but
must not allocate unbounded storage. Any fixed resource or voice limit must be
bounded by construction or explicitly enforced.

## Component kinds

An instrument has MIDI input and audio output. It has no audio source input.
An effect has audio source input and audio output and uses MIDI only for
control. An effect rack has exactly the effect shape even when its internal
graph contains serial, parallel, or mixed effects. Racks may contain and be
used by other racks.

**Shipped status:** the rack kind is fully specified — shape, metadata,
latency and tail reporting — but no rack provider ships anywhere in `lib/`
yet. Racks are deferred to the planned follow-on component library (the
future `audiocomponents` effort), not dropped; until then every published
component is a single instrument or effect, and a host that wants a chain
builds it from individual effects.

The provider metadata rules remain authoritative for classification and
catalog presentation: a `NOTE_MAP` identifies a percussion instrument, while
the runtime API identifies behavior through its kind and capabilities.
