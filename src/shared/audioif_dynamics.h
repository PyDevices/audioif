// Runtime-neutral dynamics DSP: an envelope-follower gain computer covering
// compression, limiting, downward expansion, gating and transient shaping,
// with an optional high-passed detector for de-essing.
//
// Ported from micropython-vst3's usermods/vstaudio/vstaudio_dsp.c, which is
// where the effects library's compressors have always lived. The arithmetic
// is unchanged, including the `float` working precision -- moving it to
// double would be a better filter and a different one, and the whole point of
// this file is that the ports keep sounding like the original.
//
// The source-pulling loop is not here: each runtime reaches its audio graph
// differently, so the bindings own the loop and call in with runs of frames.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    AUDIOIF_DYNAMICS_COMPRESS = 0,
    AUDIOIF_DYNAMICS_LIMIT = 1,
    AUDIOIF_DYNAMICS_EXPAND = 2,
    AUDIOIF_DYNAMICS_GATE = 3,
    AUDIOIF_DYNAMICS_TRANSIENT = 4,
} audioif_dynamics_mode_t;

//: Frames one output block carries. The original chose it to match the
//: engine's block size, and the effects library's latency assumptions --
//: notably the Splitter ring's depth -- are written around it.
#define AUDIOIF_DYNAMICS_FRAMES 256u

//: The settable options, in the order the bindings' keyword tables list them.
typedef enum {
    AUDIOIF_DYNAMICS_OPT_THRESHOLD_DB = 0,
    AUDIOIF_DYNAMICS_OPT_RATIO,
    AUDIOIF_DYNAMICS_OPT_KNEE_DB,
    AUDIOIF_DYNAMICS_OPT_MAKEUP_DB,
    AUDIOIF_DYNAMICS_OPT_ATTACK_MS,
    AUDIOIF_DYNAMICS_OPT_RELEASE_MS,
    AUDIOIF_DYNAMICS_OPT_ATTACK_GAIN_DB,
    AUDIOIF_DYNAMICS_OPT_SUSTAIN_GAIN_DB,
    AUDIOIF_DYNAMICS_OPT_SIDECHAIN_HZ,
    AUDIOIF_DYNAMICS_OPT_LOOKAHEAD_MS,
    AUDIOIF_DYNAMICS_OPT_TRUE_PEAK,
} audioif_dynamics_option_t;

//: How far ahead the detector may be allowed to look. A cap rather than a
//: preference: the buffer is audio in flight, so it is latency the whole
//: chain pays, and past a few milliseconds a limiter stops sounding like a
//: limiter and starts sounding like it is ducking before the note.
#define AUDIOIF_DYNAMICS_MAX_LOOKAHEAD_MS 50.0f

//: Everything derived from the constructor/`set()` arguments. Held apart from
//: the running state so `set()` can rewrite it mid-stream without disturbing
//: the detector.
typedef struct {
    uint32_t sample_rate;
    // Interleaved audio width. The bounded state arrays remain two entries so
    // mono and stereo use one implementation.
    uint32_t channel_count;
    int mode;
    float threshold_db;
    float ratio;
    float knee_db;
    float makeup_gain;      // linear
    float attack_coef;
    float release_coef;
    float attack_gain_db;   // transient mode
    float sustain_gain_db;
    float sidechain_coef;   // one-pole low-pass coefficient; 0 = full band
    // Both default off, so a Dynamics built the way the original was is the
    // original. See the process loop for what each costs.
    uint32_t lookahead_frames;
    bool true_peak;
} audioif_dynamics_config_t;

//: What the detector remembers between blocks.
typedef struct {
    uint32_t channel_count;
    float sidechain_lp[2];
    float envelope;         // main detector, linear 0..1
    float fast_env;         // transient mode detectors
    float slow_env;
    float gain_reduction_db;
    // The audio held back while the detector reads ahead of it. The buffer
    // belongs to the bindings, which allocate it only when someone asks for
    // lookahead -- an unconditional 50 ms of stereo is 9.6 KB per instance,
    // and audioeffects builds nine of these.
    int16_t *lookahead;
    uint32_t lookahead_capacity;
    uint32_t lookahead_write;
    // Three detector samples back per channel, for the half-sample estimate.
    float peak_history[2][3];
} audioif_dynamics_state_t;

float audioif_dynamics_ms_to_coef(float ms, float sample_rate);
float audioif_dynamics_db_to_gain(float db);
float audioif_dynamics_gain_to_db(float gain);

// Defaults, with the attack/release coefficients left at zero: apply the
// caller's options next, then call _finish(), which fills in the 10 ms / 120 ms
// defaults only if nothing set them. Splitting it this way keeps the original
// constructor's behaviour, quirk included -- an attack_ms so long that its
// coefficient rounds to zero silently gets the default instead.
void audioif_dynamics_config_init(audioif_dynamics_config_t *config, int mode,
    uint32_t sample_rate);
void audioif_dynamics_config_finish(audioif_dynamics_config_t *config);

// Apply one option. `sample_rate` is not among them: the millisecond
// conversions depend on it, so a binding must write it into the config before
// applying anything else, however its own keywords happened to be ordered.
void audioif_dynamics_configure(audioif_dynamics_config_t *config,
    audioif_dynamics_option_t option, float value);

void audioif_dynamics_state_init(audioif_dynamics_state_t *state);

// Select mono or stereo processing before configuring lookahead storage.
void audioif_dynamics_set_channel_count(
    audioif_dynamics_config_t *config, audioif_dynamics_state_t *state,
    uint32_t channel_count);

// How many frames of lookahead buffer the current config wants. Bindings call
// this after applying options and hand back storage of at least that size;
// the DSP uses whatever it has, so a binding that allocates nothing simply
// gets no lookahead rather than reading off the end.
uint32_t audioif_dynamics_lookahead_frames(
    const audioif_dynamics_config_t *config);
void audioif_dynamics_set_lookahead(audioif_dynamics_state_t *state,
    int16_t *buffer, uint32_t frames);

// What the audiosample protocol's reset_buffer does: drop the detector
// envelopes but keep the sidechain filter's memory and the last reported gain
// reduction, matching the original exactly.
void audioif_dynamics_reset(audioif_dynamics_state_t *state);

// Process `frames` interleaved stereo frames. Input and output may not alias.
void audioif_dynamics_process_s16(const audioif_dynamics_config_t *config,
    audioif_dynamics_state_t *state, int16_t *output, const int16_t *input,
    uint32_t frames);
