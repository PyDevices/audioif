// audioroute.Splitter for CircuitPython: the source pull. See Splitter.h.
//
// SPDX-License-Identifier: MIT

#include "shared-module/audioroute/Splitter.h"

void audioroute_splitter_pull(audioroute_splitter_obj_t *self) {
    if (self->source == MP_OBJ_NULL) {
        return;
    }
    uint8_t *raw = NULL;
    uint32_t raw_bytes = 0;
    audioio_get_buffer_result_t result = audiosample_get_buffer(
        self->source, false, 0, &raw, &raw_bytes);
    if (result == GET_BUFFER_ERROR || raw == NULL) {
        return;
    }
    audioif_splitter_write(&self->state, (const int16_t *)raw, raw_bytes / 4u);
}
