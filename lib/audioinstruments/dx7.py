"""Yamaha DX7."""

NAME = 'dx7'
DISPLAY_NAME = 'DX7'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "FM Amount", "Mod Ratio", "Feedback", "Env 1 Decay",
    "Env 2 Decay", "Env 3 Decay", "Release Time", "Alg Mix", "Attack Time",
    "Brightness", "Tremolo Depth", "Vibrato Depth", "Tremolo Rate",
    "Vibrato Rate", "Master Tune",
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
    0: ("Default", (102, 32, 0, 0, 44, 48, 24, 29, 64, 1, 51, 0, 0, 24, 41, 64)),
}

import math
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
    ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# In DX7 emulation via synthio, we cannot easily do true FM (modulating pitch of a Note at audio rate).
# However, we can approximate the iconic "E.Piano 1" sound using additive sine harmonics that decay at different rates.
SINE = make_table(((1, 1.0),), fast=False)
EP_HARM_1 = make_table(((1, 1.0), (3, 0.4), (5, 0.2)), fast=False)
EP_HARM_2 = make_table(((2, 1.0), (4, 0.5), (6, 0.25), (14, 0.1)), fast=False)
EP_HARM_3 = make_table(((8, 1.0), (9, 0.8), (11, 0.5), (15, 0.3))) # Metallic tines


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    fm_amount = 0.5
    mod_ratio = 1.0
    feedback = 0.0
    e1_d = 1.5
    e2_d = 0.8
    e3_d = 0.2
    rel_t = 0.5
    alg_mix = 0.5
    att_t = 0.01
    brightness = 0.8
    trem_depth = 0.0
    vib_depth = 0.0
    trem_rate = 2.0
    vib_rate = 5.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, fm_amount, mod_ratio, feedback, e1_d, e2_d, e3_d, rel_t
        nonlocal alg_mix, att_t, brightness, trem_depth, vib_depth, trem_rate, vib_rate, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # We simulate the FM modulators by having multiple carriers with different waveforms and decay times.
            # This gives the dynamic harmonic shift typical of DX7 EPiano.

            env1 = synthio.Envelope(attack_time=att_t, decay_time=e1_d, release_time=rel_t, attack_level=1.0, sustain_level=0.0)
            env2 = synthio.Envelope(attack_time=att_t, decay_time=e2_d, release_time=rel_t, attack_level=1.0, sustain_level=0.0)
            env3 = synthio.Envelope(attack_time=att_t, decay_time=e3_d, release_time=rel_t, attack_level=1.0, sustain_level=0.0)

            vib_lfo = synthio.LFO(waveform=SINE, rate=vib_rate, scale=vib_depth * 0.02) if vib_depth > 0.01 else None
            trem_wave = ring_depth_table(trem_depth) if trem_depth > 0.01 else None

            # Feedback: the DX7's self-modulating operator adds upper-harmonic
            # bite, so scale it into the metallic tine layer.
            # Alg mix: crossfades between the mellow (o1) and bright/metallic
            # (o3) layers, approximating an algorithm change.
            o1 = synthio.Note(hz, waveform=EP_HARM_1, envelope=env1, amplitude=amp * 0.6 * (1.0 - alg_mix),
                               ring_frequency=trem_rate, ring_waveform=trem_wave, bend=vib_lfo)
            o2 = synthio.Note(hz * mod_ratio, waveform=EP_HARM_2, envelope=env2, amplitude=amp * 0.3 * fm_amount,
                               ring_frequency=trem_rate, ring_waveform=trem_wave, bend=vib_lfo)
            o3 = synthio.Note(hz, waveform=EP_HARM_3, envelope=env3, amplitude=amp * 0.4 * brightness * (alg_mix + feedback),
                               ring_frequency=trem_rate, ring_waveform=trem_wave, bend=vib_lfo)

            notes = [o1, o2, o3]
            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: fm_amount = value0 * 2.0
            elif data0 == 2: mod_ratio = 1.0 + math.floor(value0 * 10.0)
            elif data0 == 3: feedback = value0
            elif data0 == 4: e1_d = 0.1 + value0 * 4.0
            elif data0 == 5: e2_d = 0.05 + value0 * 2.0
            elif data0 == 6: e3_d = 0.01 + value0 * 1.0
            elif data0 == 7: rel_t = 0.05 + value0 * 2.0
            elif data0 == 8: alg_mix = value0
            elif data0 == 9: att_t = 0.001 + value0 * 1.0
            elif data0 == 10: brightness = value0 * 2.0
            elif data0 == 11: trem_depth = value0
            elif data0 == 12: vib_depth = value0
            elif data0 == 13: trem_rate = 0.1 + value0 * 10.0
            elif data0 == 14: vib_rate = 0.1 + value0 * 15.0
            elif data0 == 15: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
