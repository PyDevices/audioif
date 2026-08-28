"""Moog Minimoog Model D."""

NAME = 'minimoog'
DISPLAY_NAME = 'Minimoog'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "Env Amount", "Glide", "Osc2 Detune",
    "Osc3 Detune", "Noise Mix", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Filter Attack", "Filter Decay", "Filter Sustain",
    "Overdrive",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "BIPOLAR",
    6: "BIPOLAR",
    7: "UNIPOLAR",
    8: "UNIPOLAR",
    9: "UNIPOLAR",
    10: "UNIPOLAR",
    11: "UNIPOLAR",
    12: "UNIPOLAR",
    13: "UNIPOLAR",
    14: "UNIPOLAR",
    15: "UNIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Classic Lead", (102, 44, 32, 51, 6, 65, 62, 0, 6, 51, 64, 44, 6, 51, 25, 0)),
    1: ('Deep Bass', (114, 25, 44, 70, 0, 66, 61, 0, 3, 38, 102, 25, 3, 32,
                      89, 19)),
    2: ('Screaming Lead', (108, 70, 95, 89, 19, 74, 56, 6, 1, 25, 114, 51,
                           1, 19, 76, 76)),
}

import array
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    logmap, make_table, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])
NOISE = noise_table(seed=1234567)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2000.0
    resonance = 1.0
    env_amount = 3000.0
    glide = 0.05
    osc2_detune = 1.01
    osc3_detune = 0.99
    noise_mix = 0.0

    amp_a = 0.01
    amp_d = 0.3
    amp_s = 0.5
    amp_r = 0.3

    filt_a = 0.01
    filt_d = 0.3
    filt_s = 0.2
    overdrive = 1.0


    voices = {}
    serial = 0
    last_pitch = None
    MAX_VOICES = 1


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, env_amount, glide, osc2_detune, osc3_detune, noise_mix
        nonlocal amp_a, amp_d, amp_s, amp_r, filt_a, filt_d, filt_s, overdrive
        nonlocal serial, last_pitch

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1)

            bend = None
            if last_pitch is not None and glide > 0.001:
                last_hz = synthio.midi_to_hz(last_pitch)
                ratio = last_hz / hz
                # Gliding from last_hz to hz.  The bend table is int16, and one
                # full-scale step is one octave, so an interval wider than an
                # octave has to clamp - the real Model D's glide can't outrun
                # its own portamento circuit either.  Without the clamp a
                # downward leap of more than an octave overflows array("h").
                depth = int(32767 * (ratio - 1.0))
                if depth > 32767:
                    depth = 32767
                elif depth < -32767:
                    depth = -32767
                glide_table = array.array("h", (depth, 0))
                bend = synthio.LFO(waveform=glide_table, once=True, rate=1.0/glide, interpolate=True)

            last_pitch = data0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            env_tbl = env_shape_table(filt_a, filt_d, filt_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, filt_a + filt_d), scale=env_amount, interpolate=True)

            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)

            amp = volume * value0 * overdrive

            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.4, bend=bend)
            o2 = synthio.Note(hz * osc2_detune, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.4, bend=bend)
            o3 = synthio.Note(hz * osc3_detune, waveform=SQUARE, envelope=env, filter=lp, amplitude=amp * 0.3, bend=bend)
            n = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=lp, amplitude=amp * noise_mix * 0.3)

            serial += 1
            voices[k] = ((o1, o2, o3, n), serial)
            synth.press(o1)
            synth.press(o2)
            synth.press(o3)
            if noise_mix > 0.01:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = logmap(value0, 50.0, 10000.0)
            elif data0 == 2: resonance = logmap(value0, 0.5, 4.0)
            elif data0 == 3: env_amount = logmap(value0, 100.0, 8000.0)
            elif data0 == 4: glide = logmap(value0, 0.001, 1.0)
            elif data0 == 5: osc2_detune = 1.0 + (value0 - 0.5) * 0.03
            elif data0 == 6: osc3_detune = 1.0 + (value0 - 0.5) * 0.03
            elif data0 == 7: noise_mix = value0
            elif data0 == 8: amp_a = logmap(value0, 0.001, 2.0)
            elif data0 == 9: amp_d = logmap(value0, 0.05, 3.0)
            elif data0 == 10: amp_s = value0
            elif data0 == 11: amp_r = logmap(value0, 0.01, 3.0)
            elif data0 == 12: filt_a = logmap(value0, 0.001, 2.0)
            elif data0 == 13: filt_d = logmap(value0, 0.05, 3.0)
            elif data0 == 14: filt_s = value0
            elif data0 == 15: overdrive = logmap(value0, 1.0, 3.0)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
