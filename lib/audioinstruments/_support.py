"""Shared building blocks for the instrument modules.

Every instrument here is a `synthio` program with the same shape: module-level
`MACRO_LABELS`/`PATCHES` (plus `NOTE_MAP` for drum machines), sample-rate
independent wavetables, and a `create(sample_rate, transport=None)` factory
returning an `Instrument`.

Units: the `Instrument` methods speak MIDI (pitches 0-127, velocity 0-127,
macros 0-127, program numbers), and are the only place those numbers are
scaled. Everything behind them - the `handle_event` bodies the factories close
over - works in normalized 0.0-1.0 floats. Macro values may be passed as floats
(64.5 is legal) so a host with finer automation resolution than 7-bit MIDI does
not have to quantize its sweeps.
"""

import array
import math

try:
    from ulab import numpy as np
except ImportError:
    np = None

TAU = 2.0 * math.pi

# Event codes. These values are part of the wire protocol shared with hosts
# that drive `handle_event` directly; they are load-bearing and must not change.
EVENT_NOTE_ON = 1
EVENT_NOTE_OFF = 2
EVENT_POLY_PRESSURE = 3
EVENT_PITCH_BEND = 4
EVENT_CONTROL_CHANGE = 5
EVENT_PARAMETER = 6
EVENT_CHANNEL_PRESSURE = 7
EVENT_TRANSPORT = 8
EVENT_PROGRAM_CHANGE = 9

# A one-shot LFO waveform that falls from full scale to zero: the pitch drop
# that gives drum voices their attack.
FALL = array.array("h", (32767, 0))


def static_transport():
    """Default transport: stopped at the origin, 120 bpm, 4/4."""
    return (False, 0.0, 120.0, 4, 4)


def make_table(parts, length=2048, gain=32000, asym=0.0, fast=True):
    """Build an additive wavetable from ``((harmonic, amplitude), ...)``.

    ``asym`` adds an asymmetric soft-clip stage (a transistor overdrive, not an
    EQ swap). ``fast`` allows the `ulab` vectorized path; instruments whose
    tables were derived with pure-Python arithmetic pass ``fast=False`` so their
    samples stay bit-identical on interpreters that ship `ulab`.
    """
    if fast and np is not None:
        idx = np.arange(length)
        acc = np.zeros(length)
        for mult, amp in parts:
            acc = acc + amp * np.sin(idx * (TAU * mult / length))
        if asym:
            acc = acc + asym * acc * np.abs(acc)
        peak = np.max(acc * acc) ** 0.5
        if peak <= 0.0:
            peak = 1.0
        scaled = acc * (gain / peak)
        return array.array("h", [int(v) for v in scaled])
    vals = [0.0] * length
    for mult, amp in parts:
        step = TAU * mult / length
        for i in range(length):
            vals[i] += amp * math.sin(step * i)
    if asym:
        for i in range(length):
            v = vals[i]
            vals[i] = v + asym * v * abs(v)
    peak = 0.0
    for v in vals:
        a = v if v >= 0.0 else -v
        if a > peak:
            peak = a
    if peak <= 0.0:
        peak = 1.0
    out = array.array("h", bytearray(length * 2))
    scale = gain / peak
    for i in range(length):
        out[i] = int(vals[i] * scale)
    return out


def noise_table(length=8192, seed=1234567):
    """White noise from a linear congruential generator, one table period."""
    out = array.array("h", bytearray(length * 2))
    state = seed
    for i in range(length):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = ((state >> 15) & 0xFFFF) - 32768
    return out


def env_shape_table(attack, decay, sustain, length=96):
    """One-shot LFO waveform: ramps 0 -> peak over the attack fraction, then
    peak -> sustain over the decay fraction, holding sustain afterwards
    (once=True freezes at the table's last sample)."""
    total = attack + decay
    n_a = 1 if total <= 0.0 else int(length * attack / total)
    if n_a < 1:
        n_a = 1
    if n_a > length - 1:
        n_a = length - 1
    sustain_level = int(32767 * sustain)
    out = array.array("h", bytearray(length * 2))
    for i in range(n_a):
        out[i] = int(32767 * (i + 1) / n_a)
    span = length - n_a
    for i in range(span):
        out[n_a + i] = int(32767 + (sustain_level - 32767) * (i + 1) / span)
    return out


def logmap(v, lo, hi):
    """Map a normalized 0.0-1.0 value onto ``lo``..``hi`` logarithmically."""
    return lo * ((hi / lo) ** v)


def key_of(channel, note_id, pitch):
    """Voice-pool key: the host's note id when it supplies one, else pitch."""
    return (channel, note_id if note_id >= 0 else pitch)


def steal_oldest(voices, release_voice):
    """Release the longest-held voice. ``voices`` maps key -> (notes, serial)."""
    oldest = None
    for k in voices:
        if oldest is None or voices[k][1] < voices[oldest][1]:
            oldest = k
    if oldest is not None:
        release_voice(oldest)


def trigger_voice(voices, synth, serial, max_voices, release_voice, k, notes):
    """Press ``notes`` as one voice, stealing as needed. Returns the new serial."""
    release_voice(k)
    while len(voices) + len(notes) >= max_voices:
        steal_oldest(voices, release_voice)
    serial += 1
    voices[k] = (tuple(notes), serial)
    for note in notes:
        synth.press(note)
    return serial


def apply_patch(handle_event, patches, index, channel=0, note_id=-1,
                sample_position=0):
    """Deliver a patch's macro values as parameter events. Patch values are
    MIDI-scale integers; the events they become are normalized floats."""
    patch = patches.get(index)
    if patch is None:
        return
    for macro_index, macro_value in enumerate(patch[1]):
        handle_event(EVENT_PARAMETER, channel, note_id, macro_index,
                     macro_value / 127.0, 0.0, sample_position)


class Instrument:
    """A live instrument: an audio source plus the MIDI surface that plays it.

    ``output`` is what a host pulls PCM from - usually the synthesizer itself,
    but an instrument that ends in an effect chain hands back the chain's tail.
    """

    def __init__(self, synth, handle_event, patches, macro_labels,
                 output=None, transport=None, note_map=None):
        self.synth = synth
        self.output = synth if output is None else output
        self.patches = patches
        self.macro_labels = macro_labels
        self.note_map = note_map
        self.transport = static_transport if transport is None else transport
        self._handle = handle_event
        self._active = set()

    def note_on(self, pitch, velocity=127, detune=0.0, channel=0, note_id=-1,
                sample_position=0):
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases,
        as it does on the wire. ``detune`` offsets the pitch in semitones."""
        pitch = int(pitch)
        if velocity > 0:
            self._active.add((channel, note_id, pitch))
        else:
            self._active.discard((channel, note_id, pitch))
        self._handle(EVENT_NOTE_ON, channel, note_id, pitch, velocity / 127.0,
                     detune, sample_position)

    def note_off(self, pitch, channel=0, note_id=-1, sample_position=0):
        pitch = int(pitch)
        self._active.discard((channel, note_id, pitch))
        self._handle(EVENT_NOTE_OFF, channel, note_id, pitch, 0.0, 0.0,
                     sample_position)

    def set_macro(self, index, value, channel=0, note_id=-1, sample_position=0):
        """Set macro ``index`` to ``value`` on the 0-127 MIDI scale. Floats are
        accepted so hosts with finer resolution need not quantize."""
        self._handle(EVENT_PARAMETER, channel, note_id, int(index),
                     value / 127.0, 0.0, sample_position)

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        apply_patch(self._handle, self.patches, int(index), channel, note_id,
                    sample_position)

    def channel_pressure(self, value, channel=0, sample_position=0):
        self._handle(EVENT_CHANNEL_PRESSURE, channel, -1, 0, value / 127.0,
                     0.0, sample_position)

    def poly_pressure(self, pitch, value, channel=0, note_id=-1,
                      sample_position=0):
        self._handle(EVENT_POLY_PRESSURE, channel, note_id, int(pitch),
                     value / 127.0, 0.0, sample_position)

    def all_notes_off(self):
        for channel, note_id, pitch in tuple(self._active):
            self.note_off(pitch, channel=channel, note_id=note_id)
