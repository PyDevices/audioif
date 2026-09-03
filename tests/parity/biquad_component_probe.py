"""Deterministic biquad PCM probes across every FilterMode.

The rest of the parity suite only ever builds LOW_PASS filters, which is how
the peaking-EQ sign error in `audioif_biquad.c` survived: no fixture reached
mode 4. This probe walks all seven modes in mono and stereo, and then all seven
again across the band, so the three deliberate deviations recorded in
docs/upstream-diff.md ("Peaking EQ computed b2 with the wrong sign", "A stereo
Filter shared one biquad state" and "The biquads are Q15, so they cannot go
low") are each pinned by something that fails when they regress.

Running this against `bin/circuitpython` is expected to differ. That is the
point of it; see docs/upstream-diff.md for the direction of each difference.
"""

from array import array

import audiocore
import audiofilters
import synthio


#: A and Q the shelf/peaking modes need. A is RBJ's amplitude parameter,
#: 10**(gain_db/40) - so 1.4125 is a +6 dB bell rather than a +1.4 dB one.
GAIN_A = 1.4125
Q = 1.0
CENTER = 1200
RATE = 8000

#: Q and A were CONSTANT across all 182 fixtures, so three of the five
#: arguments to audioif_biquad_configure could be hardcoded to the probe's own
#: value without moving the hash - two of them silently untested. Frequency was
#: the one scalar that varied. These sweep them.
Q_VALUES = (0.4, 1.0, 4.0)
A_VALUES = (0.7079, 1.4125)


def checksum(data):
    """FNV-1a over the bytes.

    `sum(data)` is invariant under any permutation of a block and under any set
    of byte deltas that cancel, so 168 of this probe's 182 lines certified 4096
    samples with a statistic that could not see them reordered - demonstrated
    with 90.6% of samples wrong at an identical byte-sum. This is order- and
    magnitude-sensitive; `instruments_probe_new.py:26` uses the same function
    for the same reason. Both are printed: the sum stays comparable with the
    older records, the checksum is what actually pins the PCM.
    """
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value

MODES = (
    ("low_pass", synthio.FilterMode.LOW_PASS),
    ("high_pass", synthio.FilterMode.HIGH_PASS),
    ("band_pass", synthio.FilterMode.BAND_PASS),
    ("notch", synthio.FilterMode.NOTCH),
    ("low_shelf", synthio.FilterMode.LOW_SHELF),
    ("high_shelf", synthio.FilterMode.HIGH_SHELF),
    ("peaking_eq", synthio.FilterMode.PEAKING_EQ),
)


def source(channel_count):
    """Two tones an octave apart, hard-panned when stereo.

    The channels have to differ, or a filter that shares one state across
    them is indistinguishable from one that does not.
    """
    values = array("h")
    for frame in range(768):
        for channel in range(channel_count):
            hz = 300 if channel == 0 else 2400
            phase = 2.0 * 3.141592653589793 * hz * frame / RATE
            # A cheap square-ish shape: deterministic, and rich enough above
            # and below CENTER that every mode has something to act on.
            values.append(12000 if (phase % 6.283185307179586) < 3.141592653589793
                          else -12000)
    return audiocore.RawSample(values, sample_rate=RATE,
                               channel_count=channel_count)


for name, mode in MODES:
    for channels in (1, 2):
        biquad = synthio.Biquad(mode, CENTER, Q, A=GAIN_A)
        effect = audiofilters.Filter(
            filter=biquad, mix=1.0, buffer_size=512, sample_rate=RATE,
            bits_per_sample=16, samples_signed=True, channel_count=channels,
        )
        effect.play(source(channels))
        for index in range(4):
            data = bytes(audiocore.get_buffer(effect)[1])
            if index == 0:
                words = tuple(int.from_bytes(data[pos:pos + 2], "little")
                              for pos in range(0, 24, 2))
                decoded = tuple(word - 65536 if word >= 32768 else word
                                for word in words)
                print("biquad_samples", name, channels, decoded)
            print("biquad", name, channels, index, len(data),
                  sum(data), checksum(data))


#: Centers spanning the usable band at RATE (Nyquist 4000). The middle two are
#: unremarkable; the outer two are the whole point. 60 Hz is where Q15
#: coefficients used to collapse - a low-pass there returned silence - and
#: 3600 Hz is past pi/2 in W0, where the old sine/cosine fit was extrapolating
#: and a high-pass passed its own stopband. Neither end was pinned by anything
#: before the biquads were widened; see docs/upstream-diff.md.
EDGE_CENTERS = (60, 200, 1200, 3600)

for name, mode in MODES:
    for center in EDGE_CENTERS:
        biquad = synthio.Biquad(mode, center, Q, A=GAIN_A)
        effect = audiofilters.Filter(
            filter=biquad, mix=1.0, buffer_size=512, sample_rate=RATE,
            bits_per_sample=16, samples_signed=True, channel_count=2,
        )
        effect.play(source(2))
        for index in range(4):
            data = bytes(audiocore.get_buffer(effect)[1])
            print("biquad_edge", name, center, index, len(data),
                  sum(data), checksum(data))


# --- Q and A, which no fixture above varies -----------------------------------
# Three of the five arguments to the filter were pinned only at one value each.
# A resonance that is ignored, or a shelf gain wired to a constant, moved
# nothing in this gate before these lines existed.

for name, mode in MODES:
    for q_value in Q_VALUES:
        for a_value in A_VALUES:
            biquad = synthio.Biquad(mode, CENTER, q_value, A=a_value)
            effect = audiofilters.Filter(
                filter=biquad, mix=1.0, buffer_size=512, sample_rate=RATE,
                bits_per_sample=16, samples_signed=True, channel_count=2,
            )
            effect.play(source(2))
            for index in range(2):
                data = bytes(audiocore.get_buffer(effect)[1])
                print("biquad_qa", name, "%.4f" % q_value, "%.4f" % a_value,
                      index, len(data), sum(data), checksum(data))


# --- synthio.Note.filter, which this gate has never exercised at all ----------
# The probe only ever built audiofilters.Filter. `Note.filter` is a different
# path - it accepts a Biquad or a tuple of up to four, applied per voice inside
# the synthesizer - and it is audioif's own extension over the oracle. It could
# be reduced to a total no-op and nothing here would notice. The cascade is the
# part most worth pinning: a dropped fourth stage is exactly the defect a
# level-based check misses, and the only other coverage
# (test_cpython_press_semantics.py::FilterCascade) compares 1 stage against 2.

CASCADE_MODES = (synthio.FilterMode.LOW_PASS, synthio.FilterMode.HIGH_PASS,
                 synthio.FilterMode.BAND_PASS, synthio.FilterMode.PEAKING_EQ)

for stages in (1, 2, 3, 4):
    synth = synthio.Synthesizer(sample_rate=RATE, channel_count=2)
    stack = tuple(
        synthio.Biquad(CASCADE_MODES[i], CENTER * (i + 1), Q, A=GAIN_A)
        for i in range(stages)
    )
    note = synthio.Note(220.0, amplitude=0.6,
                        filter=stack[0] if stages == 1 else stack)
    synth.press(note)
    for index in range(4):
        data = bytes(audiocore.get_buffer(synth)[1])
        if index == 0:
            words = tuple(int.from_bytes(data[pos:pos + 2], "little")
                          for pos in range(0, 24, 2))
            print("note_filter_samples", stages,
                  tuple(w - 65536 if w >= 32768 else w for w in words))
        print("note_filter", stages, index, len(data), sum(data),
              checksum(data))
