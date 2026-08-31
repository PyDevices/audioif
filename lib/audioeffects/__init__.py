"""Forty-six effect classes built out of audioif's audio nodes.

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
from ._core import channel_count, configure, sample_rate

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
from .rack import Rack, ShimmerHall, AirSpace


def create(name, source, sample_rate, transport=None, **options):
    """Construct the public effect named ``name``.

    This is the effect-side counterpart to ``audioinstruments.create``. The
    selected class's ``create`` method owns the actual construction, so a
    consumer does not need to know which module contains it.
    """
    for exported in __all__:
        cls = globals().get(exported)
        if (isinstance(cls, type)
                and issubclass(cls, _core.Effect)
                and cls is not _core.Effect
                and getattr(cls, "NAME", None) == name):
            return cls.create(source, sample_rate, transport=transport,
                              **options)
    raise ImportError("audioeffects has no %s" % name)

#: The package's whole surface, grouped as the modules above are. Every
#: name here is re-exported; nothing else in a submodule is public.
__all__ = [
    "configure", "sample_rate", "channel_count", "create", "ALL",
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
    # racks
    "Rack", "ShimmerHall", "AirSpace",
]

# Stable provider names, not implementation module names. This is computed
# from the already-imported public classes and never constructs an effect.
ALL = tuple(sorted(
    getattr(globals()[name], "NAME", name)
    for name in __all__
    if isinstance(globals().get(name), type)
    and issubclass(globals()[name], _core.Effect)
    and globals()[name] is not _core.Effect
))
