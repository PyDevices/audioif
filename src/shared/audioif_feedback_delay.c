// Runtime-neutral feedback delay. See audioif_feedback_delay.h for what is in
// the loop and why none of it could be done outside one.
//
// `float` working precision, deliberately, to match audioif_dynamics.c: this
// runs per sample on parts without an FPU at all, and doubles would cost more
// than the last few bits are worth in a feedback path that is already storing
// its line as int16.
//
// SPDX-License-Identifier: MIT

#include "shared/audioif_feedback_delay.h"

#include <math.h>
#include <string.h>

#define AUDIOIF_FEEDBACK_DELAY_PI 3.14159265358979323846f

static float clampf(float value, float low, float high) {
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}

// 1 - exp(-2*pi*fc/fs): the one-pole coefficient both loop filters use. Zero
// means "no filter", which is why a cutoff of zero has to fall out here
// rather than being special-cased in the loop.
static float one_pole_coefficient(float hz, uint32_t sample_rate) {
    if (hz <= 0.0f || sample_rate == 0) {
        return 0.0f;
    }
    float coefficient =
        1.0f - expf(-2.0f * AUDIOIF_FEEDBACK_DELAY_PI * hz / (float)sample_rate);
    return clampf(coefficient, 0.0f, 1.0f);
}

void audioif_feedback_delay_config_init(
    audioif_feedback_delay_config_t *config, uint32_t sample_rate,
    uint32_t line_frames) {
    config->sample_rate = sample_rate ? sample_rate : 48000;
    config->line_frames = line_frames < 2 ? 2 : line_frames;
    config->delay_frames = (float)config->line_frames * 0.5f;
    config->feedback = 0.4f;
    config->mix = 0.3f;
    config->damping_coef = 0.0f;
    config->cut_coef = 0.0f;
    config->wow_step = 0.0f;
    config->wow_depth_frames = 0.0f;
    config->cross_feed = 0.0f;
    config->loop_drive = 0.0f;
    config->damping_hz = 0.0f;
    config->cut_hz = 0.0f;
    config->wow_hz = 0.0f;
    audioif_feedback_delay_configure(config,
        AUDIOIF_FEEDBACK_DELAY_OPT_INPUT_PAN, 0.0f);
}

void audioif_feedback_delay_configure(audioif_feedback_delay_config_t *config,
    audioif_feedback_delay_option_t option, float value) {
    const float rate = (float)config->sample_rate;
    switch (option) {
        case AUDIOIF_FEEDBACK_DELAY_OPT_DELAY_MS: {
            // One frame of headroom below the line's length: the read walks
            // backward from the write cursor and interpolates between two
            // neighbours, so it must not be able to land on the cursor itself.
            float frames = value * rate / 1000.0f;
            config->delay_frames =
                clampf(frames, 1.0f, (float)config->line_frames - 2.0f);
            break;
        }
        case AUDIOIF_FEEDBACK_DELAY_OPT_FEEDBACK:
            // Stops just short of 1: at exactly unity a loop with no filter
            // in it never decays, and with the soft-clip engaged it settles
            // into a self-oscillation that is not what anyone asked for.
            config->feedback = clampf(value, 0.0f, 0.99f);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_MIX:
            // 0..2, and the dry stays at unity until 1 -- `audiodelays.Echo`'s
            // convention, adopted deliberately rather than crossfaded. Six
            // delay classes sit on top of these two modules and `mix` has to
            // mean one thing across all of them; three of them are Echo's and
            // that convention is CircuitPython's to set. So 0.3 is "dry, plus
            // 30 percent wet", 1 is "dry plus all of it", and 2 is wet alone.
            config->mix = clampf(value, 0.0f, 2.0f);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_DAMPING_HZ:
            config->damping_hz = value;
            config->damping_coef = one_pole_coefficient(value,
                config->sample_rate);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_CUT_HZ:
            config->cut_hz = value;
            config->cut_coef = one_pole_coefficient(value,
                config->sample_rate);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_WOW_HZ:
            config->wow_hz = value;
            config->wow_step = value <= 0.0f ? 0.0f :
                2.0f * sinf(AUDIOIF_FEEDBACK_DELAY_PI * value / rate);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_WOW_DEPTH_MS:
            config->wow_depth_frames =
                clampf(value, 0.0f, 1000.0f) * rate / 1000.0f;
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_CROSS_FEED:
            config->cross_feed = clampf(value, 0.0f, 1.0f);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_LOOP_DRIVE:
            config->loop_drive = clampf(value, 0.0f, 1.0f);
            break;
        case AUDIOIF_FEEDBACK_DELAY_OPT_INPUT_PAN: {
            // -1 sends both channels into the left line and nothing into the
            // right, +1 the reverse, 0 leaves each channel on its own line.
            // Hard over is what makes a real ping-pong: the first repeat is
            // on one side only, and the cross-feed alternates it after that.
            //
            // Hard over sends the *average* of the two channels rather than
            // their sum: a mono source panned into one line would otherwise
            // arrive 6 dB hot and clip on the first repeat.
            const float pan = clampf(value, -1.0f, 1.0f);
            const float to_left = pan < 0.0f ? -pan : 0.0f;
            const float to_right = pan > 0.0f ? pan : 0.0f;
            config->feed_own[0] = 1.0f - to_left * 0.5f - to_right;
            config->feed_other[0] = to_left * 0.5f;
            config->feed_own[1] = 1.0f - to_right * 0.5f - to_left;
            config->feed_other[1] = to_right * 0.5f;
            break;
        }
    }
}

void audioif_feedback_delay_config_finish(
    audioif_feedback_delay_config_t *config) {
    audioif_feedback_delay_configure(config,
        AUDIOIF_FEEDBACK_DELAY_OPT_DAMPING_HZ, config->damping_hz);
    audioif_feedback_delay_configure(config,
        AUDIOIF_FEEDBACK_DELAY_OPT_CUT_HZ, config->cut_hz);
    audioif_feedback_delay_configure(config,
        AUDIOIF_FEEDBACK_DELAY_OPT_WOW_HZ, config->wow_hz);
}

void audioif_feedback_delay_state_init(audioif_feedback_delay_state_t *state,
    int16_t *line) {
    state->line = line;
    state->write_frame = 0;
    state->damping_state[0] = state->damping_state[1] = 0.0f;
    state->cut_state[0] = state->cut_state[1] = 0.0f;
    state->wow_sine = 0.0f;
    state->wow_cosine = 1.0f;
}

void audioif_feedback_delay_reset(audioif_feedback_delay_state_t *state,
    const audioif_feedback_delay_config_t *config) {
    if (state->line != NULL) {
        memset(state->line, 0,
            (size_t)config->line_frames * 2u * sizeof(int16_t));
    }
    int16_t *line = state->line;
    audioif_feedback_delay_state_init(state, line);
}

// The one place the whole thing is not linear. A cubic is enough: it is
// odd-symmetric, so it makes third-harmonic thickening and no second, and it
// costs two multiplies where a tanh would cost a library call per sample.
static float soft_clip(float value, float drive) {
    const float normalized = clampf(value * (1.0f / 32768.0f), -1.0f, 1.0f);
    return 32768.0f *
        (normalized - drive * normalized * normalized * normalized / 3.0f);
}

static int16_t to_s16(float value) {
    if (value > 32767.0f) {
        return 32767;
    }
    if (value < -32768.0f) {
        return -32768;
    }
    return (int16_t)(value >= 0.0f ? value + 0.5f : value - 0.5f);
}

void audioif_feedback_delay_process_s16(
    const audioif_feedback_delay_config_t *config,
    audioif_feedback_delay_state_t *state, int16_t *out, const int16_t *in,
    uint32_t frames) {
    const uint32_t length = config->line_frames;
    const float dry = 2.0f - config->mix < 1.0f ? 2.0f - config->mix : 1.0f;
    const float wet = config->mix < 1.0f ? config->mix : 1.0f;
    const float direct = 1.0f - config->cross_feed;
    const float crossed = config->cross_feed;
    for (uint32_t frame = 0; frame < frames; ++frame) {
        // Rotate the wow oscillator one step. Updating the sine first and
        // feeding the new value back into the cosine is what keeps this
        // stable indefinitely; the naive pair drifts in amplitude.
        state->wow_sine += config->wow_step * state->wow_cosine;
        state->wow_cosine -= config->wow_step * state->wow_sine;

        float offset = config->delay_frames +
            config->wow_depth_frames * state->wow_sine;
        offset = clampf(offset, 1.0f, (float)length - 2.0f);
        const uint32_t whole = (uint32_t)offset;
        const float fraction = offset - (float)whole;
        const uint32_t near_frame =
            (state->write_frame + length - whole) % length;
        const uint32_t far_frame =
            (near_frame + length - 1u) % length;

        float loop[2];
        for (uint32_t channel = 0; channel < 2u; ++channel) {
            const int16_t *lane = state->line + (size_t)channel * length;
            const float near_sample = (float)lane[near_frame];
            const float delayed = near_sample +
                fraction * ((float)lane[far_frame] - near_sample);

            float value = delayed;
            if (config->damping_coef > 0.0f) {
                state->damping_state[channel] += config->damping_coef *
                    (value - state->damping_state[channel]);
                value = state->damping_state[channel];
            }
            if (config->cut_coef > 0.0f) {
                state->cut_state[channel] += config->cut_coef *
                    (value - state->cut_state[channel]);
                value -= state->cut_state[channel];
            }
            if (config->loop_drive > 0.0f) {
                value = soft_clip(value, config->loop_drive);
            }
            loop[channel] = value;
        }

        for (uint32_t channel = 0; channel < 2u; ++channel) {
            const float sent = loop[channel] * direct +
                loop[1u - channel] * crossed;
            const float source = (float)in[frame * 2u + channel];
            const float fed = source * config->feed_own[channel] +
                (float)in[frame * 2u + (1u - channel)] *
                config->feed_other[channel];
            state->line[(size_t)channel * length + state->write_frame] =
                to_s16(fed + config->feedback * sent);
            // The dry path is the channel's own signal, never the panned
            // one: `input_pan` steers what goes round the loop, not what the
            // listener hears straight through.
            out[frame * 2u + channel] =
                to_s16(dry * source + wet * loop[channel]);
        }
        state->write_frame = (state->write_frame + 1u) % length;
    }
}
