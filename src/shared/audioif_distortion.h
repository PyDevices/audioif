// Runtime-neutral distortion DSP.
// SPDX-License-Identifier: MIT

#pragma once


#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    AUDIOIF_DISTORTION_CLIP = 0,
    AUDIOIF_DISTORTION_LOFI = 1,
    AUDIOIF_DISTORTION_OVERDRIVE = 2,
    AUDIOIF_DISTORTION_WAVESHAPE = 3,
} audioif_distortion_mode_t;

int32_t audioif_distortion_sample(int32_t sample, double drive,
    double pre_gain, double post_gain, audioif_distortion_mode_t mode,
    bool soft_clip, double mix, uint32_t word_mask);
void audioif_distortion_process_s16(int16_t *output, const int16_t *input,
    size_t count, double drive, double pre_gain_db, double post_gain_db,
    audioif_distortion_mode_t mode, bool soft_clip, double mix);

