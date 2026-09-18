# MicroPython Make glue for audiopump (unix, windows).
#
# audiopump compiles against audioif's headers but declares no dependency on
# its build: the symbols it calls (`audioif_sample_get`, and the protocol
# struct's own function pointers) come from audioif's objects in the same
# binary. AUDIOIF_DIR points at the audioif checkout; the default assumes the
# usual workspace layout (audiopump and audioif as siblings).

AUDIOPUMP_MOD_DIR := $(USERMOD_DIR)
AUDIOIF_DIR ?= $(abspath $(AUDIOPUMP_MOD_DIR)/../audioif)

CFLAGS_USERMOD += -I$(AUDIOIF_DIR)/src
SRC_USERMOD_C += $(AUDIOPUMP_MOD_DIR)/audiopump.c
