"""What the converter cannot read off an instrument script for itself.

Everything mechanical is in port_instrument.py. This is the residue: the
one-line description each module gets as its docstring, the voice map for the
drum machines, and the handful of per-instrument flags below.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from port_instrument import convert

_ROOT = Path(__file__).resolve().parents[1]
OLD = _ROOT.parent / "micropython-vst3" / "lib" / "instruments"
NEW = _ROOT / "lib" / "audioinstruments"

# fast=False for the machines whose original make_table had no ulab branch:
# switching those to the vectorized sine would move their samples on any
# interpreter that ships ulab, and both of ours do.
MACHINES = {
    "tr909": dict(
        docstring="Roland TR-909 Rhythm Composer.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (37, "Rimshot"),
                  (39, "Clap"), (41, "Low Tom"), (45, "Mid Tom"),
                  (48, "Hi Tom"), (42, "Closed Hat"), (46, "Open Hat"),
                  (49, "Crash"), (51, "Ride")]),
    "tr808": dict(
        docstring="Roland TR-808 Rhythm Composer.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (37, "Rimshot"),
                  (39, "Clap"), (41, "Low Tom"), (45, "Mid Tom"),
                  (48, "Hi Tom"), (42, "Closed Hat"), (46, "Open Hat"),
                  (49, "Cymbal"), (56, "Cowbell"), (75, "Claves")]),
    "tr606": dict(
        docstring="Roland TR-606 Drumatix.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (41, "Low Tom"),
                  (48, "Hi Tom"), (42, "Closed Hat"), (46, "Open Hat"),
                  (49, "Cymbal")]),
    "tr707": dict(
        docstring="Roland TR-707 Rhythm Composer.", fast=False,
        note_map=[(36, "Kick"), (38, "Snare"), (45, "Low Tom"),
                  (47, "Mid Tom"), (50, "Hi Tom"), (42, "Closed Hat"),
                  (46, "Open Hat"), (49, "Crash")]),
    "cr78": dict(
        docstring="Roland CR-78 CompuRhythm.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (37, "Rimshot"),
                  (42, "Closed Hat"), (46, "Open Hat"), (49, "Cymbal"),
                  (54, "Tambourine"), (55, "Metal Beat"), (56, "Cowbell"),
                  (58, "Guiro"), (60, "Bongo Hi"), (61, "Bongo Lo"),
                  (70, "Maracas"), (75, "Claves")]),
    "dmx": dict(
        docstring="Oberheim DMX.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (37, "Rimshot"),
                  (39, "Clap"), (41, "Low Tom"), (45, "Mid Tom"),
                  (48, "Hi Tom"), (42, "Closed Hat"), (46, "Open Hat"),
                  (49, "Cymbal"), (54, "Tambourine"), (56, "Cowbell"),
                  (70, "Shaker")]),
    "linndrum": dict(
        docstring="Linn LinnDrum.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (37, "Rimshot"),
                  (39, "Clap"), (41, "Low Tom"), (45, "Mid Tom"),
                  (48, "Hi Tom"), (42, "Closed Hat"), (46, "Open Hat"),
                  (49, "Cymbal"), (54, "Tambourine"), (56, "Cowbell"),
                  (62, "Conga Hi"), (63, "Conga Mid"), (64, "Conga Lo"),
                  (69, "Cabasa")]),
    "simmons_sdsv": dict(
        docstring="Simmons SDS-V.",
        note_map=[(36, "Bass Drum"), (38, "Snare"), (41, "Low Tom"),
                  (45, "Mid Tom"), (48, "Hi Tom"), (42, "Closed Hat"),
                  (46, "Open Hat"), (49, "Cymbal")]),
    "drumtraks": dict(
        docstring="Sequential Circuits Drumtraks.", fast=False,
        note_map=[(36, "Kick"), (38, "Snare"), (45, "Low Tom"),
                  (47, "Mid Tom"), (50, "Hi Tom"), (42, "Closed Hat"),
                  (46, "Open Hat")]),
    "sp1200": dict(
        docstring="E-mu SP-1200.", fast=False,
        note_map=[(36, "Kick"), (38, "Snare"), (42, "Closed Hat"),
                  (46, "Open Hat")]),

    # --- melodic -----------------------------------------------------------
    "andromeda": dict(docstring="Alesis Andromeda A6."),
    "arp2600": dict(docstring="ARP 2600.", release="filtered"),
    "b3": dict(docstring="Hammond B-3 tonewheel organ.", fast=False),
    "clavinet": dict(docstring="Hohner Clavinet D6.", fast=False),
    "cp70": dict(docstring="Yamaha CP-70 electric grand.", fast=False),
    "cs80": dict(docstring="Yamaha CS-80."),
    "cz101": dict(docstring="Casio CZ-101 phase distortion synthesizer.",
                  fast=False),
    "d50": dict(docstring="Roland D-50 linear synthesizer.", fast=False),
    "dx7": dict(docstring="Yamaha DX7.", fast=False),
    "emulator2": dict(docstring="E-mu Emulator II.", fast=False),
    "fairlight": dict(docstring="Fairlight CMI.", fast=False),
    "farfisa": dict(docstring="Farfisa Compact combo organ.", fast=False),
    "fs1r": dict(docstring="Yamaha FS1R formant synthesizer.", fast=False),
    "jp8000": dict(docstring="Roland JP-8000."),
    "juno106": dict(docstring="Roland Juno-106."),
    "jupiter8": dict(docstring="Roland Jupiter-8."),
    "k2600": dict(docstring="Kurzweil K2600."),
    # Its string table is sized from the sample rate at the moment a note
    # is played, so the builder belongs to the instance, not the module.
    "karplus": dict(docstring="Plucked string, Karplus-Strong style.",
                    into_create=["karplus_strong_table"]),
    "mellotron": dict(docstring="Mellotron M400.", fast=False),
    "microwave": dict(docstring="Waldorf Microwave.", fast=False),
    # The one script that registered handle_event itself and answered program
    # changes inline; Instrument does both now, so that branch comes out.
    "minimoog": dict(
        docstring="Moog Minimoog Model D.",
        replacements=[("""
        elif event_type == EVENT_PROGRAM_CHANGE:
            patch = PATCHES.get(data0)
            if patch is not None:
                for macro_index, macro_value in enumerate(patch[1]):
                    handle_event(EVENT_PARAMETER, channel, note_id,
                                 macro_index, macro_value, 0.0, sample_position)
""", "")]),
    "ms20": dict(docstring="Korg MS-20.", release="filtered"),
    "ms2000": dict(docstring="Korg MS2000.", fast=False),
    "music_easel": dict(docstring="Buchla Music Easel.", fast=False),
    "nord_lead": dict(docstring="Clavia Nord Lead."),
    "obxa": dict(docstring="Oberheim OB-Xa.", fast=False),
    "odyssey": dict(docstring="ARP Odyssey."),
    "pianet": dict(docstring="Hohner Pianet.", fast=False),
    "polysix": dict(docstring="Korg Polysix.", fast=False),
    "ppg_wave": dict(docstring="PPG Wave 2.2.", fast=False),
    "prophet5": dict(docstring="Sequential Circuits Prophet-5."),
    # Its filter release applies to every note in the voice, where the other
    # two filter a subset; saying so in the voice tuple lets all three share
    # one release.
    "prophet_vs": dict(
        docstring="Sequential Circuits Prophet VS vector synthesizer.",
        fast=False, release="filtered",
        replacements=[("voices[k] = (tuple(notes), serial, filt_release)",
                       "voices[k] = (tuple(notes), serial, filt_release,\n"
                       "                       tuple(notes))")]),
    # A real Rhodes thumps when the damper drops back onto the tine, so its
    # release makes a sound of its own - including when a voice is stolen,
    # which is why it hangs off the release rather than off note-off.
    "rhodes": dict(
        docstring="Fender Rhodes electric piano.", fast=False,
        release="""def release_voice(k):
    voice = _support.release_voice(voices, synth, k)
    if voice is not None and key_off > 0.01:
        env = synthio.Envelope(attack_time=0.001, decay_time=0.1, release_time=0.1, attack_level=1.0, sustain_level=0.0)
        bp = synthio.Biquad(synthio.FilterMode.BAND_PASS, 500.0, Q=1.0)
        n = synthio.Note(NOISE_HZ, waveform=NOISE, envelope=env, filter=bp, amplitude=volume * key_off * 0.2)
        synth.press(n)
        synth.release(n)  # let the envelope play out
"""),
    # make_pulse_table follows the PWM macro, so its tables must not be cached.
    "sh101": dict(
        docstring="Roland SH-101.",
        replacements=[("return make_table(parts, length, gain)",
                       "return make_table(parts, length, gain, cache=False)")]),
    "solina": dict(docstring="ARP/Eminent Solina String Ensemble.", fast=False),
    "taurus": dict(docstring="Moog Taurus bass pedals.", fast=False),
    "tb303": dict(docstring="Roland TB-303 Bass Line.", fast=False),
    "virus": dict(docstring="Access Virus.", fast=False),
    "vl1": dict(docstring="Yamaha VL1 physical modelling synthesizer.",
                fast=False),
    "vox_continental": dict(docstring="Vox Continental combo organ.",
                            fast=False),
    "vp330": dict(docstring="Roland VP-330 Vocoder Plus.", fast=False),
    "wasp": dict(docstring="EDP Wasp.", fast=False),
    "wurlitzer": dict(docstring="Wurlitzer 200A electric piano.", fast=False),
}

only = sys.argv[1:] or list(MACHINES)
for name in only:
    spec = MACHINES[name]
    text = convert(OLD / (name + ".py"),
                   note_map=spec.get("note_map"),
                   docstring=spec["docstring"],
                   fast=spec.get("fast"),
                   release=spec.get("release"),
                   replacements=spec.get("replacements", ()),
                   into_create=spec.get("into_create", ()))
    (NEW / (name + ".py")).write_text(text)
    print("wrote %s (%d lines)" % (name, text.count("\n")))
