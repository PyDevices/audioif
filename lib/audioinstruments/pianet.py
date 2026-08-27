"""Hohner Pianet."""

NAME = 'Pianet'
CATEGORIES = ('Piano',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Pluck Attack", "Mellow Tone", "Decay Time", "Vibrato Rate",
    "Vibrato Depth", "Amp Attack", "Amp Sustain", "Amp Release",
    "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 64, 42, 62, 0, 6, 13, 22, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SINE = make_table(((1, 1.0),), fast=False)
WAVE_PIANET = make_table(((1, 1.0), (3, 0.2)), fast=False)
WAVE_PLUCK = make_table(((1, 1.0), (2, 0.8), (3, 0.6), (4, 0.4), (5, 0.2)), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    pluck_attack = 0.5
    mellow_tone = 0.5
    decay_time = 1.5
    vib_rate = 5.0
    vib_depth = 0.0
    amp_a = 0.01
    amp_s = 0.1
    amp_r = 0.4
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, pluck_attack, mellow_tone, decay_time, vib_rate, vib_depth
        nonlocal amp_a, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=decay_time, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)
            pluck_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)

            cutoff = 1000.0 + ((1.0 - mellow_tone) * 4000.0)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=0.7)

            vib_lfo = synthio.LFO(waveform=SINE, rate=vib_rate, scale=vib_depth * 0.025) if vib_depth > 0.01 else None

            o_body = synthio.Note(hz, waveform=WAVE_PIANET, envelope=env, filter=lp, amplitude=amp * 0.7, bend=vib_lfo)
            o_pluck = synthio.Note(hz, waveform=WAVE_PLUCK, envelope=pluck_env, filter=lp, amplitude=amp * pluck_attack * 0.4, bend=vib_lfo)

            serial += 1
            voices[k] = ((o_body, o_pluck), serial)
            synth.press(o_body)
            synth.press(o_pluck)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: pluck_attack = value0
            elif data0 == 2: mellow_tone = value0
            elif data0 == 3: decay_time = 0.5 + value0 * 3.0
            elif data0 == 4: vib_rate = 0.1 + value0 * 10.0
            elif data0 == 5: vib_depth = value0
            elif data0 == 6: amp_a = 0.001 + value0 * 0.2
            elif data0 == 7: amp_s = value0
            elif data0 == 8: amp_r = 0.05 + value0 * 2.0
            elif data0 == 9: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
