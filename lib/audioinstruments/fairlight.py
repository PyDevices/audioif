"""Fairlight CMI."""

NAME = 'fairlight'
DISPLAY_NAME = 'Fairlight CMI'
CATEGORIES = ('Sampler',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Patch Select", "Bitcrush Approx", "Attack", "Decay",
    "Sustain", "Release", "Pitch Env Depth", "Filter Env", "Master Tune",
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
    9: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 0, 0, 6, 19, 102, 16, 0, 0, 64)),
}

import array
import math
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Arr1 (Breathy Choir) approx
WAVE_ARR1 = make_table(((1, 1.0), (2, 0.6), (3, 0.4), (5, 0.3), (7, 0.1), (9, 0.05)), fast=False)
# Orch5 (Orchestra Hit) approx
WAVE_ORCH5 = make_table([(n, 1.0 / math.sqrt(n)) for n in range(1, 20)], fast=False)

def quantize_table(src, levels):
    # Real Fairlight CMI voice cards were 8-bit: this rounds amplitude down
    # to `levels` steps, the actual quantization stair-step that gave the
    # CMI its aliased grit (a feature to preserve, not filter away)
    step = 65536 // levels
    out = array.array("h", bytearray(len(src) * 2))
    for i in range(len(src)):
        out[i] = (src[i] // step) * step
    return out

WAVE_ARR1_8BIT = quantize_table(WAVE_ARR1, 256)
WAVE_ORCH5_8BIT = quantize_table(WAVE_ORCH5, 256)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    patch = 0.0 # < 0.5 = Arr1, > 0.5 = Orch5
    bitcrush = 0.0
    amp_a = 0.1
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.5
    pitch_env = 0.0
    f_env = 0.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, patch, bitcrush, amp_a, amp_d, amp_s, amp_r, pitch_env, f_env, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            is_orch = patch > 0.5

            # Orch5 has a very specific tight envelope and pitch envelope
            actual_a = 0.01 if is_orch else amp_a
            actual_d = 0.5 if is_orch else amp_d
            actual_s = 0.0 if is_orch else amp_s
            actual_r = 0.1 if is_orch else amp_r

            env = synthio.Envelope(attack_time=actual_a, decay_time=actual_d, release_time=actual_r, attack_level=1.0, sustain_level=actual_s)

            wave = WAVE_ORCH5 if is_orch else WAVE_ARR1
            wave_crushed = WAVE_ORCH5_8BIT if is_orch else WAVE_ARR1_8BIT

            # Pitch envelope (for Orch5 "whack")
            bend = synthio.LFO(waveform=FALL, once=True, rate=1.0/0.1, scale=pitch_env) if pitch_env > 0.01 else None

            # Fairlight anti-aliasing filter was weak/stepped, so it let the
            # 8-bit quantization noise through - continuous with Bitcrush Approx
            c_base = 8000.0 - bitcrush * 5500.0

            # Filter envelope
            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/actual_d, scale=f_env * 5000.0, interpolate=True)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, synthio.Math(synthio.MathOperation.SUM, c_base, f_sweep, 0.0), Q=1.0)

            notes = []
            # Bitcrush Approx blends in the genuinely 8-bit-quantized table -
            # real stair-step distortion, not just a darker filter
            notes.append(synthio.Note(hz, waveform=wave, envelope=env, filter=lp, amplitude=amp * 0.7 * (1.0 - bitcrush * 0.6), bend=bend))
            if bitcrush > 0.01:
                notes.append(synthio.Note(hz, waveform=wave_crushed, envelope=env, filter=lp, amplitude=amp * 0.7 * bitcrush, bend=bend))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: patch = value0
            elif data0 == 2: bitcrush = value0
            elif data0 == 3: amp_a = 0.001 + value0 * 2.0
            elif data0 == 4: amp_d = 0.05 + value0 * 3.0
            elif data0 == 5: amp_s = value0
            elif data0 == 6: amp_r = 0.01 + value0 * 4.0
            elif data0 == 7: pitch_env = value0
            elif data0 == 8: f_env = value0
            elif data0 == 9: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
