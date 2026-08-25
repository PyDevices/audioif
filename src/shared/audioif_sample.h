// Runtime-neutral audio sample protocol shared by the MicroPython and
// CPython bindings.
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    AUDIOIF_BUFFER_DONE = 0,
    AUDIOIF_BUFFER_MORE_DATA = 1,
    AUDIOIF_BUFFER_ERROR = 2,
} audioif_buffer_result_t;

typedef enum {
    AUDIOIF_STATUS_OK = 0,
    AUDIOIF_STATUS_DEINITIALIZED,
    AUDIOIF_STATUS_INVALID_ARGUMENT,
} audioif_status_t;

typedef struct {
    uint32_t sample_rate;
    uint32_t max_buffer_length;
    uint8_t bits_per_sample;
    uint8_t channel_count;
    uint8_t samples_signed;
    bool single_buffer;
} audioif_sample_info_t;

typedef audioif_status_t (*audioif_sample_reset_fn)(void *context,
    bool single_channel_output, uint8_t audio_channel);
typedef audioif_status_t (*audioif_sample_get_fn)(void *context,
    bool single_channel_output, uint8_t audio_channel,
    const uint8_t **buffer, uint32_t *buffer_length,
    audioif_buffer_result_t *result);

typedef struct {
    audioif_sample_reset_fn reset_buffer;
    audioif_sample_get_fn get_buffer;
} audioif_sample_ops_t;

typedef struct {
    const audioif_sample_ops_t *ops;
    void *context;
    audioif_sample_info_t *info;
} audioif_sample_source_t;

audioif_status_t audioif_sample_reset(audioif_sample_source_t *source,
    bool single_channel_output, uint8_t audio_channel);
audioif_status_t audioif_sample_get(audioif_sample_source_t *source,
    bool single_channel_output, uint8_t audio_channel,
    const uint8_t **buffer, uint32_t *buffer_length,
    audioif_buffer_result_t *result);

