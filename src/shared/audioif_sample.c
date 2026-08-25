// SPDX-License-Identifier: MIT

#include "shared/audioif_sample.h"

audioif_status_t audioif_sample_reset(audioif_sample_source_t *source,
    bool single_channel_output, uint8_t audio_channel) {
    if (source == NULL || source->ops == NULL || source->ops->reset_buffer == NULL) {
        return AUDIOIF_STATUS_INVALID_ARGUMENT;
    }
    return source->ops->reset_buffer(source->context, single_channel_output, audio_channel);
}

audioif_status_t audioif_sample_get(audioif_sample_source_t *source,
    bool single_channel_output, uint8_t audio_channel,
    const uint8_t **buffer, uint32_t *buffer_length,
    audioif_buffer_result_t *result) {
    if (source == NULL || source->ops == NULL || source->ops->get_buffer == NULL ||
        buffer == NULL || buffer_length == NULL || result == NULL) {
        return AUDIOIF_STATUS_INVALID_ARGUMENT;
    }
    return source->ops->get_buffer(source->context, single_channel_output,
        audio_channel, buffer, buffer_length, result);
}

