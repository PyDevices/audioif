// SPDX-License-Identifier: MIT

#include "shared/audioif_biquad.h"
#include "shared/audioif_synth_dsp.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

#define AUDIOIF_BIQUAD_SHIFT 15
#define AUDIOIF_PI 3.14159265358979323846

typedef struct { double s, c; } sincos_result_t;

static double fast_sqrt(double input) {
    float number = (float)input;
    union { float f; uint32_t i; } value = {.f = number};
    value.i = 0x5f3759df - (value.i >> 1);
    value.f *= 1.5F - (number * 0.5F * value.f * value.f);
    return input * (double)value.f;
}

static void fast_sincos(double theta, sincos_result_t *result) {
    double x = theta * (4.0 / AUDIOIF_PI) - 1;
    double x2 = x * x, x3 = x2 * x, x4 = x2 * x2, x5 = x2 * x3;
    double c0 = 0.70708592,
          c1x = -0.55535724 * x,
          c2x2 = -0.21798592 * x2,
          c3x3 = 0.05707685 * x3,
          c4x4 = 0.0109 * x4,
          c5x5 = -0.00171961 * x5;
    double evens = c4x4 + c2x2 + c0;
    double odds = c5x5 + c3x3 + c1x;
    result->c = evens + odds;
    result->s = evens - odds;
}

static int32_t scale(double value) {
    return (int32_t)round(ldexp(value, AUDIOIF_BIQUAD_SHIFT));
}

void audioif_biquad_configure_w0(audioif_biquad_coefficients_t *coefficients,
    int mode, double W0, double Q, double A) {
    sincos_result_t sc;
    fast_sincos(W0, &sc);
    double alpha = sc.s / (2 * Q);
    double a0, a1, a2, b0, b1, b2;
    if (mode < 4) {
        a0 = 1 + alpha; a1 = -2 * sc.c; a2 = 1 - alpha;
        if (mode == 0) {
            b2 = b0 = (1 - sc.c) * .5; b1 = 1 - sc.c;
        } else if (mode == 1) {
            b2 = b0 = (1 + sc.c) * .5; b1 = -(1 + sc.c);
        } else if (mode == 2) {
            b0 = alpha; b1 = 0; b2 = -b0;
        } else {
            b0 = 1; b1 = -2 * sc.c; b2 = 1;
        }
    } else if (mode == 4) {
        // b2 is `1 - alpha * A`, not `+`. Upstream CircuitPython has the plus
        // (shared-module/synthio/Biquad.c); see docs/upstream-diff.md. The sign
        // is what makes numerator and denominator sum alike at DC and Nyquist,
        // which is the whole point of a peaking filter: unity everywhere except
        // the band. With it flipped the numerator gains 2*alpha*A at DC while
        // the denominator does not, and since 1 - cos(W0) is tiny down there,
        // a +6 dB bell at 1 kHz / Q 1 comes out roughly +21 dB at DC.
        b0 = 1 + alpha * A; b1 = -2 * sc.c; b2 = 1 - alpha * A;
        a0 = 1 + alpha / A; a1 = -2 * sc.c; a2 = 1 - alpha / A;
    } else {
        double root = fast_sqrt(A);
        if (mode == 5) {
            b0 = A * ((A + 1) - (A - 1) * sc.c + 2 * root * alpha);
            b1 = 2 * A * ((A - 1) - (A + 1) * sc.c);
            b2 = A * ((A + 1) - (A - 1) * sc.c - 2 * root * alpha);
            a0 = (A + 1) + (A - 1) * sc.c + 2 * root * alpha;
            a1 = -2 * ((A - 1) + (A + 1) * sc.c);
            a2 = (A + 1) + (A - 1) * sc.c - 2 * root * alpha;
        } else {
            b0 = A * ((A + 1) + (A - 1) * sc.c + 2 * root * alpha);
            b1 = -2 * A * ((A - 1) + (A + 1) * sc.c);
            b2 = A * ((A + 1) + (A - 1) * sc.c - 2 * root * alpha);
            a0 = (A + 1) - (A - 1) * sc.c + 2 * root * alpha;
            a1 = 2 * ((A - 1) - (A + 1) * sc.c);
            a2 = (A + 1) - (A - 1) * sc.c - 2 * root * alpha;
        }
    }
    double reciprocal = 1 / a0;
    coefficients->a1 = scale(a1 * reciprocal);
    coefficients->a2 = scale(a2 * reciprocal);
    coefficients->b0 = scale(b0 * reciprocal);
    coefficients->b1 = scale(b1 * reciprocal);
    coefficients->b2 = scale(b2 * reciprocal);
}

void audioif_biquad_configure(audioif_biquad_coefficients_t *coefficients,
    int mode, double frequency, double Q, double A, uint32_t sample_rate) {
    double W0 = frequency * (2 * AUDIOIF_PI) / sample_rate;
    audioif_biquad_configure_w0(coefficients, mode, W0, Q, A);
}

void audioif_biquad_reset(audioif_biquad_state_t *state) {
    // Preserve CircuitPython's reset byte count exactly. This clears x[0],
    // x[1], and no later fields on 32-bit int layouts.
    memset(&state->x, 0, 4 * sizeof(int16_t));
}

void audioif_biquad_process(const audioif_biquad_coefficients_t *c,
    audioif_biquad_state_t *state, int32_t *buffer, size_t sample_count) {
    int32_t x0 = state->x[0], x1 = state->x[1];
    int32_t y0 = state->y[0], y1 = state->y[1];
    for (size_t i = 0; i < sample_count; i++) {
        int32_t input = buffer[i];
        int32_t output = audioif_sat16(c->b0 * input + c->b1 * x0 +
            c->b2 * x1 - c->a1 * y0 - c->a2 * y1 +
            (1 << (AUDIOIF_BIQUAD_SHIFT - 1)), AUDIOIF_BIQUAD_SHIFT);
        x1 = x0; x0 = input; y1 = y0; y0 = output; buffer[i] = output;
    }
    state->x[0] = x0; state->x[1] = x1;
    state->y[0] = y0; state->y[1] = y1;
}
