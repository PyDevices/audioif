// audioshaper.Waveshaper for CircuitPython. See audioif's
// src/audioshaper/Waveshaper.h for the MicroPython twin; the DSP is the same
// shared/audioif_shaper.c in both, copied into this tree by
// audioif/apply_cp_patches.sh.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "py/obj.h"
#include "shared-module/audiocore/__init__.h"

#include "shared/audioif_shaper.h"

typedef struct {
    audiosample_base_t base;
    mp_obj_t source;
    audioif_shaper_config_t config;
    audioif_shaper_state_t state;
    int16_t buffer[AUDIOIF_SHAPER_FRAMES * 2];
    // The curve, copied at construction so the caller may drop the array it
    // built. The config borrows this pointer; the GC keeps it because this
    // object holds it.
    int16_t *curve;
    // Source frames fetched but not yet consumed, carried across output
    // blocks.
    const int16_t *pending;
    uint32_t pending_frames;
} audioshaper_waveshaper_obj_t;

void audioshaper_waveshaper_reset_buffer(audioshaper_waveshaper_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audioshaper_waveshaper_get_buffer(
    audioshaper_waveshaper_obj_t *self, bool single_channel_output,
    uint8_t channel, uint8_t **buffer, uint32_t *buffer_length);
