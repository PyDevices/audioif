"""Sequential Circuits Prophet-5."""

NAME = 'Prophet-5'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Cutoff", "Resonance", "Env Amount", "Poly Mod",
    "Osc2 Detune", "Sync", "Release", "Amp Attack", "Amp Decay",
    "Amp Sustain", "Filter Attack", "Filter Decay", "Filter Sustain",
    "LFO Rate", "LFO Depth",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 102, 18, 48, 0, 106, 0, 17, 1, 11, 64, 1, 11, 25, 31,
                 0)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, env_shape_table, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    cutoff_base = 2000.0
    resonance = 1.0
    env_amount = 3000.0
    poly_mod = 0.0
    osc2_detune = 1.01
    sync = 0.0
    release_time = 0.4

    amp_a = 0.01
    amp_d = 0.3
    amp_s = 0.5
    filt_a = 0.01
    filt_d = 0.3
    filt_s = 0.2

    lfo_rate = 5.0
    lfo_depth = 0.0

    voices = {}
    serial = 0
    MAX_VOICES = 5


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, cutoff_base, resonance, env_amount, poly_mod, osc2_detune, sync, release_time
        nonlocal amp_a, amp_d, amp_s, filt_a, filt_d, filt_s, lfo_rate, lfo_depth
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
            f_sweep = synthio.LFO(waveform=env_tbl, once=True, rate=1.0/max(0.01, filt_a + filt_d), scale=env_amount, interpolate=True)

            lfo = synthio.LFO(rate=lfo_rate, scale=lfo_depth * 1000.0)

            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_base, f_sweep, lfo)
            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=resonance)

            o1 = synthio.Note(hz, waveform=SAW, envelope=env, filter=lp, amplitude=amp * 0.5)
            # Poly Mod: filter env routed to osc B frequency, approximated as a static detune offset.
            # Keep the offset small - at 0.1 a half-open Poly Mod moved osc B by 91 cents, which
            # swamped the Osc2 Detune control entirely and left the oscillator plainly out of tune.
            actual_detune = osc2_detune * (1.0 + poly_mod * 0.01)
            # Oscillator Sync: synthio can't hard-reset osc2's phase from osc1 at audio rate, so
            # approximate the characteristic sync timbre by snapping osc2 toward an integer multiple
            # of osc1's frequency (the buzzy, harmonically-locked sound sync produces) and brightening
            # its waveform as sync increases.
            if sync > 0.01:
                ratio = round(actual_detune)
                if ratio < 1:
                    ratio = 1
                sync_detune = actual_detune + (ratio - actual_detune) * sync
                o2_wave = SAW
            else:
                sync_detune = actual_detune
                o2_wave = SQUARE
            o2 = synthio.Note(hz * sync_detune, waveform=o2_wave, envelope=env, filter=lp, amplitude=amp * 0.5)

            serial += 1
            voices[k] = ((o1, o2), serial)
            synth.press(o1)
            synth.press(o2)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: cutoff_base = 50.0 * (100.0 ** value0)
            elif data0 == 2: resonance = 0.5 + value0 * 3.5
            elif data0 == 3: env_amount = value0 * 8000.0
            elif data0 == 4: poly_mod = value0
            elif data0 == 5: osc2_detune = 1.0 + (value0 - 0.5) * 0.03
            elif data0 == 6: sync = value0
            elif data0 == 7: release_time = 0.01 + value0 * 3.0
            elif data0 == 8: amp_a = 0.001 + value0 * 2.0
            elif data0 == 9: amp_d = 0.05 + value0 * 3.0
            elif data0 == 10: amp_s = value0
            elif data0 == 11: filt_a = 0.001 + value0 * 2.0
            elif data0 == 12: filt_d = 0.05 + value0 * 3.0
            elif data0 == 13: filt_s = value0
            elif data0 == 14: lfo_rate = 0.1 + value0 * 20.0
            elif data0 == 15: lfo_depth = value0

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
