// Ported from CircuitPython's shared-bindings+shared-module/audiospeed/
// Resampler.{h,c} (upstream repo: https://github.com/adafruit/circuitpython,
// MIT), added in CircuitPython 10.3.0. Merged into one header/source pair --
// see audiomixer/Mixer.h for why this port doesn't keep the
// shared-bindings/shared-module split.
//
// A Resampler is a SpeedChanger whose ratio nobody sets by hand: it is bound
// when a downstream node is handed one, from that node's own sample rate.
// Upstream expresses that by giving both types a shared `audiospeed_base_t`;
// this port's SpeedChanger predates that refactor, so the Resampler embeds a
// SpeedChanger instead and reuses its `get_buffer`/`reset_buffer` unchanged --
// the same audio path, the same fixed-point accumulator, one ratio arrived at
// differently.
//
// SPDX-FileCopyrightText: Copyright (c) 2026 Cooper Dalrymple
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "audiocore/__init__.h"
#include "audiospeed/SpeedChanger.h"
#include "py/obj.h"

typedef struct {
    // First member, so a Resampler is a valid `audiospeed_speedchanger_obj_t *`
    // and a valid `audiosample_base_t *` -- which is what lets the protocol
    // functions and audiocore's guards take one untouched.
    audiospeed_speedchanger_obj_t speed;
    // The destination rate, as bound by whoever played this node. 0 means
    // nothing has played it yet and the ratio is still 1.0.
    uint32_t destination_rate;
} audiospeed_resampler_obj_t;

extern const mp_obj_type_t audiospeed_resampler_type;

// Bind the ratio from a destination's sample rate. Called from
// `audiosample_must_match`, which every node's `play()` goes through, so one
// call site covers the whole palette -- exactly where upstream puts it.
void audiospeed_resampler_set_sample_rate(audiospeed_resampler_obj_t *self,
    uint32_t sample_rate);
