"""Roland VP-330 Vocoder Plus."""

NAME = 'VP-330'
CATEGORIES = ('Synth',)
VERSION = '0.0.1'
VENDOR = "PyDevices"

MACRO_LABELS = (
    "Volume", "Male Choir", "Female Choir", "Chorus Depth", "Attack",
    "Release", "Formant Shift", "Vibrato Rate", "Vibrato Depth",
    "Brilliance", "Bass", "Master Tune",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 102, 64, 127, 6, 16, 64, 62, 0, 64, 64, 64)),
}

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, key_of, make_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

# Vocoders use a rich pulse wave as the carrier
PULSE = make_table([(n, 1.0 / n if n % 2 != 0 else 0.5 / n) for n in range(1, 40)], fast=False)
SINE = make_table(((1, 1.0),), fast=False)


def create(sample_rate, transport=None):
    SR = sample_rate
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Macros
    volume = 0.8
    male_mix = 0.8
    female_mix = 0.5
    chorus_depth = 1.0
    amp_a = 0.1
    amp_r = 0.5
    formant_shift = 0.0
    vib_rate = 5.0
    vib_depth = 0.0
    brilliance = 0.5
    bass = 0.5
    master_tune = 1.0

    voices = {}
    serial = 0
    MAX_VOICES = 4 # Heavy filtering per voice


    def release_voice(k):
        _support.release_voice(voices, synth, k)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal volume, male_mix, female_mix, chorus_depth, amp_a, amp_r
        nonlocal formant_shift, vib_rate, vib_depth, brilliance, bass, master_tune
        nonlocal serial

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            release_voice(k)
            if len(voices) >= MAX_VOICES:
                steal_oldest()

            hz = synthio.midi_to_hz(data0 + value1) * master_tune
            amp = volume * value0

            env = synthio.Envelope(attack_time=amp_a, decay_time=0.1, release_time=amp_r, attack_level=1.0, sustain_level=1.0)

            vib_lfo = synthio.LFO(waveform=SINE, rate=vib_rate, scale=vib_depth * 0.02) if vib_depth > 0.01 else None
            ens_lfo = synthio.LFO(waveform=SINE, rate=0.8, scale=chorus_depth * 0.01) if chorus_depth > 0.01 else None

            notes = []

            # Male formants (approx "Ah" / "Oh")
            if male_mix > 0.01:
                f1 = 600.0 * (1.0 + formant_shift)
                f2 = 1200.0 * (1.0 + formant_shift)
                bp1 = synthio.Biquad(synthio.FilterMode.BAND_PASS, f1, Q=4.0)
                bp2 = synthio.Biquad(synthio.FilterMode.BAND_PASS, f2, Q=4.0)

                n1 = synthio.Note(hz, waveform=PULSE, envelope=env, filter=bp1, amplitude=amp * male_mix * 0.4, bend=vib_lfo, panning=-0.3)
                n2 = synthio.Note(hz * 1.002, waveform=PULSE, envelope=env, filter=bp2, amplitude=amp * male_mix * 0.4, bend=ens_lfo, panning=0.3)
                notes.extend([n1, n2])

            # Female formants (approx "Ee" / high "Ah")
            if female_mix > 0.01:
                f1 = 900.0 * (1.0 + formant_shift)
                f2 = 2500.0 * (1.0 + formant_shift)
                bp1 = synthio.Biquad(synthio.FilterMode.BAND_PASS, f1, Q=5.0)
                bp2 = synthio.Biquad(synthio.FilterMode.BAND_PASS, f2, Q=3.0)

                n1 = synthio.Note(hz * 2.0, waveform=PULSE, envelope=env, filter=bp1, amplitude=amp * female_mix * 0.3, bend=vib_lfo, panning=-0.5)
                n2 = synthio.Note(hz * 1.998, waveform=PULSE, envelope=env, filter=bp2, amplitude=amp * female_mix * 0.3, bend=ens_lfo, panning=0.5)
                notes.extend([n1, n2])

            # VP-330's real string/bass section is a separate divide-down organ
            # register under the choir, an octave down with no formant filtering
            if bass > 0.01:
                bp_bass = synthio.Biquad(synthio.FilterMode.LOW_PASS, 900.0, Q=0.9)
                notes.append(synthio.Note(hz * 0.5, waveform=PULSE, envelope=env, filter=bp_bass, amplitude=amp * bass * 0.5))

            # Brilliance is the VP-330's top-end tone control: a bright unfiltered
            # doubling that only becomes audible as it's turned up
            if brilliance > 0.01:
                hp_bright = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 3000.0, Q=0.7)
                notes.append(synthio.Note(hz * 2.0, waveform=PULSE, envelope=env, filter=hp_bright, amplitude=amp * brilliance * 0.25))

            serial += 1
            voices[k] = (tuple(notes), serial)
            for n in notes:
                synth.press(n)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: volume = value0
            elif data0 == 1: male_mix = value0
            elif data0 == 2: female_mix = value0
            elif data0 == 3: chorus_depth = value0
            elif data0 == 4: amp_a = 0.001 + value0 * 2.0
            elif data0 == 5: amp_r = 0.01 + value0 * 4.0
            elif data0 == 6: formant_shift = -0.5 + value0
            elif data0 == 7: vib_rate = 0.1 + value0 * 10.0
            elif data0 == 8: vib_depth = value0
            elif data0 == 9: brilliance = value0
            elif data0 == 10: bass = value0
            elif data0 == 11: master_tune = 0.95 + value0 * 0.1

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport)
    instrument.program_change(0)
    return instrument
