// Runtime-neutral signal splitter: fans one audio stream out to several taps
// with independent read cursors over a shared ring, so one source can feed
// parallel branches (an exciter, a Haas widener, multiband splits) that a
// Mixer then sums back together.
//
// Ported from micropython-vst3's usermods/vstaudio/vstaudio_dsp.c.
//
// Whichever tap is pulled first refills the ring; the others read what it
// wrote. A tap nobody reads must not wedge the ring, so writing past a
// laggard's cursor drags that cursor forward and silently drops what it never
// collected -- the branch skips ahead rather than stalling the graph.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define AUDIOIF_SPLITTER_RING_FRAMES 8192u
#define AUDIOIF_SPLITTER_MAX_TAPS 4u
#define AUDIOIF_SPLITTER_CHUNK_FRAMES 256u

typedef struct {
    uint32_t tap_count;
    uint32_t channel_count;
    uint32_t write_pos;
    uint32_t read_pos[AUDIOIF_SPLITTER_MAX_TAPS];
    int16_t ring[AUDIOIF_SPLITTER_RING_FRAMES * 2];
} audioif_splitter_state_t;

void audioif_splitter_init(audioif_splitter_state_t *state, uint32_t tap_count);

void audioif_splitter_set_channel_count(audioif_splitter_state_t *state,
    uint32_t channel_count);

// Append interleaved stereo frames, dragging any cursor the write laps.
void audioif_splitter_write(audioif_splitter_state_t *state,
    const int16_t *frames, uint32_t count);

// True when `tap` has read everything written -- the caller's cue to pull the
// source for more.
static inline bool audioif_splitter_starved(
    const audioif_splitter_state_t *state, uint32_t tap) {
    return state->write_pos == state->read_pos[tap];
}

// Claim the next run of frames for `tap`, at most one chunk and never across
// the ring's wrap. Returns the frame count and writes the ring frame index it
// starts at; zero means the tap has caught up and the caller should hand out
// silence.
uint32_t audioif_splitter_take(audioif_splitter_state_t *state, uint32_t tap,
    uint32_t *start_frame);
