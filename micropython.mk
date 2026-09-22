# MicroPython Make glue for the audio pump's platform driver (unix, windows).
#
# The engine is not here any more: the pull loop, the ring, the events, the tap
# and the lock all live in audiodsp and are built by audiodsp's own glue. This
# builds the one file that knows what a thread, a mutex, a clock and a sink
# are, and it compiles against audiodsp's headers -- AUDIODSP_DIR points at the
# audiodsp checkout, and the default assumes the usual workspace layout (this
# repo and audiodsp as siblings).

AUDIOPUMP_MOD_DIR := $(USERMOD_DIR)
AUDIODSP_DIR ?= $(abspath $(AUDIOPUMP_MOD_DIR)/../audiodsp)

CFLAGS_USERMOD += -I$(AUDIODSP_DIR)/src
SRC_USERMOD_C += $(AUDIOPUMP_MOD_DIR)/_audioif.c
SRC_USERMOD_C += $(AUDIOPUMP_MOD_DIR)/audiobusio.c

# --- which audioif this firmware was built from ----------------------
# Computed at build time from this repo's own git, never stored; "unknown" when
# there is no git (a tarball). Read on a target as <module>.__revision__.
AUDIOIF_REVISION := $(shell git -C $(AUDIOPUMP_MOD_DIR) describe --always --dirty --abbrev=7 2>/dev/null || echo unknown)
CFLAGS_USERMOD += -DAUDIOIF_REVISION='"$(AUDIOIF_REVISION)"'
