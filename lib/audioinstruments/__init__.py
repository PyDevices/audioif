"""Classic synthesizers, electromechanical keyboards, and drum machines.

Each instrument is a self-contained `synthio` program - no samples - exposing:

    MACRO_LABELS  tuple of names, one per macro parameter
    PATCHES       {index: (name, (macro values, 0-127))}; patch 0 is the sound
                  a freshly created instrument makes
    NOTE_MAP      drum machines only: ((midi_note, label), ...) for the voices
                  the machine actually maps
    create(sample_rate, transport=None) -> Instrument

`transport` is an optional callable returning the host's playback position as
``(playing, seconds, bpm, ts_numerator, ts_denominator)``; instruments that
tempo-sync call it, the rest ignore it.

    import audioinstruments
    inst = audioinstruments.create("tr808", 48000)
    inst.note_on(36)                 # bass drum, full velocity
    inst.set_macro(2, 96)            # BD Tune, MIDI scale
    audio_out.play(inst.output)
"""

import sys

_PKG = __name__

#: The subset of :data:`ALL` that maps drum voices and exports ``NOTE_MAP``.
DRUM_MACHINES = (
    "cr78", "dmx", "drumtraks", "linndrum", "simmons_sdsv", "sp1200",
    "tr606", "tr707", "tr808", "tr909",
)

#: Everything else: synthesizers, organs, and electromechanical keyboards,
#: played by pitch rather than by voice.
MELODIC = (
    "andromeda", "arp2600", "b3", "clavinet", "cp70", "cs80", "cz101", "d50",
    "dx7", "emulator2", "fairlight", "farfisa", "fs1r", "jp8000", "juno106",
    "jupiter8", "k2600", "karplus", "mellotron", "microwave", "minimoog",
    "ms20", "ms2000", "music_easel", "nord_lead", "obxa", "odyssey", "pianet",
    "polysix", "ppg_wave", "prophet5", "prophet_vs", "rhodes", "sh101",
    "solina", "taurus", "tb303", "virus", "vl1", "vox_continental", "vp330",
    "wasp", "wurlitzer",
)

#: Every instrument module in this package.
ALL = DRUM_MACHINES + MELODIC


def load(name):
    """Import and return the instrument module ``name``."""
    full = _PKG + "." + name
    __import__(full)
    return sys.modules[full]


def create(name, sample_rate, transport=None):
    """Load instrument ``name`` and return a live instance of it."""
    return load(name).create(sample_rate, transport=transport)
