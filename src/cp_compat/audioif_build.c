// The two build strings, defined once. See audioif_build.h.
//
// SPDX-FileCopyrightText: Copyright (c) 2026 PyDevices
// SPDX-License-Identifier: MIT

#include "cp_compat/audioif_build.h"

#include "py/objstr.h"

// Passed by micropython.mk / micropython.cmake. A build that reaches here
// without them says so rather than claiming a revision it does not know --
// "unknown" is the honest answer and the one that made this file necessary.
#ifndef AUDIOIF_VERSION
#define AUDIOIF_VERSION "0.0.0+unknown"
#endif
#ifndef AUDIOIF_REVISION
#define AUDIOIF_REVISION "unknown"
#endif

const MP_DEFINE_STR_OBJ(audioif_version_obj, AUDIOIF_VERSION);
const MP_DEFINE_STR_OBJ(audioif_revision_obj, AUDIOIF_REVISION);
