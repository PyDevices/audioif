"""EDP Wasp."""

NAME = 'wasp'
DISPLAY_NAME = 'Wasp'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Filter Mode", "Cutoff", "Resonance", "Noise Level",
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
    9: "BIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Default', (102, 0, 102, 17, 0, 38, 55, 64, 72, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, logmap, make_table,
    noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

NOISE = noise_table(seed=1234)
# The Wasp's two VCOs are digital (CMOS) square-wave oscillators, not analog saws -
# odd harmonics only gives the thin, buzzy character real to the hardware.
WAVE_DIGI = make_table([(n, 1.0 / n) for n in range(1, 40, 2)], fast=False)


def create(sample_rate, channel_count=2, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=channel_count)

    # Macros
    volume = 0.8
    filter_mode = 0.0 # 0=LP, 1=HP
    cutoff_val = 2000.0
    res = 1.5
    noise_lvl = 0.0
    amp_a = 0.01
    amp_d = 0.3
    amp_s = 0.5
    amp_r = 0.3
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, filter_mode, cutoff_val, res, noise_lvl
        nonlocal amp_a, amp_d, amp_s, amp_r, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            # Real Wasp filter is a 3-position switch (LP/BP/HP), not a 2-way toggle.
            if filter_mode < 0.33:
                fm = synthio.FilterMode.LOW_PASS
            elif filter_mode < 0.66:
                fm = synthio.FilterMode.BAND_PASS
            else:
                fm = synthio.FilterMode.HIGH_PASS
            flt = synthio.Biquad(fm, cutoff_val, Q=res)

            notes = []
            # Two digital square VCOs, detuned, for the raw doubled-oscillator Wasp tone.
            notes.append(synthio.Note(hz, waveform=WAVE_DIGI, envelope=env, filter=flt, amplitude=amp * 0.45))
            notes.append(synthio.Note(hz * 1.007, waveform=WAVE_DIGI, envelope=env, filter=flt, amplitude=amp * 0.45))

            if noise_lvl > 0.01:
                notes.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=flt, amplitude=amp * noise_lvl * 0.2))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: filter_mode = value0
            elif data0 == 2: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 3: res = 0.5 + value0 * 7.5 # pushes into self-oscillation like the real unstable filter
            elif data0 == 4: noise_lvl = value0
            # Time is heard as a ratio, so these travel logarithmically:
            # the steps crowd into the fast end, where a few milliseconds
            # change the articulation, instead of stepping over it.
            elif data0 == 5: amp_a = logmap(value0, 0.001, 2.001)
            elif data0 == 6: amp_d = logmap(value0, 0.05, 3.05)
            elif data0 == 7: amp_s = value0
            elif data0 == 8: amp_r = logmap(value0, 0.01, 4.01)
            elif data0 == 9: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    return instrument
