// Ported from CircuitPython's shared-bindings/synthio/MidiTrack.h and
// shared-module/synthio/MidiTrack.h (upstream repo:
// https://github.com/adafruit/circuitpython, MIT), merged into one file.
//
// SPDX-FileCopyrightText: Copyright (c) 2021 Artyom Skrobov
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include "py/obj.h"

#include "synthio/__init__.h"

typedef struct {
    synthio_synth_t synth;
    mp_buffer_info_t track;
    // invariant: after initial startup, pos always points just after an encoded duration, i.e., at a midi message (or at EOF)
    size_t pos;
    mp_int_t error_location;
    uint32_t tempo;
} synthio_miditrack_obj_t;

extern const mp_obj_type_t synthio_miditrack_type;

void common_hal_synthio_miditrack_construct(synthio_miditrack_obj_t *self, const uint8_t *buffer, uint32_t len, uint32_t tempo, uint32_t sample_rate, mp_obj_t waveform_obj, mp_obj_t filter_obj, mp_obj_t envelope_obj);

void common_hal_synthio_miditrack_deinit(synthio_miditrack_obj_t *self);
mp_int_t common_hal_synthio_miditrack_get_error_location(synthio_miditrack_obj_t *self);

mp_int_t common_hal_synthio_miditrack_get_tempo(synthio_miditrack_obj_t *self);
void common_hal_synthio_miditrack_set_tempo(synthio_miditrack_obj_t *self, mp_int_t value);

// These are not available from Python because it may be called in an interrupt.
void synthio_miditrack_reset_buffer(synthio_miditrack_obj_t *self,
    bool single_channel_output,
    uint8_t channel);

audioio_get_buffer_result_t synthio_miditrack_get_buffer(synthio_miditrack_obj_t *self,
    bool single_channel_output,
    uint8_t channel,
    uint8_t **buffer,
    uint32_t *buffer_length); // length in bytes
