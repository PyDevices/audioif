// Ported from CircuitPython's shared-bindings/synthio/Synthesizer.h and
// shared-module/synthio/Synthesizer.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
//
// SPDX-FileCopyrightText: Copyright (c) 2021 Artyom Skrobov
// SPDX-FileCopyrightText: Copyright (c) 2023 Jeff Epler for Adafruit Industries
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "synthio/__init__.h"

typedef struct {
    synthio_synth_t synth;
    mp_obj_t blocks;
} synthio_synthesizer_obj_t;

extern const mp_obj_type_t synthio_synthesizer_type;

void common_hal_synthio_synthesizer_construct(synthio_synthesizer_obj_t *self,
    uint32_t sample_rate, int channel_count, mp_obj_t waveform_obj,
    mp_obj_t envelope_obj);
void common_hal_synthio_synthesizer_deinit(synthio_synthesizer_obj_t *self);
void common_hal_synthio_synthesizer_release(synthio_synthesizer_obj_t *self, mp_obj_t to_release);
void common_hal_synthio_synthesizer_press(synthio_synthesizer_obj_t *self, mp_obj_t to_press);
void common_hal_synthio_synthesizer_retrigger(synthio_synthesizer_obj_t *self, mp_obj_t to_retrigger);
void common_hal_synthio_synthesizer_release_all(synthio_synthesizer_obj_t *self);
mp_obj_t common_hal_synthio_synthesizer_get_pressed_notes(synthio_synthesizer_obj_t *self);
mp_obj_t common_hal_synthio_synthesizer_get_blocks(synthio_synthesizer_obj_t *self);
envelope_state_e common_hal_synthio_synthesizer_note_info(synthio_synthesizer_obj_t *self, mp_obj_t note, mp_float_t *vol_out);

// These are not available from Python because it may be called in an interrupt.
void synthio_synthesizer_reset_buffer(synthio_synthesizer_obj_t *self,
    bool single_channel_output,
    uint8_t channel);

audioio_get_buffer_result_t synthio_synthesizer_get_buffer(synthio_synthesizer_obj_t *self,
    bool single_channel_output,
    uint8_t channel,
    uint8_t **buffer,
    uint32_t *buffer_length); // length in bytes
