"""Kurzweil K2600."""

NAME = 'k2600'
DISPLAY_NAME = 'K2600'
CATEGORIES = ('Sampler',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Layer 1 Mix", "Layer 2 Mix", "Layer 3 Mix", "Layer 4 Mix",
    "Shimmer Delay", "Master Cutoff", "Master Resonance", "Amp Attack",
    "Amp Decay", "Amp Sustain", "Amp Release", "Mod Wheel",
    "Modulation Rate", "Modulation Depth", "Master Tune",
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
    0: ("Default", (102, 102, 76, 51, 102, 0, 121, 18, 16, 24, 102, 24, 0, 24,
                 13, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Complex waves for VAST emulation
WAVE_STR = make_table([(n, 1.0 / n) for n in range(1, 40)]) # Strings
WAVE_CHOIR = make_table(((1, 1.0), (2, 0.8), (3, 0.4), (4, 0.6), (5, 0.2))) # Choir-ish
WAVE_BELL = make_table(((1, 1.0), (3, 0.5), (5, 0.2), (14, 0.1))) # Bell
WAVE_BASS = make_table([(n, 1.0 / n) for n in range(1, 10, 2)]) # Square bass

SINE = make_table(((1, 1.0),))


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    l1_mix = 0.8
    l2_mix = 0.6
    l3_mix = 0.4
    l4_mix = 0.8
    shimmer = 0.0
    master_cutoff = 4000.0
    master_res = 1.0
    a_a = 0.5
    a_d = 1.0
    a_s = 0.8
    a_r = 1.5
    mod_wheel = 0.0
    mod_rate = 2.0
    mod_depth = 0.1
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, l1_mix, l2_mix, l3_mix, l4_mix, shimmer, master_cutoff, master_res
        nonlocal a_a, a_d, a_s, a_r, mod_wheel, mod_rate, mod_depth, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=a_a, decay_time=a_d, release_time=a_r, attack_level=1.0, sustain_level=a_s)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, master_cutoff, Q=master_res)

            # Mod wheel adds vibrato
            vib = synthio.LFO(waveform=SINE, rate=mod_rate, scale=mod_depth * mod_wheel * 0.05) if mod_wheel > 0.01 else None

            notes = []
            if l1_mix > 0.01:
                notes.append(synthio.Note(hz, waveform=WAVE_STR, envelope=env, filter=lp, amplitude=amp * l1_mix * 0.3, bend=vib, panning=-0.3))
            if l2_mix > 0.01:
                notes.append(synthio.Note(hz * 1.002, waveform=WAVE_CHOIR, envelope=env, filter=lp, amplitude=amp * l2_mix * 0.3, bend=vib, panning=0.3))
            if l3_mix > 0.01:
                notes.append(synthio.Note(hz * 2.0, waveform=WAVE_BELL, envelope=env, filter=lp, amplitude=amp * l3_mix * 0.2, bend=vib, panning=0.0))
            if l4_mix > 0.01:
                notes.append(synthio.Note(hz * 0.5, waveform=WAVE_BASS, envelope=env, filter=lp, amplitude=amp * l4_mix * 0.4, bend=vib, panning=0.0))

            # Shimmer simulation (high pitched detuned bells)
            if shimmer > 0.01:
                notes.append(synthio.Note(hz * 4.01, waveform=WAVE_BELL, envelope=env, filter=lp, amplitude=amp * shimmer * 0.1, panning=-0.5))
                notes.append(synthio.Note(hz * 3.99, waveform=WAVE_BELL, envelope=env, filter=lp, amplitude=amp * shimmer * 0.1, panning=0.5))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: l1_mix = value0
            elif data0 == 2: l2_mix = value0
            elif data0 == 3: l3_mix = value0
            elif data0 == 4: l4_mix = value0
            elif data0 == 5: shimmer = value0
            elif data0 == 6: master_cutoff = 50.0 * (100.0 ** value0)
            elif data0 == 7: master_res = 0.5 + value0 * 3.5
            elif data0 == 8: a_a = 0.001 + value0 * 4.0
            elif data0 == 9: a_d = 0.05 + value0 * 5.0
            elif data0 == 10: a_s = value0
            elif data0 == 11: a_r = 0.01 + value0 * 8.0
            elif data0 == 12: mod_wheel = value0
            elif data0 == 13: mod_rate = 0.1 + value0 * 10.0
            elif data0 == 14: mod_depth = value0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
