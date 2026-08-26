// audioroute.Splitter for CircuitPython. See audioif's src/audioroute/ for
// the MicroPython twin; the ring is the same shared/audioif_splitter.c in
// both, copied into this tree by audioif/apply_cp_patches.sh.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "py/obj.h"
#include "shared-module/audiocore/__init__.h"

#include "shared/audioif_splitter.h"

typedef struct {
    mp_obj_base_t obj_base;
    mp_obj_t source;
    mp_obj_t taps[AUDIOIF_SPLITTER_MAX_TAPS];
    audioif_splitter_state_t state;
    int16_t silence[AUDIOIF_SPLITTER_CHUNK_FRAMES * 2];
} audioroute_splitter_obj_t;

// Refill the ring from the source, if there is one. Called by whichever tap
// finds itself out of data first.
void audioroute_splitter_pull(audioroute_splitter_obj_t *self);
