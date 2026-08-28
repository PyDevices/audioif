"""PPG Wave 2.2."""

NAME = 'ppg_wave'
DISPLAY_NAME = 'PPG Wave 2.2'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Wavetable Index", "Cutoff", "Resonance", "Env Amount",
    "Filter Attack", "Filter Decay", "Amp Attack", "Amp Sustain",
    "Amp Release", "Detune", "Master Tune",
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
    11: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 64, 102, 36, 48, 1, 8, 1, 102, 16, 25, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# PPG Wave 2.2 style digital waveforms
WAVE_A = make_table(((1, 1.0), (2, 0.5), (4, 0.25)), fast=False)
WAVE_B = make_table(((1, 1.0), (3, 0.7), (5, 0.4), (7, 0.2)), fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    wt_index = 0.5
    cutoff_base = 2000.0
    res = 1.5
    env_amount = 3000.0
    f_a = 0.01
    f_d = 0.3
    amp_a = 0.01
    amp_s = 0.8
    amp_r = 0.5
    detune = 0.01
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, wt_index, cutoff_base, res, env_amount
        nonlocal f_a, f_d, amp_a, amp_s, amp_r, detune, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=f_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            env_tbl = env_shape_table(f_a, f_d, 0.0)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, f_a + f_d), scale=env_amount, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            # PPG's signature is the wavetable position moving through the table, not
            # sitting still; scan from wave A up to the Wavetable Index target over the
            # same attack/decay contour as the filter envelope, then hold - the classic
            # "wave envelope follows filter envelope" PPG factory-patch behavior.
            scan_tbl = env_shape_table(f_a, f_d, 1.0)
            scan_lfo = synthio.LFO(waveform=scan_tbl, once=True, rate=1.0/max(0.01, f_a + f_d), scale=wt_index, interpolate=True)
            amp_a_expr = synthio.Math(synthio.MathOperation.SCALE_OFFSET, scan_lfo, -(amp * 0.4), amp * 0.4)
            amp_b_expr = synthio.Math(synthio.MathOperation.SCALE_OFFSET, scan_lfo, amp * 0.4, 0.0)

            notes = [
                synthio.Note(hz, waveform=WAVE_A, envelope=env, filter=lp, amplitude=amp_a_expr, panning=-0.2),
                synthio.Note(hz * (1.0 + detune), waveform=WAVE_A, envelope=env, filter=lp, amplitude=amp_a_expr, panning=0.2),
                synthio.Note(hz, waveform=WAVE_B, envelope=env, filter=lp, amplitude=amp_b_expr, panning=-0.2),
                synthio.Note(hz * (1.0 + detune), waveform=WAVE_B, envelope=env, filter=lp, amplitude=amp_b_expr, panning=0.2),
            ]

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: wt_index = value0
            elif data0 == 2: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 3.5
            elif data0 == 4: env_amount = value0 * 8000.0
            elif data0 == 5: f_a = 0.001 + value0 * 2.0
            elif data0 == 6: f_d = 0.05 + value0 * 4.0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_s = value0
            elif data0 == 9: amp_r = 0.01 + value0 * 4.0
            elif data0 == 10: detune = value0 * 0.05
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
