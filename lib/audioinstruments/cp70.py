"""Yamaha CP-70 electric grand."""

NAME = 'cp70'
DISPLAY_NAME = 'CP-70'
CATEGORIES = ('Piano',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Hammer Strike", "String Body", "Tremolo Rate",
    "Tremolo Depth", "Chorus", "Decay", "Brilliance", "Master Tune",
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
    8: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 51, 64, 62, 0, 64, 48, 102, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
    ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

WAVE_HAMMER = make_table(((1, 1.0), (3, 0.8), (5, 0.5), (9, 0.2)), fast=False)
WAVE_STRING = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    hammer_lvl = 0.8
    string_lvl = 1.0
    trem_rate = 5.0
    trem_depth = 0.0
    chorus = 0.5
    decay = 2.0
    brilliance = 0.8
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 12


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, hammer_lvl, string_lvl, trem_rate, trem_depth, chorus, decay, brilliance, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=0.005, decay_time=decay, release_time=0.4, attack_level=1.0, sustain_level=0.0)
            hammer_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)

            cutoff = 500.0 + (brilliance * 8000.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=0.7)

            trem_wave = ring_depth_table(trem_depth) if trem_depth > 0.01 else None

            notes = []
            # Chorus simulation
            if chorus > 0.01:
                n1 = synthio.Note(hz, waveform=WAVE_STRING, envelope=env, filter=lp, amplitude=amp * string_lvl * 0.4, ring_frequency=trem_rate, ring_waveform=trem_wave, panning=-0.3)
                n2 = synthio.Note(hz * (1.0 + chorus * 0.005), waveform=WAVE_STRING, envelope=env, filter=lp, amplitude=amp * string_lvl * 0.4, ring_frequency=trem_rate, ring_waveform=trem_wave, panning=0.3)
                notes.extend([n1, n2])
            else:
                notes.append(synthio.Note(hz, waveform=WAVE_STRING, envelope=env, filter=lp, amplitude=amp * string_lvl * 0.8, ring_frequency=trem_rate, ring_waveform=trem_wave))

            notes.append(synthio.Note(hz, waveform=WAVE_HAMMER, envelope=hammer_env, filter=lp, amplitude=amp * hammer_lvl * 0.6, ring_frequency=trem_rate, ring_waveform=trem_wave))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: hammer_lvl = value0 * 2.0
            elif data0 == 2: string_lvl = value0 * 2.0
            elif data0 == 3: trem_rate = 0.1 + value0 * 10.0
            elif data0 == 4: trem_depth = value0
            elif data0 == 5: chorus = value0
            elif data0 == 6: decay = 0.5 + value0 * 4.0
            elif data0 == 7: brilliance = value0
            elif data0 == 8: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
