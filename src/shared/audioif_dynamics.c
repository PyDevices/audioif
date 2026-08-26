// Runtime-neutral dynamics DSP. See audioif_dynamics.h for provenance.
// SPDX-License-Identifier: MIT

#include "shared/audioif_dynamics.h"

#include <math.h>

float audioif_dynamics_ms_to_coef(float ms, float sample_rate) {
    if (ms <= 0.0f) {
        return 1.0f;
    }
    return 1.0f - expf(-1000.0f / (ms * sample_rate));
}

float audioif_dynamics_db_to_gain(float db) {
    return expf(db * 0.115129254649702f);
}

float audioif_dynamics_gain_to_db(float gain) {
    return logf(gain < 1e-6f ? 1e-6f : gain) * 8.68588963806504f;
}

void audioif_dynamics_config_init(audioif_dynamics_config_t *config, int mode,
    uint32_t sample_rate) {
    config->sample_rate = sample_rate;
    config->mode = mode;
    config->threshold_db = -24.0f;
    config->ratio = 4.0f;
    config->knee_db = 6.0f;
    config->makeup_gain = 1.0f;
    config->attack_coef = 0.0f;
    config->release_coef = 0.0f;
    config->attack_gain_db = 0.0f;
    config->sustain_gain_db = 0.0f;
    config->sidechain_coef = 0.0f;
}

void audioif_dynamics_config_finish(audioif_dynamics_config_t *config) {
    if (config->attack_coef == 0.0f) {
        config->attack_coef = audioif_dynamics_ms_to_coef(10.0f,
            (float)config->sample_rate);
    }
    if (config->release_coef == 0.0f) {
        config->release_coef = audioif_dynamics_ms_to_coef(120.0f,
            (float)config->sample_rate);
    }
}

void audioif_dynamics_configure(audioif_dynamics_config_t *config,
    audioif_dynamics_option_t option, float value) {
    switch (option) {
        case AUDIOIF_DYNAMICS_OPT_THRESHOLD_DB:
            config->threshold_db = value;
            break;
        case AUDIOIF_DYNAMICS_OPT_RATIO:
            config->ratio = value < 1.0f ? 1.0f : value;
            break;
        case AUDIOIF_DYNAMICS_OPT_KNEE_DB:
            config->knee_db = value < 0.0f ? 0.0f : value;
            break;
        case AUDIOIF_DYNAMICS_OPT_MAKEUP_DB:
            config->makeup_gain = audioif_dynamics_db_to_gain(value);
            break;
        case AUDIOIF_DYNAMICS_OPT_ATTACK_MS:
            config->attack_coef = audioif_dynamics_ms_to_coef(value,
                (float)config->sample_rate);
            break;
        case AUDIOIF_DYNAMICS_OPT_RELEASE_MS:
            config->release_coef = audioif_dynamics_ms_to_coef(value,
                (float)config->sample_rate);
            break;
        case AUDIOIF_DYNAMICS_OPT_ATTACK_GAIN_DB:
            config->attack_gain_db = value;
            break;
        case AUDIOIF_DYNAMICS_OPT_SUSTAIN_GAIN_DB:
            config->sustain_gain_db = value;
            break;
        case AUDIOIF_DYNAMICS_OPT_SIDECHAIN_HZ:
            config->sidechain_coef = value <= 0.0f ? 0.0f
                : 1.0f - expf(-6.283185307f * value /
                              (float)config->sample_rate);
            break;
    }
}

void audioif_dynamics_state_init(audioif_dynamics_state_t *state) {
    state->sidechain_lp[0] = 0.0f;
    state->sidechain_lp[1] = 0.0f;
    state->envelope = 0.0f;
    state->fast_env = 0.0f;
    state->slow_env = 0.0f;
    state->gain_reduction_db = 0.0f;
}

void audioif_dynamics_reset(audioif_dynamics_state_t *state) {
    state->envelope = 0.0f;
    state->fast_env = 0.0f;
    state->slow_env = 0.0f;
}

// The gain computer: how many dB to apply for a detector reading of `env_db`.
static float dynamics_gain_db(const audioif_dynamics_config_t *config,
    float env_db) {
    const float over = env_db - config->threshold_db;
    switch (config->mode) {
        case AUDIOIF_DYNAMICS_LIMIT:
            return over > 0.0f ? -over : 0.0f;
        case AUDIOIF_DYNAMICS_EXPAND: {
            if (over >= 0.0f) {
                return 0.0f;
            }
            float cut = over * (config->ratio - 1.0f);
            return cut < -60.0f ? -60.0f : cut;
        }
        case AUDIOIF_DYNAMICS_GATE: {
            if (over >= 0.0f) {
                return 0.0f;
            }
            float cut = over * 8.0f;
            return cut < -80.0f ? -80.0f : cut;
        }
        case AUDIOIF_DYNAMICS_COMPRESS:
        default: {
            const float half_knee = config->knee_db * 0.5f;
            const float slope = 1.0f - 1.0f / config->ratio;
            if (over <= -half_knee) {
                return 0.0f;
            }
            if (over < half_knee && config->knee_db > 0.0f) {
                const float x = over + half_knee;
                return -slope * x * x / (2.0f * config->knee_db);
            }
            return -slope * over;
        }
    }
}

void audioif_dynamics_process_s16(const audioif_dynamics_config_t *config,
    audioif_dynamics_state_t *state, int16_t *output, const int16_t *input,
    uint32_t frames) {
    // The transient detectors' time constants are fixed by the shaper's
    // design; only the envelope follower's are settable.
    const float fast_att = audioif_dynamics_ms_to_coef(1.0f,
        (float)config->sample_rate);
    const float fast_rel = audioif_dynamics_ms_to_coef(50.0f,
        (float)config->sample_rate);
    const float slow_att = audioif_dynamics_ms_to_coef(25.0f,
        (float)config->sample_rate);
    const float slow_rel = audioif_dynamics_ms_to_coef(300.0f,
        (float)config->sample_rate);

    while (frames-- != 0) {
        const float left = (float)input[0] / 32768.0f;
        const float right = (float)input[1] / 32768.0f;
        float det_l = left;
        float det_r = right;
        if (config->sidechain_coef > 0.0f) {
            state->sidechain_lp[0] += config->sidechain_coef *
                (left - state->sidechain_lp[0]);
            state->sidechain_lp[1] += config->sidechain_coef *
                (right - state->sidechain_lp[1]);
            det_l = left - state->sidechain_lp[0];
            det_r = right - state->sidechain_lp[1];
        }
        float level = fabsf(det_l);
        const float level_r = fabsf(det_r);
        if (level_r > level) {
            level = level_r;
        }
        float gain_db;
        if (config->mode == AUDIOIF_DYNAMICS_TRANSIENT) {
            state->fast_env += (level > state->fast_env ? fast_att : fast_rel)
                * (level - state->fast_env);
            state->slow_env += (level > state->slow_env ? slow_att : slow_rel)
                * (level - state->slow_env);
            const float diff =
                audioif_dynamics_gain_to_db(state->fast_env + 1e-5f) -
                audioif_dynamics_gain_to_db(state->slow_env + 1e-5f);
            float norm = diff / 6.0f;
            if (norm > 1.0f) {
                norm = 1.0f;
            } else if (norm < -1.0f) {
                norm = -1.0f;
            }
            gain_db = norm > 0.0f ? config->attack_gain_db * norm
                                  : config->sustain_gain_db * -norm;
        } else {
            const bool rising = level > state->envelope;
            state->envelope += (rising ? config->attack_coef
                                       : config->release_coef)
                * (level - state->envelope);
            gain_db = dynamics_gain_db(config,
                audioif_dynamics_gain_to_db(state->envelope + 1e-6f));
        }
        state->gain_reduction_db = gain_db;
        const float gain = audioif_dynamics_db_to_gain(gain_db) *
            config->makeup_gain;
        float out_l = left * gain * 32768.0f;
        float out_r = right * gain * 32768.0f;
        if (out_l > 32767.0f) {
            out_l = 32767.0f;
        } else if (out_l < -32768.0f) {
            out_l = -32768.0f;
        }
        if (out_r > 32767.0f) {
            out_r = 32767.0f;
        } else if (out_r < -32768.0f) {
            out_r = -32768.0f;
        }
        output[0] = (int16_t)out_l;
        output[1] = (int16_t)out_r;
        input += 2;
        output += 2;
    }
}
