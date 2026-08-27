"""Hohner Clavinet D6."""

NAME = 'Clavinet D6'
CATEGORIES = ('Piano',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Pickup Mix", "Mute Level", "Wah Depth", "Wah Rate",
    "Brilliance", "Amp Attack", "Amp Decay", "Amp Sustain", "Amp Release",
    "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 0, 0, 19, 64, 6, 38, 13, 24, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Clavinet string plucks
WAVE_CB = make_table([(n, 1.0 / n) for n in range(1, 40)]) # Bright saw-like
WAVE_DA = make_table([(n, 1.0 / n) for n in range(1, 40, 2)]) # Hollow square-like
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    pickup_mix = 0.5 # 0 = DA, 1 = CB
    mute_lvl = 0.0
    wah_depth = 0.0
    wah_rate = 2.0
    brilliance = 0.5
    amp_a = 0.01
    amp_d = 1.0
    amp_s = 0.1
    amp_r = 0.2
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 16


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, pickup_mix, mute_lvl, wah_depth, wah_rate, brilliance
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            # Mute slider makes decay very short
            actual_d = amp_d * (1.0 - mute_lvl * 0.9)
            actual_s = amp_s * (1.0 - mute_lvl)

            env = synthio.Envelope(attack_time=amp_a, decay_time=actual_d, release_time=amp_r, attack_level=1.0, sustain_level=actual_s)

            cutoff = 1000.0 + (brilliance * 6000.0)

            if wah_depth > 0.01:
                wah_lfo = synthio.LFO(waveform=SINE, rate=wah_rate, scale=wah_depth * 4000.0)
                cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff, wah_lfo, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.BAND_PASS if wah_depth > 0.01 else synthio.FilterMode.LOW_PASS, cutoff, Q=2.0 if wah_depth > 0.01 else 0.8)

            o_cb = synthio.Note(hz, waveform=WAVE_CB, envelope=env, filter=lp, amplitude=amp * pickup_mix * 0.7)
            o_da = synthio.Note(hz, waveform=WAVE_DA, envelope=env, filter=lp, amplitude=amp * (1.0 - pickup_mix) * 0.7)

            serial += 1
            voices[k] = ((o_cb, o_da), serial)
            synth.press(o_cb)
            synth.press(o_da)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: pickup_mix = value0
            elif data0 == 2: mute_lvl = value0
            elif data0 == 3: wah_depth = value0
            elif data0 == 4: wah_rate = 0.5 + value0 * 10.0
            elif data0 == 5: brilliance = value0
            elif data0 == 6: amp_a = 0.001 + value0 * 0.2
            elif data0 == 7: amp_d = 0.1 + value0 * 3.0
            elif data0 == 8: amp_s = value0
            elif data0 == 9: amp_r = 0.01 + value0 * 1.0
            elif data0 == 10: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
