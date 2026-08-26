"""Convert the drum machines, with the voice maps read off their dispatch."""
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
}

only = sys.argv[1:] or list(MACHINES)
for name in only:
    spec = MACHINES[name]
    text = convert(OLD / (name + ".py"),
                   note_map=spec["note_map"],
                   docstring=spec["docstring"],
                   fast=spec.get("fast"))
    (NEW / (name + ".py")).write_text(text)
    print("wrote %s (%d lines)" % (name, text.count("\n")))
