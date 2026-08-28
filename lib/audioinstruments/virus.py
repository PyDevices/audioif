"""Access Virus."""

NAME = 'virus'
DISPLAY_NAME = 'Virus'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Hypersaw Detune", "Sub Osc", "Cutoff", "Resonance",
    "Distortion", "Env Depth", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Amp Release", "Master Tune",
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
    0: ("Default", (102, 42, 64, 102, 18, 64, 64, 1, 19, 102, 9, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)], fast=False)
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)], fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    hs_detune = 0.2
    sub_osc = 0.5
    cutoff_val = 2000.0
    res = 1.0
    distortion = 1.0
    env_depth = 4000.0
    amp_a = 0.01
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 4 # Hypersaw is taxing (5 detuned saws per voice)


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, hs_detune, sub_osc, cutoff_val, res, distortion, env_depth
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

            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/amp_d, scale=env_depth, interpolate=True)
            # Distortion pushes the filter brighter too, mimicking the extra
            # harmonic energy an analog-modeled overdrive stage would expose
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val * (1.0 + distortion * 0.6), f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            notes = []

            # Hypersaw emulation (5 saws)
            detunes = [0.0, hs_detune * 0.03, -hs_detune * 0.03, hs_detune * 0.06, -hs_detune * 0.06]
            pans = [0.0, 0.4, -0.4, 0.8, -0.8]

            base_a = amp * 0.2
            for i in range(5):
                notes.append(synthio.Note(hz * (1.0 + detunes[i]), waveform=SAW, envelope=env, filter=lp, amplitude=base_a, panning=pans[i]))

            if sub_osc > 0.01:
                notes.append(synthio.Note(hz * 0.5, waveform=SQUARE, envelope=env, filter=lp, amplitude=amp * sub_osc * 0.4))

            # Distortion: an added octave-up harmonic layer through a hotter,
            # un-lowpassed square wave approximates the extra odd/even overtones
            # a real overdrive/waveshaper stage would add on top of the saws
            if distortion > 0.01:
                notes.append(synthio.Note(hz * 2.0, waveform=SQUARE, envelope=env, amplitude=amp * distortion * 0.25))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: hs_detune = value0 * 0.6
            elif data0 == 2: sub_osc = value0
            elif data0 == 3: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 4: res = 0.5 + value0 * 3.5
            elif data0 == 5: distortion = value0 * 2.0
            elif data0 == 6: env_depth = value0 * 8000.0
            elif data0 == 7: amp_a = 0.001 + value0 * 2.0
            elif data0 == 8: amp_d = 0.05 + value0 * 3.0
            elif data0 == 9: amp_s = value0
            elif data0 == 10: amp_r = 0.01 + value0 * 4.0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
