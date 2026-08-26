"""Linn LinnDrum."""

MACRO_LABELS = (
    "Level", "BD Pitch", "BD Decay", "SD Pitch", "SD Snappy", "Rim Pitch",
    "Clap Decay", "LT Pitch", "MT Pitch", "HT Pitch", "Conga Pitch",
    "Cowbell", "Tambourine", "Cabasa", "CH Decay", "OH Decay",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro
# a caller does not set resolves here rather than to the middle of its
# range.
PATCHES = {
    0: ('Init', (102, 67, 69, 64, 76, 80, 67, 77, 73, 67, 72, 68, 102, 102,
                 58, 85)),
}

NOTE_MAP = (
    (36, "Bass Drum"),
    (38, "Snare"),
    (37, "Rimshot"),
    (39, "Clap"),
    (41, "Low Tom"),
    (45, "Mid Tom"),
    (48, "Hi Tom"),
    (42, "Closed Hat"),
    (46, "Open Hat"),
    (49, "Cymbal"),
    (54, "Tambourine"),
    (56, "Cowbell"),
    (62, "Conga Hi"),
    (63, "Conga Mid"),
    (64, "Conga Lo"),
    (69, "Cabasa"),
)

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER, FALL, key_of, logmap,
    make_table, noise_table,
)
from audioinstruments._support import Instrument
from audioinstruments import _support

SINE = make_table(((1, 1.0), (2, 0.2)))
TRIANGLE = make_table([(n, (1.0 / (n*n)) * (-1)**((n-1)//2)) for n in range(1, 11, 2)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 15, 2)])
NOISE = noise_table(seed=13579)


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0
    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Master params
    master_level = 0.8

    # BD
    bd_pitch = 65.0
    bd_decay = 0.35

    # SD
    sd_pitch = 190.0
    sd_snappy = 0.6

    # Rim
    rim_pitch = 800.0

    # Clap
    clap_decay = 0.3

    # Toms
    lt_pitch = 100.0
    mt_pitch = 140.0
    ht_pitch = 190.0

    # Congas
    conga_pitch = 280.0

    # Percussion
    cowbell_pitch = 900.0
    tamb_level = 0.8
    cabasa_level = 0.8

    # Hats
    ch_decay = 0.05
    oh_decay = 0.4

    voices = {}
    serial = 0
    open_hat_keys = []
    MAX_VOICES = 16




    def release_voice(k):
        _support.release_voice(voices, synth, k)


    def steal_oldest():
        _support.steal_oldest(voices, release_voice)


    def trigger_voice(k, notes):
        nonlocal serial
        serial = _support.trigger_voice(voices, synth, serial, MAX_VOICES,
                                        release_voice, k, notes)


    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal master_level, bd_pitch, bd_decay, sd_pitch, sd_snappy, rim_pitch, clap_decay
        nonlocal lt_pitch, mt_pitch, ht_pitch, conga_pitch
        nonlocal cowbell_pitch, tamb_level, cabasa_level, ch_decay, oh_decay

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            amp = master_level * value0

            notes_to_play = []

            # BD (35, 36) - a sampled acoustic kick, not a swept VCO like the analog
            # machines: no deliberate pitch-drop, just the sample's tone plus its
            # short broadband transient thump
            if pitch in (35, 36):
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 4.0, Q=0.8)
                body = synthio.Note(bd_pitch, waveform=SINE, envelope=env, filter=lp, amplitude=amp)
                thump_env = synthio.Envelope(attack_time=0.001, decay_time=0.03, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                thump_lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_pitch * 6.0, Q=0.6)
                thump = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=thump_env, filter=thump_lp, amplitude=amp * 0.35)
                notes_to_play.extend([body, thump])

            # SD (38, 40)
            elif pitch in (38, 40):
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                body = synthio.Note(sd_pitch, waveform=TRIANGLE, envelope=body_env, amplitude=amp * 0.7)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.2, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                snare_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 1200.0, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=snare_env, filter=snare_hp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body, snare])

            # Rimshot (37)
            elif pitch == 37:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, rim_pitch, Q=2.0)
                note = synthio.Note(rim_pitch, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp)
                notes_to_play.append(note)

            # Clap (39)
            elif pitch == 39:
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1400.0, Q=1.0)
                for i, attack in enumerate([0.001, 0.015, 0.03]):
                    env = synthio.Envelope(attack_time=attack, decay_time=clap_decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                    notes_to_play.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * (1.0 - i*0.2)))

            # Toms (41, 43, 45, 47, 48, 50)
            elif pitch in (41, 43, 45, 47, 48, 50):
                if pitch in (41, 43):
                    tune = lt_pitch
                elif pitch in (45, 47):
                    tune = mt_pitch
                else:
                    tune = ht_pitch

                env = synthio.Envelope(attack_time=0.002, decay_time=0.4, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=25.0, scale=0.15, interpolate=True)
                note = synthio.Note(tune, waveform=TRIANGLE, envelope=env, amplitude=amp, bend=drop)
                notes_to_play.append(note)

            # Congas (62, 63, 64)
            elif pitch in (62, 63, 64):
                offset = 1.0 if pitch == 62 else (0.8 if pitch == 63 else 0.6)
                env = synthio.Envelope(attack_time=0.001, decay_time=0.25, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                note = synthio.Note(conga_pitch * offset, waveform=SINE, envelope=env, amplitude=amp * 0.9)
                notes_to_play.append(note)

            # Cowbell (56)
            elif pitch == 56:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, cowbell_pitch * 2.0, Q=1.0)
                note1 = synthio.Note(cowbell_pitch, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(cowbell_pitch * 1.3, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Tambourine (54) & Cabasa (69)
            elif pitch in (54, 69):
                is_tamb = pitch == 54
                a = amp * (tamb_level if is_tamb else cabasa_level)
                env = synthio.Envelope(attack_time=0.001, decay_time=0.15, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 6000.0 if is_tamb else 8000.0, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=a)
                notes_to_play.append(note)

            # Hats (42, 44, 46)
            elif pitch in (42, 44, 46):
                is_open = pitch == 46
                if not is_open:
                    for ok in open_hat_keys:
                        release_voice(ok)
                    open_hat_keys.clear()

                env = synthio.Envelope(attack_time=0.001, decay_time=oh_decay if is_open else ch_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 7000.0, Q=0.8)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)
                if is_open:
                    open_hat_keys.append(k)

            # Cymbals (49, 51, 57, 59)
            elif pitch in (49, 51, 57, 59):
                env = synthio.Envelope(attack_time=0.001, decay_time=1.2, release_time=0.3, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 4500.0, Q=0.5)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 8000.0, Q=0.7)
                note1 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=hp, amplitude=amp * 0.4)
                notes_to_play.extend([note1, note2])

            # Fallback (other percussion)
            else:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 3000.0, Q=1.0)
                note = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * 0.5)
                notes_to_play.append(note)

            if notes_to_play:
                trigger_voice(k, notes_to_play)

        elif event_type in (EVENT_NOTE_OFF, EVENT_NOTE_ON):
            release_voice(k)
            if k in open_hat_keys:
                open_hat_keys.remove(k)

        elif event_type == EVENT_PARAMETER:
            if data0 == 0: master_level = value0
            elif data0 == 1: bd_pitch = logmap(value0, 40.0, 100.0)
            elif data0 == 2: bd_decay = logmap(value0, 0.1, 1.0)
            elif data0 == 3: sd_pitch = logmap(value0, 120.0, 300.0)
            elif data0 == 4: sd_snappy = value0
            elif data0 == 5: rim_pitch = logmap(value0, 400.0, 1200.0)
            elif data0 == 6: clap_decay = logmap(value0, 0.1, 0.8)
            elif data0 == 7: lt_pitch = logmap(value0, 60.0, 140.0)
            elif data0 == 8: mt_pitch = logmap(value0, 100.0, 180.0)
            elif data0 == 9: ht_pitch = logmap(value0, 140.0, 250.0)
            elif data0 == 10: conga_pitch = logmap(value0, 150.0, 450.0)
            elif data0 == 11: cowbell_pitch = logmap(value0, 500.0, 1500.0)
            elif data0 == 12: tamb_level = value0
            elif data0 == 13: cabasa_level = value0
            elif data0 == 14: ch_decay = logmap(value0, 0.02, 0.15)
            elif data0 == 15: oh_decay = logmap(value0, 0.1, 0.8)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    instrument.program_change(0)
    return instrument
