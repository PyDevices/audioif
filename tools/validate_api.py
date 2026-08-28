#!/usr/bin/env python3
"""Validate the live audio-component API across the provider catalogue.

This is intentionally a small runtime check rather than an inheritance check:
the public contract is structural and a future rack or third-party provider
may implement it without using audioeffects._core.Effect.
"""

import array
import sys

import audiocore
import audioeffects
import audioinstruments


COMMON_METHODS = (
    "set_macro", "program_change", "get_macro", "reset", "deinit",
)
INSTRUMENT_METHODS = (
    "note_on", "note_off", "all_notes_off", "pitch_bend", "control_change",
    "channel_pressure", "poly_pressure",
)
EFFECT_METHODS = (
    "pitch_bend", "control_change", "channel_pressure", "poly_pressure",
)
PROPERTIES = (
    "output", "sample_rate", "channel_count", "latency_samples",
    "tail_samples", "capabilities", "patch_index",
)


def _source(channel_count=2):
    return audiocore.RawSample(
        array.array("h", [0] * 256 * channel_count),
        sample_rate=48000, channel_count=channel_count)


def _check(component, label, effect):
    for name in COMMON_METHODS + (EFFECT_METHODS if effect else
                                  INSTRUMENT_METHODS):
        if not callable(getattr(component, name, None)):
            raise TypeError("%s has no callable %s" % (label, name))
    for name in PROPERTIES:
        getattr(component, name)
    if not isinstance(component.capabilities, tuple):
        raise TypeError("%s capabilities is not a tuple" % label)
    for capability in component.capabilities:
        if (not isinstance(capability, str)
                or any(ord(character) >= 128 for character in capability)):
            raise TypeError("%s has a non-ASCII capability" % label)
    if component.sample_rate != 48000:
        raise ValueError("%s has the wrong sample rate" % label)
    if component.channel_count != 2:
        raise ValueError("%s has the wrong channel count" % label)
    if component.patch_index != 0:
        raise ValueError("%s did not start on patch 0" % label)
    result, data = audiocore.get_buffer(component.output, False, 0)
    if len(data) == 0 or len(data) % (2 * component.channel_count):
        raise ValueError("%s returned malformed audio" % label)
    labels = getattr(component, "macro_labels", None)
    if labels is None:
        labels = getattr(component, "MACRO_LABELS", ())
    if labels:
        component.set_macro(0, 64)
        if component.patch_index is not None:
            raise ValueError("%s did not enter custom macro state" % label)
        component.program_change(0)
    else:
        try:
            component.get_macro(0)
        except IndexError:
            pass
        else:
            raise ValueError("%s accepted a nonexistent macro" % label)


def validate():
    failures = []
    if len(audioinstruments.ALL) != len(set(audioinstruments.ALL)):
        failures.append("audioinstruments.ALL contains duplicates")
    if len(audioeffects.ALL) != len(set(audioeffects.ALL)):
        failures.append("audioeffects.ALL contains duplicates")

    for name in audioinstruments.ALL:
        component = None
        try:
            component = audioinstruments.create(name, 48000)
            _check(component, "instrument %s" % name, False)
        except Exception as exc:
            failures.append("instrument %s: %s" % (name, exc))
        finally:
            if component is not None:
                component.deinit()

    for name in audioeffects.ALL:
        component = None
        try:
            component = audioeffects.create(name, _source(), 48000)
            _check(component, "effect %s" % name, True)
        except Exception as exc:
            failures.append("effect %s: %s" % (name, exc))
        finally:
            if component is not None:
                component.deinit()
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("validated %d instruments and %d effects" %
          (len(audioinstruments.ALL), len(audioeffects.ALL)))
    return 0


if __name__ == "__main__":
    raise SystemExit(validate())
