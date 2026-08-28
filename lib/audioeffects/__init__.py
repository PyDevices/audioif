"""Forty-three effect classes built out of audioif's audio nodes.

Every class wires itself from an audio source - a synthesizer, an
instrument's `output`, a host input, or a previous effect's `output` - and
exposes its chain tail as `output`. See README.md for the catalogue.

    import audioeffects
    comp = audioeffects.create("Compressor", source, 48000,
                               threshold_db=-20, ratio=3)
    audio_out.play(comp.output)

The package factory receives the source and sample rate explicitly. Direct
class construction remains supported for local code after `configure()`.

Some classes also carry patches - named settings on the 0-127 MIDI grid, the
way an instrument does. See README.md, "A note on patches".
"""

from . import _core
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


def create(name, source, sample_rate, **options):
    """Construct the public effect named ``name``.

    This is the effect-side counterpart to ``audioinstruments.create``. The
    selected class's ``create`` method owns the actual construction, so a
    consumer does not need to know which module contains it.
    """
    cls = globals().get(name)
    if not isinstance(cls, type) or not issubclass(cls, _core.Effect):
        raise ImportError("audioeffects has no %s" % name)
    return cls.create(source, sample_rate, **options)

#: The package's whole surface, grouped as the modules above are. Every
#: name here is re-exported; nothing else in a submodule is public.
__all__ = [
    "configure", "sample_rate", "create",
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
