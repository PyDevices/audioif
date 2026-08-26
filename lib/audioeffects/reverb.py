"""Algorithmic reverb presets over the engine's Freeverb.

Convolution reverb is deliberately absent: there is no impulse-response
engine in the DSP palette, and pretending with filters would not be one.
"""

import audiodelays
import audiofreeverb

from . import _core

_PRESETS = {
    #            roomsize damp
    "room":     (0.55, 0.6),
    "chamber":  (0.72, 0.5),
    "hall":     (0.88, 0.35),
    "plate":    (0.80, 0.15),
    "spring":   (0.62, 0.25),
}


class Reverb(_core.Effect):
    def __init__(self, source, preset="hall", mix=0.3):
        roomsize, damp = _PRESETS[preset]
        chain_source = source
        if preset == "spring":
            # the boingy pre-flutter of a spring tank
            self.flutter = audiodelays.Echo(
                max_delay_ms=60, delay_ms=33, decay=0.45, mix=0.5,
                freq_shift=True, **_core.pcm())
            self.flutter.play(source)
            chain_source = self.flutter
        self.node = audiofreeverb.Freeverb(
            roomsize=roomsize, damp=damp, mix=mix, **_core.pcm())
        self.node.play(chain_source)
        self.output = self.node

    def set_mix(self, mix):
        self.node.mix = mix
