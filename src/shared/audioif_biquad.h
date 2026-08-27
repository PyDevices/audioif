// Runtime-neutral synth biquad coefficient and sample processing.
// SPDX-License-Identifier: MIT

#pragma once


#include <stddef.h>
#include <stdint.h>

// How many fractional bits the filter's output memory keeps beyond the 16 the
// samples themselves carry. See audioif_biquad.c for why the feedback path
// needs them; anything that stores a `y` value out of a state struct has to
// know it is not in sample units.
#define AUDIOIF_BIQUAD_STATE_SHIFT 12

typedef struct {
    int32_t a1, a2, b0, b1, b2;
    // Fractional bits in the five coefficients above, chosen per filter.
    int32_t shift;
} audioif_biquad_coefficients_t;

typedef struct {
    // `x` is in sample units; `y` carries AUDIOIF_BIQUAD_STATE_SHIFT extra
    // fractional bits.
    int32_t x[2], y[2];
} audioif_biquad_state_t;

void audioif_biquad_configure(audioif_biquad_coefficients_t *coefficients,
    int mode, double frequency, double Q, double A, uint32_t sample_rate);
void audioif_biquad_configure_w0(audioif_biquad_coefficients_t *coefficients,
    int mode, double W0, double Q, double A);
void audioif_biquad_reset(audioif_biquad_state_t *state);
void audioif_biquad_process(const audioif_biquad_coefficients_t *coefficients,
    audioif_biquad_state_t *state, int32_t *buffer, size_t sample_count);
