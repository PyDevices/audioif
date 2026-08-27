// audioconvolve.Convolver for CircuitPython: the buffer plumbing around
// shared/audioif_convolve.c. See Convolver.h.
//
// SPDX-License-Identifier: MIT

#include "shared-module/audioconvolve/Convolver.h"

#include <string.h>

void audioconvolve_convolver_reset_buffer(
    audioconvolve_convolver_obj_t *self, bool single_channel_output,
    uint8_t channel) {
    (void)single_channel_output;
    (void)channel;
    self->pending = NULL;
    self->pending_frames = 0;
    // The history goes; the impulse stays. One is audio in flight and the
    // other is a setting -- reloading a room because playback restarted would
    // be both wrong and expensive.
    audioif_convolve_reset(&self->state, &self->config);
}

audioio_get_buffer_result_t audioconvolve_convolver_get_buffer(
    audioconvolve_convolver_obj_t *self, bool single_channel_output,
    uint8_t channel, uint8_t **buffer, uint32_t *buffer_length) {
    (void)single_channel_output;
    (void)channel;
    uint32_t produced = 0;
    while (produced < AUDIOIF_CONVOLVE_FRAMES) {
        if (self->pending_frames == 0) {
            if (self->source == MP_OBJ_NULL) {
                break;
            }
            uint8_t *raw = NULL;
            uint32_t raw_bytes = 0;
            audioio_get_buffer_result_t result = audiosample_get_buffer(
                self->source, false, 0, &raw, &raw_bytes);
            if (result == GET_BUFFER_ERROR || raw == NULL || raw_bytes < 4) {
                break;
            }
            self->pending = (const int16_t *)raw;
            self->pending_frames = raw_bytes / 4u;
        }
        uint32_t run = AUDIOIF_CONVOLVE_FRAMES - produced;
        if (run > self->pending_frames) {
            run = self->pending_frames;
        }
        audioif_convolve_process_s16(&self->config, &self->state,
            &self->buffer[produced * 2], self->pending, run);
        self->pending += run * 2;
        self->pending_frames -= run;
        produced += run;
    }
    // A starved chain gets silence rather than a short block, and the tail
    // stops with the source: only frames that arrive advance the convolution,
    // so a reverb does not ring on into silence after its input ends. Same
    // rule as audioecho and audiodelays, and for the same reason -- a node in
    // the middle of a live graph never reports itself finished.
    if (produced == 0) {
        memset(self->buffer, 0, sizeof(self->buffer));
        produced = AUDIOIF_CONVOLVE_FRAMES;
    }
    *buffer = (uint8_t *)self->buffer;
    *buffer_length = produced * 4u;
    return GET_BUFFER_MORE_DATA;
}
