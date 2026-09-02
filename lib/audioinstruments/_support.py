"""Shared building blocks for the instrument modules.

Every instrument here is a `synthio` program with the same shape: module-level
`MACRO_LABELS`/`PATCHES` (plus `NOTE_MAP` for drum machines), sample-rate
independent wavetables, and a `create(sample_rate, channel_count=2,
transport=None)` factory
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

import synthio

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


# Instruments share far more wavetables than they differ on - a plain sine is
# the same table in thirty-two of them - and building one costs thousands of
# sin() calls, which is money on a microcontroller. Identical arguments give an
# identical table, so the first module to ask for one pays and the rest borrow
# it. The tables handed out here are shared: treat them as read-only.
_WAVE_TABLES = {}
_NOISE_TABLES = {}


def make_table(parts, length=2048, gain=32000, asym=0.0, fast=True,
               cache=True):
    """Build an additive wavetable from ``((harmonic, amplitude), ...)``.

    ``asym`` adds an asymmetric soft-clip stage (a transistor overdrive, not an
    EQ swap). ``fast`` allows the `ulab` vectorized path; instruments whose
    tables were derived with pure-Python arithmetic pass ``fast=False`` so their
    samples stay bit-identical on interpreters that ship `ulab`.

    Results are cached against the arguments that produced them. A caller whose
    arguments vary while the instrument plays - a pulse table following a width
    macro - passes ``cache=False`` rather than growing that cache without bound.
    """
    parts = tuple(parts)
    if not cache:
        return _build_table(parts, length, gain, asym, fast)
    key = (parts, length, gain, asym, fast)
    table = _WAVE_TABLES.get(key)
    if table is None:
        table = _WAVE_TABLES[key] = _build_table(parts, length, gain, asym, fast)
    return table


def _build_table(parts, length, gain, asym, fast):
    if fast and np is not None:
        idx = np.arange(length)
        acc = np.zeros(length)
        for mult, amp in parts:
            acc = acc + amp * np.sin(idx * (TAU * mult / length))
        if asym:
            # np.maximum(acc, -acc), not np.abs: ulab.numpy has neither abs
            # nor fabs, so np.abs raised AttributeError on any interpreter
            # shipping ulab. Latent until now only because all six asym=
            # call sites also pass fast=False -- it would have fired the
            # moment the two paths were unified.
            #
            # maximum() rather than sqrt(acc*acc) because it is pure
            # selection: no float round trip, so it is exactly abs() rather
            # than merely close to it.
            acc = acc + asym * acc * np.maximum(acc, -acc)
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


def noise_table(length=8192, seed=1234567, cache=True):
    """White noise from a linear congruential generator, one table period.

    Cached like :func:`make_table`, and shared read-only. Instruments do not
    agree on the seed, so it is always named at the call site."""
    key = (length, seed)
    if cache:
        out = _NOISE_TABLES.get(key)
        if out is not None:
            return out
    out = array.array("h", bytearray(length * 2))
    state = seed
    for i in range(length):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = ((state >> 15) & 0xFFFF) - 32768
    if cache:
        _NOISE_TABLES[key] = out
    return out


def ring_depth_table(depth, length=256):
    """A ring-modulation waveform biased between unity (``depth`` 0, no audible
    effect) and a full bipolar sine (``depth`` 1, true ring modulation). Below
    about 20Hz the same table reads as tremolo.

    Not cached: instruments build this from a live macro value."""
    out = array.array("h", bytearray(length * 2))
    for i in range(length):
        s = math.sin(TAU * i / length)
        v = (1.0 - depth) + depth * s
        out[i] = int(32767 * v)
    return out


def pulse_table(width, length=2048, gain=30000):
    """A variable-duty pulse wave for PWM, as a direct duty-cycle lookup rather
    than a sum of sines - the edges stay square at every width.

    Not cached: ``width`` is what the PWM macro sweeps."""
    n_hi = int(length * width)
    if n_hi < 1:
        n_hi = 1
    if n_hi > length - 1:
        n_hi = length - 1
    out = array.array("h", bytearray(length * 2))
    for i in range(length):
        out[i] = gain if i < n_hi else -gain
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


def release_voice(voices, synth, k):
    """Release the notes of the voice held under ``k``, and return that voice -
    or ``None`` when nothing was held there.

    A voice is ``(notes, serial)`` followed by whatever else its instrument
    needs to remember about it. Every instrument releases through this
    function; the few that do more at key-off - sweeping a filter through the
    release tail, striking a key-off noise - read what they need from the
    tuple it hands back, which is also how they tell a real release from a
    note-on retriggering a key that was never down.
    """
    voice = voices.pop(k, None)
    if voice is not None:
        for note in voice[0]:
            synth.release(note)
    return voice


def release_filter(spec):
    """The low-pass filter a voice sweeps through while it releases, built from
    ``(base_cutoff, sustain_delta, release_time, q)``.

    A one-shot LFO carries the cutoff from ``base_cutoff + sustain_delta`` down
    to ``base_cutoff`` over ``release_time``. This is the release stage of a
    filter envelope, and it has to be built at note-off rather than at
    note-on: the attack/decay LFO a voice is pressed with cannot express an
    indefinite sustain hold ending at a time nobody knows in advance. ``Note``
    accepts a new filter after it has been pressed, so the voice is retargeted
    on the way out.
    """
    base_cutoff, sustain_delta, release_time, q = spec
    rel_lfo = synthio.LFO(waveform=FALL, once=True,
                          rate=1.0 / max(0.01, release_time), interpolate=True)
    rel_cutoff = synthio.Math(synthio.MathOperation.SCALE_OFFSET, rel_lfo,
                              sustain_delta, base_cutoff)
    return synthio.Biquad(synthio.FilterMode.LOW_PASS, rel_cutoff, Q=q)


def steal_oldest(voices, release):
    """Release the longest-held voice. ``voices`` maps key -> (notes, serial).

    ``release`` is the instrument's own release function, not this module's:
    an instrument that sounds a key-off noise sounds one when a voice is
    stolen too.
    """
    oldest = None
    for k in voices:
        if oldest is None or voices[k][1] < voices[oldest][1]:
            oldest = k
    if oldest is not None:
        release(oldest)


def trigger_voice(voices, synth, serial, max_voices, release, k, notes):
    """Press ``notes`` as one voice, stealing as needed. Returns the new serial."""
    release(k)
    while len(voices) + len(notes) >= max_voices:
        steal_oldest(voices, release)
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
    """A live instrument implementing the audio component API.

    The class is a provider helper rather than a required base class. It keeps
    the existing event-handler seam used by the instruments, while presenting
    a stable object to renderers, hosts, and hardware callers.
    """

    def __init__(self, synth, handle_event, patches, macro_labels,
                 output=None, transport=None, note_map=None,
                 capabilities=(), latency_samples=0, tail_samples=0):
        self.synth = synth
        self._output = synth if output is None else output
        self.patches = patches
        self.macro_labels = tuple(macro_labels)
        self.note_map = note_map
        self.transport = static_transport if transport is None else transport
        self._handle = handle_event
        # The public identity is (channel, note_id) when a note id is
        # supplied, otherwise (channel, pitch). Keep the pitch alongside the
        # identity so all_notes_off() can emit a complete note-off event.
        self._active = {}
        self._macro_values = [0.0] * len(self.macro_labels)
        self._patch_index = None
        self._sample_rate = int(getattr(self._output, "sample_rate",
                                       getattr(synth, "sample_rate", 0)))
        self._channel_count = int(getattr(self._output, "channel_count",
                                         getattr(synth, "channel_count", 0)))
        if self._sample_rate < 1:
            raise ValueError("instrument sample_rate must be positive")
        if self._channel_count not in (1, 2):
            raise ValueError("instrument channel_count must be 1 or 2")
        self._capabilities = tuple(capabilities)
        for capability in self._capabilities:
            if (not isinstance(capability, str)
                    or any(ord(character) >= 128 for character in capability)):
                raise ValueError("instrument capabilities must be ASCII strings")
        self._latency_samples = _nonnegative_int(latency_samples,
                                                 "latency_samples")
        self._tail_samples = _tail_value(tail_samples)
        self._deinited = False
        self.program_change(0)

    def _check_live(self):
        if self._deinited:
            raise RuntimeError("instrument has been deinitialized")

    @property
    def output(self):
        self._check_live()
        return self._output

    @property
    def sample_rate(self):
        self._check_live()
        return self._sample_rate

    @property
    def channel_count(self):
        self._check_live()
        return self._channel_count

    @property
    def latency_samples(self):
        self._check_live()
        return self._latency_samples

    @property
    def tail_samples(self):
        self._check_live()
        return self._tail_samples

    @property
    def capabilities(self):
        self._check_live()
        return self._capabilities

    @property
    def patch_index(self):
        self._check_live()
        return self._patch_index

    def note_on(self, pitch, velocity=127, detune=0.0, channel=0, note_id=-1,
                sample_position=0):
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases,
        as it does on the wire. ``detune`` offsets the pitch in semitones."""
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        velocity = _midi_value(velocity, "velocity")
        channel = _channel(channel)
        note_id = _note_id(note_id)
        detune = float(detune)
        sample_position = _sample_position(sample_position)
        key = key_of(channel, note_id, pitch)
        if velocity > 0:
            self._active[key] = (pitch, note_id)
            self._handle(EVENT_NOTE_ON, channel, note_id, pitch,
                         velocity / 127.0, detune, sample_position)
        else:
            # MIDI note-on with zero velocity is a note-off, including at the
            # provider boundary. Do not send a note-on event that a provider
            # might reasonably ignore because its velocity is zero.
            if self._active.pop(key, None) is not None:
                self._handle(EVENT_NOTE_OFF, channel, note_id, pitch, 0.0,
                             0.0, sample_position)

    def note_off(self, pitch, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        key = key_of(channel, note_id, pitch)
        if self._active.pop(key, None) is not None:
            self._handle(EVENT_NOTE_OFF, channel, note_id, pitch, 0.0, 0.0,
                         sample_position)

    def set_macro(self, index, value, channel=0, note_id=-1, sample_position=0):
        """Set macro ``index`` to ``value`` on the 0-127 MIDI scale. Floats are
        accepted so hosts with finer resolution need not quantize."""
        self._check_live()
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        index = self._macro_index(index)
        self._set_macro(index, _bounded_midi(value), channel, note_id,
                        sample_position, custom=True)

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("program index must be a non-negative integer")
        if index < 0:
            raise ValueError("program index must be non-negative")
        patch = self.patches.get(index)
        if patch is None:
            return
        for macro_index, macro_value in enumerate(patch[1]):
            self._set_macro(macro_index, macro_value, channel, note_id,
                            sample_position, custom=False)
        self._patch_index = index

    def channel_pressure(self, value, channel=0, sample_position=0):
        self._check_live()
        self._handle(EVENT_CHANNEL_PRESSURE, _channel(channel), -1, 0,
                     _bounded_midi(value) / 127.0, 0.0,
                     _sample_position(sample_position))

    def poly_pressure(self, pitch, value, channel=0, note_id=-1,
                      sample_position=0):
        self._check_live()
        self._handle(EVENT_POLY_PRESSURE, _channel(channel), _note_id(note_id),
                     _midi_value(pitch, "pitch"), _bounded_midi(value) / 127.0,
                     0.0, _sample_position(sample_position))

    def pitch_bend(self, value, channel=0, sample_position=0):
        self._check_live()
        value = _pitch_bend(value)
        self._handle(EVENT_PITCH_BEND, _channel(channel), -1, 0,
                     value / 16383.0,
                     (value - 8192.0) / 8192.0,
                     _sample_position(sample_position))

    def control_change(self, controller, value, channel=0, sample_position=0):
        self._check_live()
        self._handle(EVENT_CONTROL_CHANGE, _channel(channel), -1,
                     _midi_value(controller, "controller"),
                     _bounded_midi(value) / 127.0, 0.0,
                     _sample_position(sample_position))

    def all_notes_off(self):
        self._check_live()
        for (channel, _identity), (pitch, note_id) in tuple(
                self._active.items()):
            self.note_off(pitch, channel=channel, note_id=note_id)

    def get_macro(self, index):
        self._check_live()
        return self._macro_values[self._macro_index(index)]

    def reset(self):
        self._check_live()
        self.all_notes_off()
        release = getattr(self.synth, "release_all", None)
        if release is not None:
            release()
        self._active.clear()
        self.program_change(0)

    def deinit(self):
        if self._deinited:
            return
        self.all_notes_off()
        seen = set()
        for node in (self._output, self.synth):
            if id(node) in seen:
                continue
            seen.add(id(node))
            deinit = getattr(node, "deinit", None)
            if deinit is not None:
                deinit()
        self._output = None
        self._deinited = True

    def _macro_index(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("macro index must be an integer")
        if not 0 <= index < len(self.macro_labels):
            raise IndexError("instrument has %d macros; no index %d"
                             % (len(self.macro_labels), index))
        return index

    def _set_macro(self, index, value, channel, note_id, sample_position,
                   custom):
        self._macro_values[index] = value
        if custom:
            self._patch_index = None
        self._handle(EVENT_PARAMETER, channel, note_id, index,
                     value / 127.0, 0.0, sample_position)


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a non-negative integer" % name)
    if value < 0:
        raise ValueError("%s must be non-negative" % name)
    return value


def _tail_value(value):
    if value is None:
        return None
    return _nonnegative_int(value, "tail_samples")


def _midi_value(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer from 0 through 127" % name)
    if not 0 <= value <= 127:
        raise ValueError("%s must be from 0 through 127" % name)
    return value


def _bounded_midi(value):
    value = float(value)
    return min(127.0, max(0.0, value))


def _pitch_bend(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pitch bend must be an integer from 0 through 16383")
    if not 0 <= value <= 16383:
        raise ValueError("pitch bend must be from 0 through 16383")
    return value


def _channel(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("channel must be an integer from 0 through 15")
    if not 0 <= value <= 15:
        raise ValueError("channel must be from 0 through 15")
    return value


def _note_id(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("note_id must be -1 or a non-negative integer")
    if value < -1:
        raise ValueError("note_id must be -1 or non-negative")
    return value


def _sample_position(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("sample_position must be a non-negative integer")
    if value < 0:
        raise ValueError("sample_position must be non-negative")
    return value
