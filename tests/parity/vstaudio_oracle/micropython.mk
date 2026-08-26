# Oracle-only usermod: see module.c. Built by capture_dynamics_oracle.sh into
# its own scratch workspace, never by cmods/build_mp.sh.
#
# VSTAUDIO_DSP is the unmodified DSP source in the sibling micropython-vst3
# checkout. Override it if that tree lives somewhere else.

VSTAUDIO_ORACLE_DIR := $(USERMOD_DIR)
VSTAUDIO_DSP ?= $(abspath $(VSTAUDIO_ORACLE_DIR)/../micropython-vst3/usermods/vstaudio/vstaudio_dsp.c)

ifeq ($(wildcard $(VSTAUDIO_DSP)),)
$(error vstaudio_dsp.c not found at $(VSTAUDIO_DSP) -- pass VSTAUDIO_DSP=<path>)
endif

# The original was built with this warning downgraded (its float math promotes
# freely); audioif compiles with -Werror, so keep the original's own terms.
CFLAGS_USERMOD += -Wno-error=double-promotion

SRC_USERMOD_C += $(VSTAUDIO_DSP)
SRC_USERMOD_C += $(VSTAUDIO_ORACLE_DIR)/module.c
