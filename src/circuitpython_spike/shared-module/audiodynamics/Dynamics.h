// audiodynamics.Dynamics for CircuitPython. See audioif's
// src/audiodynamics/Dynamics.h for the MicroPython twin; the DSP is the same
// shared/audioif_dynamics.c in both, copied into this tree by
// audioif/apply_cp_patches.sh.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "py/obj.h"
#include "shared-module/audiocore/__init__.h"

#include "shared/audioif_dynamics.h"

typedef struct {
    audiosample_base_t base;
    mp_obj_t source;
    audioif_dynamics_config_t config;
    audioif_dynamics_state_t state;
    int16_t buffer[AUDIOIF_DYNAMICS_FRAMES * 2];
    // Source frames fetched but not yet consumed, carried across output blocks.
    const int16_t *pending;
    uint32_t pending_frames;
} audiodynamics_dynamics_obj_t;

void audiodynamics_dynamics_reset_buffer(audiodynamics_dynamics_obj_t *self,
    bool single_channel_output, uint8_t channel);
audioio_get_buffer_result_t audiodynamics_dynamics_get_buffer(
    audiodynamics_dynamics_obj_t *self, bool single_channel_output,
    uint8_t channel, uint8_t **buffer, uint32_t *buffer_length);
