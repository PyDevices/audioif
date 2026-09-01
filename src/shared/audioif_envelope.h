// Runtime-neutral synth envelope state machine.
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    AUDIOIF_ENVELOPE_ATTACK = 0,
    AUDIOIF_ENVELOPE_DECAY = 1,
    AUDIOIF_ENVELOPE_SUSTAIN = 2,
    AUDIOIF_ENVELOPE_RELEASE = 3,
} audioif_envelope_kind_t;

typedef struct {
    int16_t attack_step, decay_step, release_step;
    uint16_t attack_level, sustain_level;
} audioif_envelope_definition_t;

typedef struct {
    int16_t level;
    uint16_t substep;
    audioif_envelope_kind_t state;
} audioif_envelope_state_t;

void audioif_envelope_definition_init(audioif_envelope_definition_t *definition,
    uint32_t sample_rate, bool enabled, double attack_time,
    double decay_time, double release_time, double attack_level,
    double sustain_level);
void audioif_envelope_state_init(audioif_envelope_state_t *state,
    const audioif_envelope_definition_t *definition);
void audioif_envelope_state_release(audioif_envelope_state_t *state);
void audioif_envelope_state_reattack(audioif_envelope_state_t *state);
void audioif_envelope_state_step(audioif_envelope_state_t *state,
    const audioif_envelope_definition_t *definition, size_t sample_count);

