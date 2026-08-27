// Runtime-neutral sample-wise multiply. See audioif_multiply.h for provenance.
// SPDX-License-Identifier: MIT

#include "shared/audioif_multiply.h"

void audioif_multiply_config_init(audioif_multiply_config_t *config) {
    config->mix = 32768;
}

void audioif_multiply_set_mix(audioif_multiply_config_t *config, float mix) {
    if (mix <= 0.0f) {
        config->mix = 0;
    } else if (mix >= 1.0f) {
        config->mix = 32768;
    } else {
        config->mix = (int32_t)(mix * 32768.0f + 0.5f);
    }
}

void audioif_multiply_process_s16(const audioif_multiply_config_t *config,
    int16_t *out, const int16_t *a, const int16_t *b, uint32_t frames) {
    const int32_t wet = config->mix;
    const int32_t dry = 32768 - wet;
    const uint32_t samples = frames * 2u;
    for (uint32_t i = 0; i < samples; ++i) {
        const int32_t signal = a[i];
        // Scaling by 32768 rather than 32767 keeps a full-scale modulator a
        // gain of one to within an LSB and keeps the shift a shift. The two
        // negative rails are the one product that lands outside int16, which
        // is what the clamp below is for.
        const int32_t product = (signal * (int32_t)b[i]) >> 15;
        int32_t value = (dry * signal + wet * product) >> 15;
        if (value > 32767) {
            value = 32767;
        } else if (value < -32768) {
            value = -32768;
        }
        out[i] = (int16_t)value;
    }
}

void audioif_multiply_passthrough_s16(int16_t *out, const int16_t *a,
    uint32_t frames) {
    const uint32_t samples = frames * 2u;
    for (uint32_t i = 0; i < samples; ++i) {
        out[i] = a[i];
    }
}
