"""Roland SH-101."""

MACRO_LABELS = (
    "Volume", "Pulse Width", "Sub-Osc Level", "Cutoff", "Resonance",
    "Env Depth", "Fast Decay", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 64, 102, 94, 18, 64, 19, 64)),
}

import math
import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of,
    make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

def make_pulse_table(duty, length=2048, gain=32000, harmonics=32):
    # Band-limited rectangular pulse via its Fourier series so the duty cycle
    # actually reshapes the harmonic content (true PWM), not just a naive
    # sample-and-hold pulse that would alias badly at pitch.
    parts = [(n, (2.0 / (n * math.pi)) * math.sin(n * math.pi * duty)) for n in range(1, harmonics)]
    return make_table(parts, length, gain, cache=False)

SAW = make_table([(n, 1.0 / n) for n in range(1, 40)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 40, 2)])


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    pw = 0.5
    sub_osc = 0.8
    cutoff_val = 1500.0
    res = 1.0
    env_depth = 3000.0
    fast_decay = 0.2
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 1


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, pw, sub_osc, cutoff_val, res, env_depth, fast_decay, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=0.01, decay_time=fast_decay, release_time=0.1, attack_level=1.0, sustain_level=0.1)

            f_sweep = synthio.LFO(waveform=FALL, once=True, rate=1.0/fast_decay, scale=env_depth, interpolate=True)
            cutoff = synthio.Math(synthio.MathOperation.SUM, cutoff_val, f_sweep, 0.0)

            lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, cutoff, Q=res)

            # SH-101's main VCO is a pulse wave with a real PWM control; rebuild the
            # duty-cycle table per note-on from the current Pulse Width macro.
            duty = 0.05 + pw * 0.9
            pulse_wave = make_pulse_table(duty)
            n1 = synthio.Note(hz, waveform=pulse_wave, envelope=env, filter=lp, amplitude=amp * 0.5)
            n_sub = synthio.Note(hz * 0.5, waveform=SQUARE, envelope=env, filter=lp, amplitude=amp * sub_osc * 0.5)

            serial += 1
            voices[k] = ((n1, n_sub), serial)
            synth.press(n1)
            synth.press(n_sub)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: pw = value0
            elif data0 == 2: sub_osc = value0
            elif data0 == 3: cutoff_val = 50.0 * (100.0 ** value0)
            elif data0 == 4: res = 0.5 + value0 * 3.5
            elif data0 == 5: env_depth = value0 * 6000.0
            elif data0 == 6: fast_decay = 0.05 + value0 * 1.0
            elif data0 == 7: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
