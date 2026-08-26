"""Roland Jupiter-8."""

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "Env Depth", "Cross Mod", "Unison",
    "LFO Rate", "Amp Release", "Amp Attack", "Amp Decay", "Amp Sustain",
    "Filter Attack", "Filter Decay", "Filter Sustain", "HPF Cutoff", "PW",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 108, 25, 64, 0, 0, 31, 16, 1, 15, 64, 1, 15, 38, 1,
                 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table, pulse_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2500.0
    resonance = 1.2
    env_depth = 4000.0
    cross_mod = 0.0
    unison_spread = 0.0
    lfo_rate = 5.0
    release_time = 0.5
    hpf_cutoff = 40.0
    pw = 0.5

    amp_a = 0.01
    amp_d = 0.4
    amp_s = 0.5
    filt_a = 0.01
    filt_d = 0.4
    filt_s = 0.3

    voices = {}
    serial = 0
    MAX_VOICES = 8


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, env_depth, cross_mod, unison_spread, lfo_rate, release_time
        nonlocal amp_a, amp_d, amp_s, filt_a, filt_d, filt_s, hpf_cutoff, pw
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1)
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=release_time, attack_level=1.0, sustain_level=amp_s)

            env_tbl = env_shape_table(filt_a, filt_d, filt_s)
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, filt_a + filt_d), scale=env_depth, interpolate=True)
            # LFO Rate: Jupiter-8's LFO can route to the VCF; give it a modest fixed depth here
            # since there's no separate LFO depth macro.
            filt_lfo = synthio.LFO(rate=lfo_rate, scale=250.0)

            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, filt_lfo)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)

            pw_wave = pulse_table(0.1 + pw * 0.8)

            # Jupiter 8 Unison creates massive sound
            if unison_spread > 0.01:
                o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.3, panning=-0.5)
                o2 = synthio.Note(hz * (1.0 + unison_spread * 0.012), waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.3, panning=0.5)
                o3 = synthio.Note(hz * (1.0 - unison_spread * 0.012), waveform=pw_wave, envelope=env, filter=lp, amplitude=amp * 0.3, panning=0.0)
                notes = [o1, o2, o3]
            else:
                o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5)
                # Cross-modulation: synthio can't FM one oscillator's pitch from another's audio
                # signal, so approximate the warbling cross-mod character with a fast sub-audio
                # LFO bending osc2's pitch, scaled by the Cross Mod amount.
                cm_lfo = synthio.LFO(rate=max(20.0, hz * 0.25), scale=cross_mod * 0.4) if cross_mod > 0.01 else None
                o2 = synthio.Note(hz, waveform=pw_wave, envelope=env, filter=lp, amplitude=amp * 0.5, bend=cm_lfo)
                notes = [o1, o2]

            # The Jupiter-8 has no dedicated per-voice HPF; give the macro a real audible effect
            # by mixing in a quiet high-passed top-end layer whose brightness tracks HPF Cutoff
            # (single-filter-per-Note rules out a true series HPF -> VCF chain).
            hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hpf_cutoff, Q=0.7)
            notes.append(synthio.Note(hz, waveform=SAW, envelope=env, filter=hp, amplitude=amp * 0.15))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: env_depth = value0 * 8000.0
            elif data0 == 4: cross_mod = value0 * 2.0
            elif data0 == 5: unison_spread = value0
            elif data0 == 6: lfo_rate = 0.1 + value0 * 20.0
            elif data0 == 7: release_time = 0.01 + value0 * 4.0
            elif data0 == 8: amp_a = 0.001 + value0 * 2.0
            elif data0 == 9: amp_d = 0.05 + value0 * 3.0
            elif data0 == 10: amp_s = value0
            elif data0 == 11: filt_a = 0.001 + value0 * 2.0
            elif data0 == 12: filt_d = 0.05 + value0 * 3.0
            elif data0 == 13: filt_s = value0
            elif data0 == 14: hpf_cutoff = 20.0 + value0 * 2000.0
            elif data0 == 15: pw = value0

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
