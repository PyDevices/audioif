// Runtime-neutral feedback delay with everything a repeat needs inside the
// loop: a low-pass, a high-pass, a soft-clip, per-sample delay modulation,
// and a cross-feed between the channels.
//
// New code -- not a CircuitPython port, and not from vstaudio either.
// `audiodelays.Echo` exists upstream and has none of it: its feedback path is
// `echo * decay` and nothing else. Everything a delay is actually *called*
// falls out of what happens in that path, so without it there is one delay
// with a level knob:
//
//   * **Tape.** Each pass through a tape machine loses top and bottom and
//     softens, so the repeats darken and blur into the reverb tail. Filtering
//     the whole wet signal once, after the delay, is not the same thing at
//     all -- it darkens the first repeat as much as the tenth.
//   * **Analog / BBD.** The same, further: a bucket-brigade line is noisy and
//     band-limited by construction, and its clock drifts.
//   * **Ping-pong.** Repeats alternating between the speakers needs each
//     channel's output fed into the *other* channel's line. Panning two taps
//     hard left and right, which is all the palette could do before, gives
//     two independent delays that happen to sit either side.
//
// The delay modulation is per sample rather than per block, which is the
// second thing upstream cannot reach: an LFO-driven `delay_ms` updates once
// per buffer, about 187 Hz at 48 kHz, so it steps rather than glides and the
// doppler that makes tape wow sound like tape is not there.
//
// The pulling loop is not here, for the same reason it is not in
// audioif_dynamics.c: each runtime reaches its audio graph differently.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

//: Frames one output block carries. The same 256 audiodynamics and audiomath
//: use, so a chain built out of several of them moves in one block size.
#define AUDIOIF_FEEDBACK_DELAY_FRAMES 256u

//: The settable options, in the order the bindings' keyword tables list them.
typedef enum {
    AUDIOIF_FEEDBACK_DELAY_OPT_DELAY_MS = 0,
    AUDIOIF_FEEDBACK_DELAY_OPT_FEEDBACK,
    AUDIOIF_FEEDBACK_DELAY_OPT_MIX,
    AUDIOIF_FEEDBACK_DELAY_OPT_DAMPING_HZ,
    AUDIOIF_FEEDBACK_DELAY_OPT_CUT_HZ,
    AUDIOIF_FEEDBACK_DELAY_OPT_WOW_HZ,
    AUDIOIF_FEEDBACK_DELAY_OPT_WOW_DEPTH_MS,
    AUDIOIF_FEEDBACK_DELAY_OPT_CROSS_FEED,
    AUDIOIF_FEEDBACK_DELAY_OPT_LOOP_DRIVE,
    AUDIOIF_FEEDBACK_DELAY_OPT_INPUT_PAN,
} audioif_feedback_delay_option_t;

//: Everything derived from the constructor/`set()` arguments. Held apart from
//: the running state so `set()` can rewrite it mid-stream without disturbing
//: the line or the filters.
typedef struct {
    uint32_t sample_rate;
    // Frames of line per channel. Fixed at construction: it is what was
    // allocated, and `delay_ms` is clamped against it.
    uint32_t line_frames;
    float delay_frames;
    float feedback;
    // 0..2, the dry at unity until 1: `audiodelays.Echo`'s convention. See
    // the process loop for why this module follows it rather than fixing it.
    float mix;
    // One-pole coefficients, 0 meaning the filter is out of the loop.
    float damping_coef;
    float cut_coef;
    // Rotation constant for the wow oscillator, and its depth in frames.
    float wow_step;
    float wow_depth_frames;
    float cross_feed;
    float loop_drive;
    // How much of each channel's input reaches its own line and the other
    // one, from `input_pan`. Both lanes need their own pair: panning the
    // input hard left means the left line takes both channels and the right
    // line takes neither, which is not a symmetric operation.
    float feed_own[2];
    float feed_other[2];
    // The frequency-shaped options as they were asked for, so a change of
    // sample rate can recompute their coefficients.
    float damping_hz;
    float cut_hz;
    float wow_hz;
} audioif_feedback_delay_config_t;

typedef struct {
    // 2 * line_frames samples, channel-major: [channel * line_frames + frame].
    // The bindings own it; this struct only borrows the pointer.
    int16_t *line;
    uint32_t write_frame;
    float damping_state[2];
    float cut_state[2];
    // Magic-circle oscillator: two states rotated by `wow_step` per frame,
    // which is two multiplies where sinf() would be a library call.
    float wow_sine;
    float wow_cosine;
} audioif_feedback_delay_state_t;

void audioif_feedback_delay_config_init(
    audioif_feedback_delay_config_t *config, uint32_t sample_rate,
    uint32_t line_frames);

// Applies immediately, against whatever `sample_rate` is currently set --
// so set that first, as the bindings' keyword tables do.
void audioif_feedback_delay_configure(audioif_feedback_delay_config_t *config,
    audioif_feedback_delay_option_t option, float value);

// Recomputes everything that depends on the sample rate. Call after changing
// it, and once after construction.
void audioif_feedback_delay_config_finish(
    audioif_feedback_delay_config_t *config);

void audioif_feedback_delay_state_init(audioif_feedback_delay_state_t *state,
    int16_t *line);

// Clears the line and the filters. Unlike audiodynamics' reset this really
// does drop everything: a delay's whole state is audible, and a chain that
// restarts with the old repeats still in the line plays the previous take.
void audioif_feedback_delay_reset(audioif_feedback_delay_state_t *state,
    const audioif_feedback_delay_config_t *config);

// Interleaved stereo frames in and out. `out` may alias `in`.
void audioif_feedback_delay_process_s16(
    const audioif_feedback_delay_config_t *config,
    audioif_feedback_delay_state_t *state, int16_t *out, const int16_t *in,
    uint32_t frames);
