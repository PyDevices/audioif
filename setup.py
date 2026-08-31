import sys
from pathlib import Path

from setuptools import Extension, setup

# The parity gates hash PCM bit-exactly against the CircuitPython oracle,
# and Linux (gcc) and Windows (MSVC) builds agree with it. On macOS arm64,
# clang's default -ffp-contract=on fuses multiply-adds into fmadd (baseline
# on AArch64, so contraction actually happens there, unlike x86-64 without
# -mfma), which perturbs last-ulp float results and broke verify_effects.
# Scoped to macOS the way the single-precision cell scoped its own flags
# (clean-build.yml): turn contraction off so every shipped wheel computes
# the same bits the oracle blessed.
MACOS_COMPILE_ARGS = ["-ffp-contract=off"] if sys.platform == "darwin" else []

# _audioif.__version__ used to be a literal in the C, and drifted from VERSION
# the first time VERSION moved. There is one version here, and it is this file.
VERSION = Path(__file__).parent.joinpath("VERSION").read_text().strip()

setup(
    ext_modules=[
        Extension(
            "_audioif",
            sources=[
                "src/cpython/_audioif.c",
                "src/shared/audioif_sample.c",
                "src/shared/audioif_rawsample.c",
                "src/shared/audioif_synth_dsp.c",
                "src/shared/audioif_envelope.c",
                "src/shared/audioif_distortion.c",
                "src/shared/audioif_biquad.c",
                "src/shared/audioif_echo.c",
                "src/shared/audioif_phaser.c",
                "src/shared/audioif_chorus.c",
                "src/shared/audioif_multitap.c",
                "src/shared/audioif_pitchshift.c",
                "src/shared/audioif_freeverb.c",
                "src/shared/audioif_dynamics.c",
                "src/shared/audioif_splitter.c",
                "src/shared/audioif_multiply.c",
                "src/shared/audioif_feedback_delay.c",
                "src/shared/audioif_trig.c",
                "src/shared/audioif_fft.c",
                "src/shared/audioif_convolve.c",
            ],
            include_dirs=["src"],
            define_macros=[("AUDIOIF_VERSION", '"%s"' % VERSION)],
            extra_compile_args=MACOS_COMPILE_ARGS,
        )
    ]
)
