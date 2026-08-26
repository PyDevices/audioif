// audiodynamics.Dynamics -- MicroPython bindings over the runtime-neutral
// dynamics DSP in shared/audioif_dynamics.c.
//
// Not a CircuitPython port: this module comes from micropython-vst3's
// `vstaudio` usermod, which is where the effects library's compressors,
// limiters, gates and transient shapers have always lived. See
// docs/upstream-diff.md.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "audiocore/__init__.h"
#include "py/obj.h"
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

extern const mp_obj_type_t audiodynamics_dynamics_type;
