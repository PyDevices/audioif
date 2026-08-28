"""Yamaha FS1R formant synthesizer."""

NAME = 'fs1r'
DISPLAY_NAME = 'FS1R'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Vowel A", "Vowel B", "Morph Speed", "FM Index", "Brightness",
    "Amp Attack", "Amp Decay", "Amp Sustain", "Amp Release", "Master Tune",
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
    10: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 0, 127, 64, 64, 51, 3, 30, 102, 31, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Complex FM carrier base
WAVE_FM = make_table(((1, 1.0), (2, 0.5), (3, 0.2), (4, 0.1), (7, 0.05)), fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    vowel_a = 0.0 # 0=A, 1=E, 2=I, 3=O, 4=U (simplified mapping)
    vowel_b = 1.0
    morph_speed = 0.5
    fm_idx = 0.5
    brightness = 0.8
    amp_a = 0.05
    amp_d = 1.0
    amp_s = 0.8
    amp_r = 1.0
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 6


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def get_formant_freq(vowel_idx):
        # Rough approximation of A, E, I, O, U
        v = vowel_idx * 4.0
        if v < 1.0: return 800.0 # A
        elif v < 2.0: return 400.0 # E
        elif v < 3.0: return 300.0 # I
        elif v < 4.0: return 500.0 # O
        else: return 350.0 # U

    def get_formant_freq2(vowel_idx):
        v = vowel_idx * 4.0
        if v < 1.0: return 1200.0
        elif v < 2.0: return 2000.0
        elif v < 3.0: return 2500.0
        elif v < 4.0: return 800.0
        else: return 600.0

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, vowel_a, vowel_b, morph_speed, fm_idx, brightness
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

            # We morph from Vowel A to Vowel B using an LFO FALL
            f1_start = get_formant_freq(vowel_a)
            f1_end = get_formant_freq(vowel_b)
            f2_start = get_formant_freq2(vowel_a)
            f2_end = get_formant_freq2(vowel_b)

            diff1 = f1_end - f1_start
            diff2 = f2_end - f2_start

            # FALL ramps 1.0 -> 0.0 once, so output = end + (start - end) * FALL
            # sweeps from f_start at note-on down to f_end over morph_speed
            morph_lfo = synthio.LFO(waveform=FALL, once=True, rate=1.0 / max(0.01, morph_speed * 4.0), scale=1.0, interpolate=True)

            c1 = synthio.Math(synthio.MathOperation.SUM, f1_end, synthio.Math(synthio.MathOperation.SCALE_OFFSET, morph_lfo, diff1, 0.0), 0.0)
            c2 = synthio.Math(synthio.MathOperation.SUM, f2_end, synthio.Math(synthio.MathOperation.SCALE_OFFSET, morph_lfo, diff2, 0.0), 0.0)

            bp1 = synthio.Biquad(synthio.FilterMode.BAND_PASS, c1, Q=6.0)
            bp2 = synthio.Biquad(synthio.FilterMode.BAND_PASS, c2, Q=6.0)

            # True FM operators/algorithms aren't in reach here, so the FM engine
            # is approximated as: fast pitch modulation (sideband generation,
            # like real FM) run through formant filters (the real FS1R's actual
            # party trick). Brightness raises the modulation index rather than
            # just the volume, since a brighter FM tone is a harder-modulated one.
            fm_mod = synthio.LFO(waveform=SINE, rate=hz * 2.0, scale=fm_idx * (0.04 + brightness * 0.18)) if fm_idx > 0.01 else None

            n1 = synthio.Note(hz, waveform=WAVE_FM, envelope=env, filter=bp1, amplitude=amp * 0.6, bend=fm_mod, panning=-0.3)
            n2 = synthio.Note(hz, waveform=WAVE_FM, envelope=env, filter=bp2, amplitude=amp * 0.6, bend=fm_mod, panning=0.3)

            serial += 1
            voices[k] = ((n1, n2), serial)
            synth.press(n1)
            synth.press(n2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: vowel_a = value0
            elif data0 == 2: vowel_b = value0
            elif data0 == 3: morph_speed = value0
            elif data0 == 4: fm_idx = value0
            elif data0 == 5: brightness = value0 * 2.0
            elif data0 == 6: amp_a = 0.001 + value0 * 2.0
            elif data0 == 7: amp_d = 0.05 + value0 * 4.0
            elif data0 == 8: amp_s = value0
            elif data0 == 9: amp_r = 0.01 + value0 * 4.0
            elif data0 == 10: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
