"""Roland TR-808 Rhythm Composer."""

MACRO_LABELS = (
    "Level", "Accent", "BD Tune", "BD Decay", "BD Tone", "SD Tune",
    "SD Snappy", "SD Tone", "Low Tom", "Mid Tom", "Hi Tom", "Clap Decay",
    "Cowbell", "Cymbal Decay", "CH Decay", "OH Decay",
)

# Patch 0 is the sound this instrument's defaults describe, so a fresh
# instance and patch 0 are the same thing - create() applies it. A macro a
# caller does not set resolves here rather than to the middle of its range.
PATCHES = {
    0: ("Init", (102, 64, 51, 59, 67, 56, 64, 64, 74, 71, 71, 67, 68, 76,
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
    (56, "Cowbell"),
    (75, "Claves"),
)

import synthio

from audioinstruments._support import (
    EVENT_NOTE_ON, EVENT_NOTE_OFF, EVENT_PARAMETER,
    FALL, Instrument, key_of, logmap, make_table, noise_table,
)
from audioinstruments import _support

SINE = make_table(((1, 1.0),))
TRIANGLE = make_table([(n, (1.0 / (n*n)) * (-1)**((n-1)//2)) for n in range(1, 11, 2)])
SQUARE = make_table([(n, 1.0 / n) for n in range(1, 23, 2)])
NOISE = noise_table(seed=808080)

# The real 808's hi-hats/cymbals come from six square-wave oscillators mixed
# together, not noise - build that same inharmonic square bank here (ratios
# approximate the real circuit's ~205/304/369/421/497/619 Hz bank) and drive
# each partial with a few of its own odd harmonics for square-wave grit.
_METAL_TONES = ((10, 1.0), (15, 0.85), (18, 0.75), (21, 0.65), (24, 0.55), (30, 0.45))
_METAL_PARTS = [(m * h, a * (1.0 / h)) for m, a in _METAL_TONES for h in (1, 3, 5)]
METAL = make_table(_METAL_PARTS, length=2048)
METAL_HZ = 90.0


def create(sample_rate, transport=None):
    SR = sample_rate
    NOISE_HZ = SR / 8192.0

    synth = synthio.Synthesizer(sample_rate=SR, channel_count=2)

    # Master params
    master_level = 0.8
    accent_level = 0.5

    # BD params
    bd_tune = 50.0
    bd_decay = 0.4
    bd_tone = 300.0

    # SD params
    sd_tune = 180.0
    sd_snappy = 0.5
    sd_tone = 2000.0

    # Toms
    lt_tune = 90.0
    mt_tune = 130.0
    ht_tune = 180.0

    # Others
    clap_decay = 0.3
    cowbell_tune = 800.0
    cym_decay = 0.8
    ch_decay = 0.05
    oh_decay = 0.4

    voices = {}
    serial = 0
    open_hat_keys = []
    MAX_VOICES = 16

    def release_voice(k):
        voice = voices.pop(k, None)
        if voice is not None:
            for note in voice[0]:
                synth.release(note)

    def steal_oldest():
        _support.steal_oldest(voices, release_voice)

    def trigger_voice(k, notes):
        nonlocal serial
        serial = _support.trigger_voice(voices, synth, serial, MAX_VOICES,
                                        release_voice, k, notes)

    def handle_event(event_type, channel, note_id, data0, value0, value1, sample_position):
        nonlocal master_level, accent_level, bd_tune, bd_decay, bd_tone
        nonlocal sd_tune, sd_snappy, sd_tone, lt_tune, mt_tune, ht_tune
        nonlocal clap_decay, cowbell_tune, cym_decay, ch_decay, oh_decay

        k = key_of(channel, note_id, data0)

        if event_type == EVENT_NOTE_ON and value0 > 0.0:
            pitch = data0
            vel = value0
            amp = master_level * (vel + accent_level * (1.0 if vel > 0.8 else 0.0))

            notes_to_play = []

            # BD (35, 36)
            if pitch in (35, 36):
                env = synthio.Envelope(attack_time=0.001, decay_time=bd_decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=20.0, scale=0.5, interpolate=True)
                lp = synthio.Biquad(synthio.FilterMode.LOW_PASS, bd_tone, Q=0.8)
                note = synthio.Note(bd_tune, waveform=SINE, envelope=env, filter=lp, amplitude=amp, bend=drop)

                click_env = synthio.Envelope(attack_time=0.001, decay_time=0.01, release_time=0.01, attack_level=1.0, sustain_level=0.0)
                click_hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 3000.0, Q=0.7)
                click = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=click_env, filter=click_hp, amplitude=amp * 0.5)

                notes_to_play.extend([note, click])

            # SD (38, 40)
            elif pitch in (38, 40):
                body_env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=30.0, scale=0.2, interpolate=True)
                body1 = synthio.Note(sd_tune, waveform=SINE, envelope=body_env, amplitude=amp*0.8, bend=drop)
                body2 = synthio.Note(sd_tune * 1.8, waveform=SINE, envelope=body_env, amplitude=amp*0.4, bend=drop)

                snare_env = synthio.Envelope(attack_time=0.001, decay_time=0.2, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                snare_bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, sd_tone, Q=1.0)
                snare = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=snare_env, filter=snare_bp, amplitude=amp * sd_snappy)

                notes_to_play.extend([body1, body2, snare])

            # Toms (41, 43, 45, 47, 48, 50)
            elif pitch in (41, 43, 45, 47, 48, 50):
                if pitch in (41, 43):
                    tune = lt_tune
                elif pitch in (45, 47):
                    tune = mt_tune
                else:
                    tune = ht_tune

                env = synthio.Envelope(attack_time=0.001, decay_time=0.3, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                drop = synthio.LFO(waveform=FALL, once=True, rate=15.0, scale=0.1, interpolate=True)
                note = synthio.Note(tune, waveform=SINE, envelope=env, amplitude=amp, bend=drop)
                notes_to_play.append(note)

            # Hats (42, 44, 46)
            elif pitch in (42, 44, 46):
                is_open = pitch == 46
                if not is_open:
                    for ok in open_hat_keys:
                        release_voice(ok)
                    open_hat_keys.clear()

                env = synthio.Envelope(attack_time=0.001, decay_time=oh_decay if is_open else ch_decay, release_time=0.05, attack_level=1.0, sustain_level=0.0)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 8000.0, Q=0.8)
                note = synthio.Note(METAL_HZ, waveform=METAL, envelope=env, filter=hp, amplitude=amp * 0.7)
                notes_to_play.append(note)
                if is_open:
                    open_hat_keys.append(k)

            # Cymbal (49, 51, 57, 59)
            elif pitch in (49, 51, 57, 59):
                env = synthio.Envelope(attack_time=0.001, decay_time=cym_decay, release_time=0.2, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 6000.0, Q=0.5)
                hp = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 9000.0, Q=0.7)
                note = synthio.Note(METAL_HZ, waveform=METAL, envelope=env, filter=bp, amplitude=amp * 0.6)
                note2 = synthio.Note(METAL_HZ, waveform=METAL, envelope=env, filter=hp, amplitude=amp * 0.4)
                notes_to_play.extend([note, note2])

            # Clap (39)
            elif pitch == 39:
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1200.0, Q=1.0)
                for i, attack in enumerate([0.001, 0.015, 0.03]):
                    env = synthio.Envelope(attack_time=attack, decay_time=clap_decay, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                    notes_to_play.append(synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=amp * (1.0 - i*0.2)))

            # Cowbell (56)
            elif pitch == 56:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.4, release_time=0.1, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 2500.0, Q=1.5)
                note1 = synthio.Note(cowbell_tune, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(cowbell_tune * 1.48, waveform=SQUARE, envelope=env, filter=bp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Rimshot (37)
            elif pitch == 37:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.05, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 1600.0, Q=2.0)
                note1 = synthio.Note(450.0, waveform=TRIANGLE, envelope=env, filter=bp, amplitude=amp * 0.5)
                note2 = synthio.Note(1600.0, waveform=TRIANGLE, envelope=env, filter=bp, amplitude=amp * 0.5)
                notes_to_play.extend([note1, note2])

            # Claves (75)
            elif pitch == 75:
                env = synthio.Envelope(attack_time=0.001, decay_time=0.08, release_time=0.02, attack_level=1.0, sustain_level=0.0)
                bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 2500.0, Q=3.0)
                note = synthio.Note(2500.0, waveform=SINE, envelope=env, filter=bp, amplitude=amp)
                notes_to_play.append(note)

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
            elif data0 == 1: accent_level = value0
            elif data0 == 2: bd_tune = logmap(value0, 40.0, 70.0)
            elif data0 == 3: bd_decay = logmap(value0, 0.1, 2.0)
            elif data0 == 4: bd_tone = logmap(value0, 100.0, 800.0)
            elif data0 == 5: sd_tune = logmap(value0, 120.0, 300.0)
            elif data0 == 6: sd_snappy = value0
            elif data0 == 7: sd_tone = logmap(value0, 1000.0, 4000.0)
            elif data0 == 8: lt_tune = logmap(value0, 60.0, 120.0)
            elif data0 == 9: mt_tune = logmap(value0, 100.0, 160.0)
            elif data0 == 10: ht_tune = logmap(value0, 140.0, 220.0)
            elif data0 == 11: clap_decay = logmap(value0, 0.1, 0.8)
            elif data0 == 12: cowbell_tune = logmap(value0, 500.0, 1200.0)
            elif data0 == 13: cym_decay = logmap(value0, 0.2, 2.0)
            elif data0 == 14: ch_decay = logmap(value0, 0.02, 0.15)
            elif data0 == 15: oh_decay = logmap(value0, 0.1, 0.8)

    instrument = Instrument(synth, handle_event, PATCHES, MACRO_LABELS,
                            transport=transport, note_map=NOTE_MAP)
    instrument.program_change(0)
    return instrument
