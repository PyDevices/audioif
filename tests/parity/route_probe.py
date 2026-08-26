"""Deterministic Splitter PCM, from whichever module provides the node.

    route_probe.py audioroute        the port
    route_probe.py vstaudio_oracle   the original, via the oracle build

Only the positional `Splitter(source, taps)` form is used: the port also
accepts `taps` as a keyword, which the original never did, so that belongs in
the unit tests rather than in a comparison against it.

Sources here are SpeedChanger over a RawSample rather than the RawSample
itself. A RawSample hands out its whole buffer on every pull and never runs
dry, which would leave both the ring's wrap and the dry-source path
unexercised; SpeedChanger delivers 128 frames at a time and then stops, which
walks the ring and finishes empty.
"""

import sys
from array import array

import audiocore
import audiospeed

MODULE = sys.argv[1] if len(sys.argv) > 1 else "audioroute"
# Both spellings are built-in modules under MicroPython, which does not record
# those in sys.modules - take what __import__ hands back.
route = __import__(MODULE)

SAMPLE_RATE = 48000


def checksum(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def source(frames):
    """A stream whose content keeps changing, so a skipped span is visible."""
    values = array("h")
    for frame in range(frames):
        for channel in range(2):
            values.append(((frame * (37 + channel * 11) + channel * 500)
                           % 24001) - 12000)
    return audiospeed.SpeedChanger(
        audiocore.RawSample(values, sample_rate=SAMPLE_RATE, channel_count=2),
        1.0)


def emit(tag, tap, blocks, index=0):
    for block in range(blocks):
        data = bytes(audiocore.get_buffer(tap)[1])
        print("route", tag, index, block, len(data), sum(data),
              checksum(data))


# Every tap count, each tap read in turn: the first one to ask refills the
# ring, the rest read what it wrote.
for taps in (1, 2, 3, 4):
    splitter = route.Splitter(source(2000), taps)
    for index in range(taps):
        emit("taps%d" % taps, splitter.tap(index), 4, index)

# Interleaved, which is how a Mixer actually pulls them.
splitter = route.Splitter(source(2000), 3)
handles = [splitter.tap(index) for index in range(3)]
for block in range(5):
    for index, tap in enumerate(handles):
        data = bytes(audiocore.get_buffer(tap)[1])
        print("route interleaved", index, block, len(data), sum(data),
              checksum(data))

# tap(i) is the same object every time - the taps are built with the Splitter,
# not on demand, because the ring drops what an unclaimed tap never collects.
splitter = route.Splitter(source(500), 2)
print("route identity", splitter.tap(1) is splitter.tap(1))

# A laggard tap: read one branch past the ring's depth (8192 frames) while the
# other sits idle, then read the idle one. Its cursor has been dragged forward
# and the span it never collected is gone.
splitter = route.Splitter(source(20000), 2)
lead = splitter.tap(0)
for _ in range(70):          # 70 x 128 frames, comfortably past 8192
    bytes(audiocore.get_buffer(lead)[1])
emit("laggard", splitter.tap(1), 4, 1)
emit("laggard-lead", lead, 2, 0)

# reset_buffer on a tap does nothing on purpose: the cursors belong to the
# Splitter and the other branches are still reading against them.
splitter = route.Splitter(source(2000), 2)
first = splitter.tap(0)
emit("before-reset", first, 2)
audiocore.reset_buffer(first)
emit("after-reset", first, 2)

# A source that runs out. The taps keep answering with silence rather than
# reporting themselves finished - the graph around them is still running.
splitter = route.Splitter(source(400), 2)
emit("dry", splitter.tap(0), 6)
emit("dry-other", splitter.tap(1), 6, 1)

# Out-of-range tap indices, including the negative one that used to arrive
# here as a very large unsigned number.
splitter = route.Splitter(source(500), 2)
for index in (2, 4, -1):
    try:
        splitter.tap(index)
        print("route range", index, "no error")
    except ValueError as error:
        print("route range", index, error)

for count in (0, 5):
    try:
        route.Splitter(source(500), count)
        print("route taps", count, "no error")
    except ValueError as error:
        print("route taps", count, error)

print("done route")
