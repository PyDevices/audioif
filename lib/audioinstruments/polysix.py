"""Korg Polysix."""

NAME = 'Polysix'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Sub-Osc Level", "Cutoff", "Resonance", "Ensemble Depth",
    "PWM Rate", "Amp Attack", "Amp Decay", "Amp Sustain", "Amp Release",
    "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 102, 18, 64, 24, 1, 19, 102, 16, 64)),
}

import math
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

def pulse_wave(duty, harmonics=32):
    parts = [(n, (2.0 / (n * math.pi)) * math.sin(n * math.pi * duty)) for n in range(1, harmonics)]
    return make_table(parts, fast=False)

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)
PULSE_NARROW = pulse_wave(0.15)
PULSE_WIDE = pulse_wave(0.5)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    sub_osc = 0.5
    cutoff_val = 2000.0
    res = 1.0
    ens_depth = 1.0
    pwm_rate = 2.0
    amp_a = 0.01
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 6


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, sub_osc, cutoff_val, res, ens_depth, pwm_rate
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff_val, Q=res)

            # Emulate bucket-brigade ensemble with pitch mod
            ens_lfo1 = synthio.LFO(waveform=SINE, rate=0.6, scale=ens_depth * 0.01) if ens_depth > 0.01 else None
            ens_lfo2 = synthio.LFO(waveform=SINE, rate=6.0, scale=ens_depth * 0.005) if ens_depth > 0.01 else None

            # Real PWM: crossfade the DCO between a narrow and wide pulse table at the
            # PWM Rate, which sweeps the harmonic balance the way a duty-cycle sweep
            # would (synthio can't reshape one wavetable's duty cycle in real time).
            pwm_lfo = synthio.LFO(waveform=SINE, rate=pwm_rate, scale=0.5, offset=0.5)
            amp_narrow = synthio.Math(synthio.MathOperation.SCALE_OFFSET, pwm_lfo, -(amp * 0.5), amp * 0.5)
            amp_wide = synthio.Math(synthio.MathOperation.SCALE_OFFSET, pwm_lfo, amp * 0.5, 0.0)

            notes = []
            # Main DCO, width-modulated
            notes.append(synthio.Note(hz, waveform=PULSE_NARROW, envelope=env, filter=lp, amplitude=amp_narrow, bend=ens_lfo1, panning=-0.3))
            notes.append(synthio.Note(hz, waveform=PULSE_WIDE, envelope=env, filter=lp, amplitude=amp_wide, bend=ens_lfo1, panning=-0.3))
            # Simulated ensemble spread
            if ens_depth > 0.01:
                notes.append(synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5, bend=ens_lfo2, panning=0.3))

            # Sub osc
            if sub_osc > 0.01:
                notes.append(synthio.Note(hz * 0.5, waveform=SQUARE, envelope=env, filter=lp, amplitude=amp * sub_osc * 0.5))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: sub_osc = value0
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 3.5
            elif data0 == 4: ens_depth = value0 * 2.0
            elif data0 == 5: pwm_rate = 0.1 + value0 * 10.0
            elif data0 == 6: amp_a = 0.001 + value0 * 2.0
            elif data0 == 7: amp_d = 0.05 + value0 * 3.0
            elif data0 == 8: amp_s = value0
            elif data0 == 9: amp_r = 0.01 + value0 * 4.0
            elif data0 == 10: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
