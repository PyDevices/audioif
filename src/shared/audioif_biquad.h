// Runtime-neutral synth biquad coefficient and sample processing.
// SPDX-License-Identifier: MIT

#pragma once


#include <stddef.h>
#include <stdint.h>

typedef struct {
    int32_t a1, a2, b0, b1, b2;
} audioif_biquad_coefficients_t;

typedef struct {
    int32_t x[2], y[2];
} audioif_biquad_state_t;

void audioif_biquad_configure(audioif_biquad_coefficients_t *coefficients,
    int mode, double frequency, double Q, double A, uint32_t sample_rate);
void audioif_biquad_configure_w0(audioif_biquad_coefficients_t *coefficients,
    int mode, double W0, double Q, double A);
void audioif_biquad_reset(audioif_biquad_state_t *state);
void audioif_biquad_process(const audioif_biquad_coefficients_t *coefficients,
    audioif_biquad_state_t *state, int32_t *buffer, size_t sample_count);
