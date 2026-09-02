"""Hammond B-3 tonewheel organ."""

NAME = 'b3'
DISPLAY_NAME = 'B-3'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Drawbar 16", "Drawbar 8", "Drawbar 4", "Drawbar 2",
    "Perc Level", "Perc Decay", "Key Click", "Leslie Fast", "Overdrive",
    "Master Tune",
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
    8: "TOGGLE",
    9: "UNIPOLAR",
    10: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Default', (102, 127, 127, 64, 25, 64, 75, 38, 0, 0, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, logmap,
    make_table, noise_table, ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SINE = make_table(((1, 1.0),), fast=False)
NOISE = noise_table(seed=1234)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    db16 = 1.0
    db8 = 1.0
    db4 = 0.5
    db2 = 0.2
    perc_lvl = 0.5
    perc_dec = 0.3
    key_click = 0.3
    leslie_fast = 0.0
    overdrive = 1.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8 # B3 has heavy polyphony usually, but we need to limit to avoid CPU overload due to additive oscillators


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, db16, db8, db4, db2, perc_lvl, perc_dec, key_click, leslie_fast, overdrive, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0 * overdrive

            env = synthio.Envelope(attack_time=0.01, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=1.0)
            perc_env = synthio.Envelope(attack_time=0.001, decay_time=perc_dec, release_time=0.05, attack_level=1.0, sustain_level=0.0)
            click_env = synthio.Envelope(attack_time=0.001, decay_time=0.02, release_time=0.02, attack_level=1.0, sustain_level=0.0)

            # Leslie has two independent rotors: a slow bass drum and a faster
            # treble horn, each with its own speed and modulation depth.
            drum_rate = 5.0 if leslie_fast > 0.5 else 0.6
            horn_rate = 6.8 if leslie_fast > 0.5 else 0.85
            drum_wave = ring_depth_table(0.15)
            horn_wave = ring_depth_table(0.35)
            drum_vib = synthio.LFO(waveform=SINE, rate=drum_rate * 1.05, scale=0.01)
            horn_vib = synthio.LFO(waveform=SINE, rate=horn_rate * 1.05, scale=0.025)

            notes = []
            # Drawbars: 16' (sub), 8' (fund) go through the bass drum rotor;
            # 4' (2nd harm), 2' (4th harm) go through the treble horn rotor
            if db16 > 0.01: notes.append(synthio.Note(hz * 0.5, waveform=SINE, envelope=env, amplitude=amp * db16 * 0.25, ring_frequency=drum_rate, ring_waveform=drum_wave, bend=drum_vib, panning=-0.2))
            if db8 > 0.01: notes.append(synthio.Note(hz, waveform=SINE, envelope=env, amplitude=amp * db8 * 0.25, ring_frequency=drum_rate, ring_waveform=drum_wave, bend=drum_vib, panning=0.2))
            if db4 > 0.01: notes.append(synthio.Note(hz * 2.0, waveform=SINE, envelope=env, amplitude=amp * db4 * 0.2, ring_frequency=horn_rate, ring_waveform=horn_wave, bend=horn_vib, panning=-0.1))
            if db2 > 0.01: notes.append(synthio.Note(hz * 4.0, waveform=SINE, envelope=env, amplitude=amp * db2 * 0.15, ring_frequency=horn_rate, ring_waveform=horn_wave, bend=horn_vib, panning=0.1))

            # 3rd harmonic percussion rides the horn rotor
            if perc_lvl > 0.01: notes.append(synthio.Note(hz * 3.0, waveform=SINE, envelope=perc_env, amplitude=amp * perc_lvl * 0.4, ring_frequency=horn_rate, ring_waveform=horn_wave, bend=horn_vib))

            # Key click
            if key_click > 0.01:
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 5000.0, Q=1.0)
                notes.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=click_env, filter=hp, amplitude=amp * key_click * 0.3))

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
            elif data0 == 4: db2 = value0
            elif data0 == 5: perc_lvl = value0
            elif data0 == 6: perc_dec = logmap(value0, 0.05, 1.05)
            elif data0 == 7: key_click = value0
            elif data0 == 8: leslie_fast = value0
            elif data0 == 9: overdrive = 1.0 + value0 * 2.0
            elif data0 == 10: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
