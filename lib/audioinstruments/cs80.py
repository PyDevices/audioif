"""Yamaha CS-80."""

NAME = 'cs80'
DISPLAY_NAME = 'CS-80'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "VCF Cutoff", "Resonance", "HPF Cutoff", "Ring Mod Speed",
    "Ring Mod Depth", "Layer II Mix", "Poly AT Depth", "Amp Attack",
    "Amp Decay", "Amp Sustain", "Amp Release", "Filter Attack",
    "Filter Decay", "Filter Sustain", "Brilliance",
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
    15: "UNIPOLAR",
}

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ("Default", (102, 108, 18, 5, 31, 0, 64, 64, 3, 19, 102, 16, 3, 19, 64,
                 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, EVENT_POLY_PRESSURE,
    env_shape_table, key_of, make_table, ring_depth_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SINE = make_table(((1, 1.0),))


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2500.0
    resonance = 1.0
    hpf_cutoff = 100.0
    ring_speed = 5.0
    ring_depth = 0.0
    layer2_mix = 0.5
    poly_at_depth = 0.5

    amp_a = 0.05
    amp_d = 0.5
    amp_s = 0.8
    amp_r = 0.5
    filt_a = 0.05
    filt_d = 0.5
    filt_s = 0.5
    brilliance = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, hpf_cutoff, ring_speed, ring_depth, layer2_mix
        nonlocal poly_at_depth, amp_a, amp_d, amp_s, amp_r, filt_a, filt_d, filt_s, brilliance
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1)
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            env_tbl = env_shape_table(filt_a, filt_d, filt_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, filt_a + filt_d), scale=2000.0 * brilliance, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, 0.0)

            lp1 = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)
            hp2 = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hpf_cutoff, Q=0.7)

            ring_wave = ring_depth_table(ring_depth) if ring_depth > 0.01 else None

            # Layer I: low-pass voice
            amp1 = amp * (1.0 - layer2_mix) * 0.8
            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp1, amplitude=amp1, ring_frequency=ring_speed * 10.0, ring_waveform=ring_wave)
            # Layer II: slightly detuned, high-pass voice (the CS-80's second layer ran through its own filter)
            amp2 = amp * layer2_mix * 0.8
            o2 = synthio.Note(hz * 1.005, waveform=SAW, envelope=env, filter=hp2, amplitude=amp2, ring_frequency=ring_speed * 10.0, ring_waveform=ring_wave)

            serial += 1
            voices[k] = ((o1, o2), serial, (amp1, amp2))
            synth.press(o1)
            synth.press(o2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_POLY_PRESSURE:
            voice = voices.get(k)
            if voice is not None:
                notes, _, base_amps = voice
                boost = 1.0 + poly_at_depth * value0
                for note, base_amp in zip(notes, base_amps):
                    note.amplitude = base_amp * boost

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: hpf_cutoff = 20.0 + value0 * 2000.0
            elif data0 == 4: ring_speed = 0.1 + value0 * 20.0
            elif data0 == 5: ring_depth = value0
            elif data0 == 6: layer2_mix = value0
            elif data0 == 7: poly_at_depth = value0
            elif data0 == 8: amp_a = 0.001 + value0 * 2.0
            elif data0 == 9: amp_d = 0.05 + value0 * 3.0
            elif data0 == 10: amp_s = value0
            elif data0 == 11: amp_r = 0.01 + value0 * 4.0
            elif data0 == 12: filt_a = 0.001 + value0 * 2.0
            elif data0 == 13: filt_d = 0.05 + value0 * 3.0
            elif data0 == 14: filt_s = value0
            elif data0 == 15: brilliance = value0 * 2.0

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
