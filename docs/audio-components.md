# Audio component metadata manifest

The live-object construction and processing surface is specified separately in
[`audio-component-api.md`](audio-component-api.md). This document defines only
the static provider metadata and its consumer rules.

An **audio component** is an audioif instrument, effect, or effect rack. The
component's metadata is a static declaration owned by `audioif`. Consumers
such as the offline renderer and `micropython-vst3` may use as much or as
little of the optional metadata as they need.

The provider rule is strict: a published component must declare every
required field explicitly. The consumer rule is intentionally tolerant:
`NAME` is the only metadata field a consumer must require.

## Provider declarations

An instrument module is one component. An effect module may contain multiple
components, so each public concrete `Effect` subclass is one component. The
metadata is made only from static, portable Python literals: strings,
integers, booleans, tuples, lists, and dictionaries. Providers treat it as
read-only after import.

Required on every component:

```python
NAME = "tr808"                         # stable Python/module identifier
MACRO_LABELS = ("Level", "Accent")
MACRO_MODES = {0: "UNIPOLAR", 1: "UNIPOLAR"}
PATCHES = {
    0: ("Default", (102, 64)),
}
```

`NAME` is a non-empty ASCII Python identifier and is stable within its
package and kind. It matches an instrument module name or an effect class
name. Renaming it is a breaking change. `DISPLAY_NAME` is an optional
human-readable string for catalogs and user interfaces:

```python
DISPLAY_NAME = "TR-808"
```

`MACRO_LABELS` is a tuple of zero to sixteen unique, non-empty strings. A
component with no macros declares `MACRO_LABELS = ()`.

`MACRO_MODES` is an index-keyed dictionary with exactly one entry for every
macro label. It is `{}` when there are no macros. Its values are:

- `UNIPOLAR`: the control rests at MIDI `0` and moves upward;
- `BIPOLAR`: the control rests at MIDI `64` and moves in either direction;
- `TOGGLE`: `0` is off and `127` is on. Runtime values `0..63` are off and
  `64..127` are on.

The mode is explicit metadata and is not inferred from a MIDI CC assignment.
The `audioinstruments.midi_cc` utility may be used by an implementation to
convert normalized host values, but it does not replace the declaration.

`PATCHES` is a non-empty dictionary with contiguous integer indexes from `0`
through `N-1`, up to 128 patches:

```python
PATCHES = {
    0: ("Default", (64, 64, 0)),
    1: ("Bright", (96, 80, 127)),
}
```

Each patch name is a unique, non-empty human-readable string. Each values
tuple has exactly one integer per macro, and every value is in MIDI range
`0..127`.

**Patch values are integers deliberately, and this is settled** (Brad,
2026-09-02, after the question was raised by instruments whose declared
defaults did not land on a grid point). The live surface and the patch
surface do different jobs, and the asymmetry is the boundary between them:

- **Live macro values are performance** — continuous, at whatever resolution
  the host offers. A DAW turning a knob sends a gradual slope, and
  `get_macro()` returns a fractional value (see `audio-component-api.md`).
- **Patch values are storage** — discrete, portable, and meant to reproduce.

Opening patches to floats would be comfortable for a DAW and would then
require special cases for MIDI, which is integer-native for program change
and patch transfer. Worse, it would make a patch host-dependent: one saved
from a DAW's continuous control could not be reproduced on a MIDI rig, and a
patch that does not travel is not a patch. **The 7-bit integer is what makes
a patch portable**, which is the whole purpose of having one.

The resolution this costs is bought back by **choosing the curve rather than
widening the type**. A macro whose useful values crowd one end of its range
should map logarithmically, putting fine grain where the ear needs it and
coarse where it does not — 128 well-placed points are worth more than 128
evenly-spaced ones. Engineering ranges are private (`_MACRO_RANGES`), so a
provider may re-range freely; only the public `0..127` scale is fixed.

Corollary worth stating, because it is easy to get wrong: since construction
applies patch `0` and a patch supplies every macro, **a source-level default
for a macro-controlled parameter is never observable.** What ships is patch
`0`. Where the two disagree, the source is documentation that contradicts the
artifact — see [audioif#17](https://github.com/PyDevices/audioif/issues/17). Patch `0` is the component's default state. When there is only one
patch, `Default` is the convention but not a validity requirement. When
there are multiple patches, patch `0` has a descriptive name like every other
patch. A macro-less component uses an empty values tuple.

Percussion instruments additionally declare a non-empty `NOTE_MAP`:

```python
NOTE_MAP = (
    (36, "Bass Drum"),
    (38, "Snare"),
)
```

It is a tuple of unique MIDI note numbers and unique, non-empty voice labels.
The presence of a valid `NOTE_MAP` is the sole percussion discriminator;
melodic instruments omit it. `CATEGORIES` may contain `"percussion"`, but
that value is descriptive and does not determine classification.

Effects do not declare `NOTE_MAP`. In an effect source file, `VENDOR` is
module-level and applies to every public component in that file. Instruments
also use module-level `VENDOR`. `CATEGORIES`, `VERSION`, `VENDOR`, and
`DISPLAY_NAME` are optional; when supplied, they must have the documented
shape. `CATEGORIES` is a tuple of descriptive strings, while `VERSION` and
`VENDOR` are non-empty strings.

Engineering ranges such as hertz, seconds, and decibels are implementation
details. They may remain in private names such as `_MACRO_RANGES`, but
`MACRO_RANGES` is not public component metadata. Public macro and patch
values always use the MIDI `0..127` scale.

## Discovery and validation

Metadata is discoverable from module/class declarations without constructing
an audio graph. `audioinstruments.ALL` identifies instrument modules. Public
concrete effect classes are the effect providers; private helpers and base
classes are excluded. The portable validator in
`tools/validate_metadata.py` is the authority used by tests and tooling.

`audioinstruments.DRUM_MACHINES` is derived from modules that declare a
non-empty `NOTE_MAP`; `MELODIC` is the remainder of `ALL`. This avoids a
second hand-maintained classification list.

## Runtime portability and signal shape

An audio component is portable source code. It may run under CircuitPython,
MicroPython, or CPython on Linux, Windows, WebAssembly, Android (wheels
build and publish; playback is not yet validated on an emulator or a
device — see `handoff.md`), or another
host supported by the surrounding audio stack. Component code must therefore
use the common Python/audioif surface. When an operation differs by runtime,
the component supplies another route for the other runtimes rather than
silently depending on a CPython-only function or object.

The audio direction is part of the construction contract:

- an instrument receives MIDI note/control events and exposes an audio output;
- an effect receives an audio source and exposes an audio output, with MIDI
  used only for control;
- a rack has the same external shape as an effect, even when its internal
  graph contains several effects.

The shared builds freeze `ulab`; CPython may use NumPy behind the same
portable route. Components do not import NumPy-only APIs into their common
path. This lets the same component be used by the offline renderer, a VST3
adapter, a software-only device, or the audio side of a MIDI controller.

## Effect racks

An effect rack is one audio component whose internal graph chains or mixes
multiple effect nodes. It declares the same required metadata as a single
effect class. When the rack is a public class inside an effects package —
the shipped form — the declarations sit at class scope like every other
effect class; a standalone rack script file makes the same declarations at
module scope, because that rack is one source file:

```python
NAME = "ShimmerHall"
DISPLAY_NAME = "Shimmer Hall"
MACRO_LABELS = ("Shimmer", "Echo", "Space", "Tone")
MACRO_MODES = {0: "UNIPOLAR", 1: "UNIPOLAR", 2: "UNIPOLAR", 3: "UNIPOLAR"}
PATCHES = {0: ("Shimmer Hall", (70, 57, 76, 79))}
```

The rack may implement its control surface with a module-level event handler
or with an object/factory equivalent to an effect class. A consumer may use
the declarations to build a UI, initialize values, or offer program changes;
the metadata remains mandatory even when that consumer chooses not to use
those features.

**Shipped status:** rack providers ship in `lib/audioeffects/rack.py` —
`Rack` (the generic serial-chain mechanism, built from a portable `chain`
literal), `ShimmerHall`, and `AirSpace` (fixed topologies with a macro
surface, ported from micropython-vst3's shared soundtrack racks). All
three are ordinary `audioeffects` providers: class-scope metadata,
validated by `tools/validate_metadata.py` with the other effect classes.

## Consumer behavior

A consumer must use `NAME` as the stable lookup identity and may use
`DISPLAY_NAME`, `CATEGORIES`, `VERSION`, `VENDOR`, macro modes, patches, or
note maps when useful. It must not assume optional metadata exists. It may
also provide a generic UI when macros or patches are empty, although every
provider still declares those fields explicitly.
