"""Alesis Andromeda A6."""

NAME = 'andromeda'
DISPLAY_NAME = 'Andromeda A6'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Filter 1 Cutoff", "Filter 2 Cutoff", "Filter Mix",
    "Resonance 1", "Resonance 2", "Env 1 -> F1", "Env 1 -> F2",
    "Unison Detune", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Filter Attack", "Filter Decay", "Master Tune",
)
MACRO_MODES = {
    0: "UNIPOLAR",
    1: "UNIPOLAR",
    2: "UNIPOLAR",
    3: "UNIPOLAR",
    4: "UNIPOLAR",
    5: "UNIPOLAR",
    6: "UNIPOLAR",
    7: "UNIPOLAR",
    8: "UNIPOLAR",
    9: "UNIPOLAR",
    10: "UNIPOLAR",
    11: "UNIPOLAR",
    12: "UNIPOLAR",
    13: "UNIPOLAR",
    14: "UNIPOLAR",
    15: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 102, 113, 64, 18, 18, 32, 16, 0, 1, 11, 64, 9, 1, 11,
                 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    f1_cutoff = 2000.0
    f2_cutoff = 3000.0
    f_mix = 0.5
    res1 = 1.0
    res2 = 1.0
    env_to_f1 = 2000.0
    env_to_f2 = 1000.0
    unison_detune = 0.0
    a_a = 0.01
    a_d = 0.3
    a_s = 0.5
    a_r = 0.3
    f_a = 0.01
    f_d = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, f1_cutoff, f2_cutoff, f_mix, res1, res2, env_to_f1, env_to_f2
        nonlocal unison_detune, a_a, a_d, a_s, a_r, f_a, f_d, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=a_a, decay_time=a_d, release_time=a_r, attack_level=1.0, sustain_level=a_s)

            env_tbl = env_shape_table(f_a, f_d, 0.0)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, f_a + f_d), scale=1.0, interpolate=True)

            c1 = synthio.Math(synthio.MathOperation.SUM, f1_cutoff, synthio.Math(synthio.MathOperation.SCALE_OFFSET, f_sweep, env_to_f1, 0.0), 0.0)
            c2 = synthio.Math(synthio.MathOperation.SUM, f2_cutoff, synthio.Math(synthio.MathOperation.SCALE_OFFSET, f_sweep, env_to_f2, 0.0), 0.0)

            # Filter 1: Moog-style Low Pass
            lp1 = synthio.Biquad(synthio.FilterMode.LOW_PASS, c1, Q=res1)
            # Filter 2: SEM-style High Pass (or Multi, but we'll use HP for contrast)
            hp2 = synthio.Biquad(synthio.FilterMode.HIGH_PASS, c2, Q=res2)

            notes = []
            if unison_detune > 0.01:
                for i, detune in enumerate([-unison_detune, 0.0, unison_detune]):
                    pan = [-0.5, 0.0, 0.5][i]
                    n1 = synthio.Note(hz * (1.0 + detune * 0.012), waveform=SAW, envelope=env, filter=lp1, amplitude=amp * (1.0 - f_mix) * 0.3, panning=pan)
                    n2 = synthio.Note(hz * (1.0 + detune * 0.012), waveform=SQUARE, envelope=env, filter=hp2, amplitude=amp * f_mix * 0.3, panning=pan)
                    notes.extend([n1, n2])
            else:
                n1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp1, amplitude=amp * (1.0 - f_mix))
                n2 = synthio.Note(hz * 1.002, waveform=SQUARE, envelope=env, filter=hp2, amplitude=amp * f_mix)
                notes.extend([n1, n2])

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: f1_cutoff = 50.0 * (100.0 ** value0)
            elif data0 == 2: f2_cutoff = 50.0 * (100.0 ** value0)
            elif data0 == 3: f_mix = value0
            elif data0 == 4: res1 = 0.5 + value0 * 3.5
            elif data0 == 5: res2 = 0.5 + value0 * 3.5
            elif data0 == 6: env_to_f1 = value0 * 8000.0
            elif data0 == 7: env_to_f2 = value0 * 8000.0
            elif data0 == 8: unison_detune = value0
            elif data0 == 9: a_a = 0.001 + value0 * 2.0
            elif data0 == 10: a_d = 0.05 + value0 * 3.0
            elif data0 == 11: a_s = value0
            elif data0 == 12: a_r = 0.01 + value0 * 4.0
            elif data0 == 13: f_a = 0.001 + value0 * 2.0
            elif data0 == 14: f_d = 0.05 + value0 * 3.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
