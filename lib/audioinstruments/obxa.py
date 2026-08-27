"""Oberheim OB-Xa."""

NAME = 'OB-Xa'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Detune Spread", "Cutoff", "Resonance", "Env Depth",
    "Brass Attack", "Brass Decay", "Amp Attack", "Amp Sustain",
    "Amp Release", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 42, 102, 18, 64, 3, 19, 3, 102, 9, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    detune_spread = 0.004
    cutoff_val = 2000.0
    res = 1.0
    env_depth = 4000.0
    brass_a = 0.05
    brass_d = 0.5
    amp_a = 0.05
    amp_s = 0.8
    amp_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8 # OB-Xa is famous for its 8 voices of huge unison/poly brass


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, detune_spread, cutoff_val, res, env_depth, brass_a, brass_d
        nonlocal amp_a, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=brass_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            env_tbl = env_shape_table(brass_a, brass_d, 0.0)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, brass_a + brass_d), scale=env_depth, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            # Dual oscillator per voice with detune for massive sound
            n1 = synthio.Note(hz * (1.0 - detune_spread), waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5, panning=-0.2)
            n2 = synthio.Note(hz * (1.0 + detune_spread), waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5, panning=0.2)

            serial += 1
            voices[k] = ((n1, n2), serial)
            synth.press(n1)
            synth.press(n2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: detune_spread = value0 * 0.012
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 3.5
            elif data0 == 4: env_depth = value0 * 8000.0
            elif data0 == 5: brass_a = 0.001 + value0 * 2.0
            elif data0 == 6: brass_d = 0.05 + value0 * 3.0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_s = value0
            elif data0 == 9: amp_r = 0.01 + value0 * 4.0
            elif data0 == 10: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
