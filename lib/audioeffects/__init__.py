"""Forty-three effect classes built out of audioif's audio nodes.

Every class wires itself from an audio source - a synthesizer, an
instrument's `output`, a host input, or a previous effect's `output` - and
exposes its chain tail as `output`. See README.md for the catalogue.

    import audioeffects
    audioeffects.configure(48000)
    comp = audioeffects.Compressor(source, threshold_db=-20, ratio=3)
    audio_out.play(comp.output)

`configure()` sets the sample rate every effect built after it runs at; call
it once, before building anything.

Some classes also carry patches - named settings on the 0-127 MIDI grid, the
way an instrument does. See README.md, "A note on patches".
"""

from ._core import configure, sample_rate

from .dynamics import (Compressor, Limiter, Expander, NoiseGate, DeEsser,
                       TransientShaper, MultibandCompressor)
from .eq import (ParametricEQ, GraphicEQ, LowPass, HighPass, BandPass,
                 Notch, LadderFilter, CombFilter, DynamicEQ)
from .reverb import Reverb, ConvolutionReverb
from .delay import (DigitalDelay, SlapbackDelay, TapeDelay, AnalogDelay,
                    PingPongDelay, MultiTapDelay)
from .modulation import (Chorus, Flanger, Phaser, Tremolo, AutoPan,
                         Vibrato, Rotary, RingMod)
from .drive import (Overdrive, Distortion, Fuzz, Saturation, Bitcrusher,
                    Exciter, CabinetSim)
from .pitch import PitchShifter, Harmonizer, Octaver, StereoWidener

#: The package's whole surface, grouped as the modules above are. Every
#: name here is re-exported; nothing else in a submodule is public.
__all__ = [
    "configure", "sample_rate",
    # dynamics
    "Compressor", "Limiter", "Expander", "NoiseGate", "DeEsser",
    "TransientShaper", "MultibandCompressor",
    # eq and filters
    "ParametricEQ", "GraphicEQ", "LowPass", "HighPass", "BandPass",
    "Notch", "LadderFilter", "CombFilter", "DynamicEQ",
    # reverb
    "Reverb", "ConvolutionReverb",
    # delay
    "DigitalDelay", "SlapbackDelay", "TapeDelay", "AnalogDelay",
    "PingPongDelay", "MultiTapDelay",
    # modulation
    "Chorus", "Flanger", "Phaser", "Tremolo", "AutoPan", "Vibrato", "Rotary",
    "RingMod",
    # drive
    "Overdrive", "Distortion", "Fuzz", "Saturation", "Bitcrusher", "Exciter",
    "CabinetSim",
    # pitch and stereo
    "PitchShifter", "Harmonizer", "Octaver", "StereoWidener",
]
