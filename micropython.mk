# MicroPython Make glue for the audio pump's platform driver (unix, windows).
#
# The engine is not here any more: the pull loop, the ring, the events, the tap
# and the lock all live in audioif and are built by audioif's own glue. This
# builds the one file that knows what a thread, a mutex, a clock and a sink
# are, and it compiles against audioif's headers -- AUDIOIF_DIR points at the
# audioif checkout, and the default assumes the usual workspace layout (this
# repo and audioif as siblings).

AUDIOPUMP_MOD_DIR := $(USERMOD_DIR)
AUDIOIF_DIR ?= $(abspath $(AUDIOPUMP_MOD_DIR)/../audioif)

CFLAGS_USERMOD += -I$(AUDIOIF_DIR)/src
SRC_USERMOD_C += $(AUDIOPUMP_MOD_DIR)/_audioif.c
