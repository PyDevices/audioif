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
            print("biquad", name, channels, index, len(data), sum(data))


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
            print("biquad_edge", name, center, index, len(data), sum(data))
