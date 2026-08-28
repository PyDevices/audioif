"""Vox Continental combo organ."""

NAME = 'vox_continental'
DISPLAY_NAME = 'Vox Continental'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Drawbar 16", "Drawbar 8", "Drawbar 4", "Drawbar IV",
    "Vibrato Rate", "Vibrato Depth", "Brilliance", "Master Tune",
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
    0: ("Default", (102, 127, 127, 102, 64, 75, 0, 102, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Transistor organs use a brighter, buzzier waveform than B3 sine waves
WAVE_TRANS = make_table(((1, 1.0), (2, 0.5), (3, 0.33), (4, 0.25)), fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    db16 = 1.0
    db8 = 1.0
    db4 = 0.8
    db_iv = 0.5
    vib_rate = 6.0
    vib_depth = 0.0
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
        nonlocal volume, db16, db8, db4, db_iv, vib_rate, vib_depth, brilliance, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=0.01, decay_time=0.1, release_time=0.1, attack_level=1.0, sustain_level=1.0)

            cutoff = 1000.0 + (brilliance * 6000.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=0.5)

            vib_lfo = synthio.LFO(waveform=SINE, rate=vib_rate, scale=vib_depth * 0.02) if vib_depth > 0.01 else None

            notes = []
            if db16 > 0.01: notes.append(synthio.Note(hz * 0.5, waveform=WAVE_TRANS, envelope=env, filter=lp, amplitude=amp * db16 * 0.25, bend=vib_lfo))
            if db8 > 0.01: notes.append(synthio.Note(hz, waveform=WAVE_TRANS, envelope=env, filter=lp, amplitude=amp * db8 * 0.25, bend=vib_lfo))
            if db4 > 0.01: notes.append(synthio.Note(hz * 2.0, waveform=WAVE_TRANS, envelope=env, filter=lp, amplitude=amp * db4 * 0.25, bend=vib_lfo))
            if db_iv > 0.01: notes.append(synthio.Note(hz * 2.99, waveform=WAVE_TRANS, envelope=env, filter=lp, amplitude=amp * db_iv * 0.25, bend=vib_lfo))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: db16 = value0
            elif data0 == 2: db8 = value0
            elif data0 == 3: db4 = value0
            elif data0 == 4: db_iv = value0
            elif data0 == 5: vib_rate = 0.1 + value0 * 10.0
            elif data0 == 6: vib_depth = value0
            elif data0 == 7: brilliance = value0
            elif data0 == 8: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
