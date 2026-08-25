from setuptools import Extension, setup

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
            ],
            include_dirs=["src"],
        )
    ]
)
