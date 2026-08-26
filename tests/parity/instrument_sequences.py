"""Deterministic event scripts the instrument parity probes replay.

Both probes - the one driving the original vstaudio scripts and the one driving
the ported `audioinstruments` modules - read their sequence from here, so any
divergence in rendered PCM is a divergence in the instrument, not in how it was
played.

Every value sits on the 7-bit MIDI grid. The old side sends `value / 127.0` for
the same integers the new side passes to `set_macro()`, so the two paths reduce
to the identical float before either instrument sees it.

Operations:
    ("on", pitch, velocity)             ("off", pitch)
    ("on", pitch, velocity, detune)     ("macro", index, value)
    ("pc", index)                       ("pull", blocks)
    ("cpress", value)                   ("ppress", pitch, value)
"""

#: Drum machines, which map fixed percussion voices to note numbers.
DRUMS = (
    "cr78", "dmx", "drumtraks", "linndrum", "simmons_sdsv", "sp1200",
    "tr606", "tr707", "tr808", "tr909",
)

#: Everything else in the library: synths, keyboards, samplers-as-synths.
MELODIC = (
    "andromeda", "arp2600", "b3", "clavinet", "cp70", "cs80", "cz101", "d50",
    "dx7", "emulator2", "fairlight", "farfisa", "fs1r", "jp8000", "juno106",
    "jupiter8", "k2600", "karplus", "mellotron", "microwave", "minimoog",
    "ms20", "ms2000", "music_easel", "nord_lead", "obxa", "odyssey", "pianet",
    "polysix", "ppg_wave", "prophet5", "prophet_vs", "rhodes", "sh101",
    "solina", "taurus", "tb303", "virus", "vl1", "vox_continental", "vp330",
    "wasp", "wurlitzer",
)

#: Piece-private instruments that ship with the soundtrack.
PRIVATE_AUTOMATA = (
    "acid", "arp_fast", "brass_stabs", "choir", "claps", "fm_bells", "glass",
    "glitch", "hats", "impact", "keys", "kick", "organ", "polyseq", "pump_pad",
    "reese", "riser", "shaker", "snare", "strings", "sub_bass", "supersaw",
    "texture", "toms",
)

PRIVATE_PERIHELION = (
    "arp", "bells", "brass_high", "choir", "hits", "horns", "lead",
    "moog_bass", "pad_glass", "pad_warm", "riser", "shimmer", "strings_high",
    "strings_low", "sub_drone", "timpani",
)

#: Every note any drum machine in the library maps, plus two it does not - the
#: machines with a fallback branch answer those with a noise burst, the ones
#: without stay silent, and both behaviours are worth pinning down.
DRUM_NOTES = (
    35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51,
    54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 69, 70, 75, 82, 33, 90,
)

MELODIC_CHORD = (48, 60, 64, 67)
MACRO_VALUES = (0, 64, 127)
VELOCITIES = (127, 100, 64, 32)

#: Instruments that respond to aftertouch, and which kind they take.
PRESSURE = {
    "cs80": "poly",
    "vl1": "both",
    "odyssey": "channel",
}

def _program_ops(patches):
    """Visit every patch the instrument declares, then return to patch 0.

    Read off the module rather than listed here, so an instrument that gains
    patches gets them exercised without anyone remembering to say so. An
    instrument carrying only the default patch is left alone: create() has
    already applied it, and a redundant program change would only churn every
    golden the day the first one is added.
    """
    extra = tuple(index for index in sorted(patches) if index != 0)
    return (extra + (0,)) if extra else ()


def _drum_ops(name, macro_count):
    ops = []
    for note in DRUM_NOTES:
        ops.append(("on", note, 100))
        ops.append(("pull", 2))
        ops.append(("off", note))
        ops.append(("pull", 1))
    for velocity in VELOCITIES:
        ops.append(("on", 36, velocity))
        ops.append(("pull", 2))
        ops.append(("off", 36))
        ops.append(("pull", 1))
    # Open hat, then closed hat: the choke has to release the open voice before
    # the closed one speaks, and the ordering is easy to break in a port.
    ops.append(("on", 46, 110))
    ops.append(("pull", 1))
    ops.append(("on", 42, 110))
    ops.append(("pull", 3))
    ops.append(("off", 42))
    ops.append(("off", 46))
    ops.append(("pull", 2))
    for index in range(macro_count):
        for value in MACRO_VALUES:
            ops.append(("macro", index, value))
            ops.append(("on", 36, 100))
            ops.append(("pull", 2))
            ops.append(("off", 36))
            ops.append(("pull", 1))
    return ops


def _melodic_ops(name, macro_count, patches=(0,)):
    ops = []
    for pitch in MELODIC_CHORD:
        ops.append(("on", pitch, 100))
    ops.append(("pull", 8))
    for pitch in MELODIC_CHORD:
        ops.append(("off", pitch))
    ops.append(("pull", 6))

    # Fractional pitch: ~50 instruments read the detune field.
    ops.append(("on", 60, 96, 0.5))
    ops.append(("pull", 4))
    ops.append(("off", 60))
    ops.append(("pull", 2))

    for velocity in VELOCITIES:
        ops.append(("on", 55, velocity))
        ops.append(("pull", 3))
        ops.append(("off", 55))
        ops.append(("pull", 2))

    kind = PRESSURE.get(name)
    if kind in ("poly", "both"):
        ops.append(("on", 60, 100))
        ops.append(("pull", 2))
        for value in MACRO_VALUES:
            ops.append(("ppress", 60, value))
            ops.append(("pull", 2))
        ops.append(("off", 60))
        ops.append(("pull", 2))
    if kind in ("channel", "both"):
        ops.append(("on", 62, 100))
        ops.append(("pull", 2))
        for value in MACRO_VALUES:
            ops.append(("cpress", value))
            ops.append(("pull", 2))
        ops.append(("off", 62))
        ops.append(("pull", 2))

    for index in _program_ops(patches):
        ops.append(("pc", index))
        for pitch in MELODIC_CHORD:
            ops.append(("on", pitch, 100))
        ops.append(("pull", 4))
        for pitch in MELODIC_CHORD:
            ops.append(("off", pitch))
        ops.append(("pull", 2))

    for index in range(macro_count):
        for value in MACRO_VALUES:
            ops.append(("macro", index, value))
            ops.append(("on", 60, 100))
            ops.append(("pull", 3))
            ops.append(("off", 60))
            ops.append(("pull", 1))
    return ops


def build(name, macro_count, patches=(0,)):
    """Return the operation list for ``name``.

    ``macro_count`` and ``patches`` come from each side's own source of truth,
    so a mismatch between the two shows up as a PCM difference rather than
    being papered over here."""
    if name in DRUMS:
        return tuple(_drum_ops(name, macro_count))
    return tuple(_melodic_ops(name, macro_count, patches))


#: Transport readings served to instruments that tempo-sync, one per pull.
#: 96 bpm in 4/4, advancing a 256-frame block at 48 kHz each time.
def transport_at(pull_index):
    seconds = pull_index * 256 / 48000.0
    return (True, seconds, 96.0, 4, 4)
