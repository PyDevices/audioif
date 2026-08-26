// audioroute.Splitter -- MicroPython bindings over the runtime-neutral ring in
// shared/audioif_splitter.c.
//
// Not a CircuitPython port: this module comes from micropython-vst3's
// `vstaudio` usermod, where the effects library's parallel branches (exciters,
// Haas wideners, multiband splits) have always been built. See
// docs/upstream-diff.md.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "audiocore/__init__.h"
#include "py/obj.h"
#include "shared/audioif_splitter.h"

typedef struct {
    mp_obj_base_t obj_base;
    mp_obj_t source;
    mp_obj_t taps[AUDIOIF_SPLITTER_MAX_TAPS];
    audioif_splitter_state_t state;
    int16_t silence[AUDIOIF_SPLITTER_CHUNK_FRAMES * 2];
} audioroute_splitter_obj_t;

extern const mp_obj_type_t audioroute_splitter_type;

// Refill the ring from the source, if there is one. Called by whichever tap
// finds itself out of data first.
void audioroute_splitter_pull(audioroute_splitter_obj_t *self);
