"""Roland Juno-106."""

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "Sub Level", "Noise Level",
    "Chorus Depth", "Chorus Rate", "HPF", "PWM Amount", "LFO Rate",
    "Env Depth", "Amp Attack", "Amp Decay", "Amp Sustain", "Amp Release",
    "Filter Decay",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 102, 25, 64, 0, 64, 23, 3, 64, 31, 48, 1, 11, 64, 9,
                 11)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table, noise_table, pulse_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])
NOISE = noise_table(seed=1234567)
SINE = make_table(((1, 1.0),))


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2000.0
    resonance = 1.2
    sub_level = 0.5
    noise_level = 0.0
    chorus_depth = 0.5
    chorus_rate = 1.0
    hpf_cutoff = 40.0
    pwm_amount = 0.5
    lfo_rate = 5.0
    env_depth = 3000.0

    amp_a = 0.01
    amp_d = 0.3
    amp_s = 0.5
    amp_r = 0.3
    filt_d = 0.3

    voices = {}
    serial = 0
    MAX_VOICES = 6


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, sub_level, noise_level, chorus_depth, chorus_rate
        nonlocal hpf_cutoff, pwm_amount, lfo_rate, env_depth, amp_a, amp_d, amp_s, amp_r, filt_d
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1)
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=amp_d, release_time=amp_r, attack_level=1.0, sustain_level=amp_s)

            # LFO Rate: the Juno-106's LFO can route to the VCF (via the LFO->VCF slider), so
            # give it a modest fixed depth here since there's no separate LFO depth macro.
            filt_lfo = synthio.LFO(rate=lfo_rate, scale=150.0)
            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/filt_d, scale=env_depth, interpolate=True)

            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, filt_lfo)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)
            # The real HPF sits in series before the resonant VCF on the whole mix; synthio only
            # allows one filter per Note, so approximate it by high-passing the bass-heavy
            # sub-oscillator and noise layers directly (thinning bass as cutoff rises, same
            # audible direction as the real control).
            hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, hpf_cutoff, Q=0.7)

            # Chorus: the Juno-106's BBD ensemble effect is an animated pitch wobble, not just
            # stereo width, so add a slow bend LFO (Chorus Rate) on top of the static spread.
            chorus_lfo = synthio.LFO(waveform=SINE, rate=chorus_rate, scale=chorus_depth * 0.006) if chorus_depth > 0.01 else None
            detune = chorus_depth * 0.01
            pwm_wave = pulse_table(0.5 - pwm_amount * 0.4)

            o_saw = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.4, panning=-chorus_depth, bend=chorus_lfo)
            o_sq = synthio.Note(hz * (1.0 + detune), waveform=pwm_wave, envelope=env, filter=lp, amplitude=amp * 0.4, panning=chorus_depth, bend=chorus_lfo)
            o_sub = synthio.Note(hz * 0.5, waveform=SQUARE, envelope=env, filter=hp, amplitude=amp * sub_level * 0.4, panning=0.0)
            n = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * noise_level * 0.2)

            notes = [o_saw, o_sq, o_sub]
            if noise_level > 0.01:
                notes.append(n)

            serial += 1
            voices[k] = (tuple(notes), serial)
            for note in notes:
                synth.press(note)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: sub_level = value0
            elif data0 == 4: noise_level = value0
            elif data0 == 5: chorus_depth = value0
            elif data0 == 6: chorus_rate = 0.1 + value0 * 5.0
            elif data0 == 7: hpf_cutoff = 20.0 + value0 * 1000.0
            elif data0 == 8: pwm_amount = value0
            elif data0 == 9: lfo_rate = 0.1 + value0 * 20.0
            elif data0 == 10: env_depth = value0 * 8000.0
            elif data0 == 11: amp_a = 0.001 + value0 * 2.0
            elif data0 == 12: amp_d = 0.05 + value0 * 3.0
            elif data0 == 13: amp_s = value0
            elif data0 == 14: amp_r = 0.01 + value0 * 4.0
            elif data0 == 15: filt_d = 0.05 + value0 * 3.0

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
