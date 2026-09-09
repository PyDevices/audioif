# Configure-only harness for audioif's CMake glue (audioif#35).
#
#   cmake -S tests/cmake -B <build dir> \
#         -DMICROPY_DIR=<micropython checkout> \
#         -DUSER_C_MODULES=<this checkout>
#
# Nothing in CI ran CMake until this existed: `clean-build.yml` builds through
# `micropython.mk` only, so an edit to `micropython.cmake` -- or to the CMake
# recipe in the README -- could break the standalone CMake path exactly as it
# was broken before, and every workflow would stay green. The whole check is
# the *configure* step, which takes seconds and needs no compiler and no
# firmware: it drives MicroPython's own `py/usermod.cmake` the way a real port
# does, and then asserts what that must have produced.
#
# `project(... NONE)` on purpose: no language is enabled, so this never looks
# for a cross-compiler.
cmake_minimum_required(VERSION 3.16)
project(audioif_usermod_configure NONE)

foreach(required MICROPY_DIR USER_C_MODULES)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "pass -D${required}=<path>")
    endif()
    if(NOT EXISTS ${${required}})
        message(FATAL_ERROR "${required} does not exist: ${${required}}")
    endif()
endforeach()

# What a port does. `usermod.cmake` creates the `usermod` target, includes
# `py/manifest.cmake`, and then includes each USER_C_MODULES entry's
# `micropython.cmake`.
include(${MICROPY_DIR}/py/usermod.cmake)

# 1. The targets. `usermod_mpaudio` is this repo's own; `usermod_ulab` comes
#    from the ulab clone that `micropython.cmake`'s guarded block includes,
#    and is the half that had actually broken once - so its absence is a
#    failure here, not a warning.
foreach(target usermod usermod_mpaudio usermod_ulab)
    if(NOT TARGET ${target})
        message(FATAL_ERROR
            "audioif's CMake glue did not define the ${target} target")
    endif()
    message(STATUS "audioif cmake check: target ${target} ok")
endforeach()

# 2. `usermod_mpaudio` is linked into `usermod`, which is what actually makes
#    a port compile any of it. A target that exists but is not linked builds
#    nothing.
get_target_property(linked usermod INTERFACE_LINK_LIBRARIES)
if(NOT linked MATCHES "usermod_mpaudio")
    message(FATAL_ERROR
        "usermod_mpaudio is not linked into usermod (link libraries: ${linked})")
endif()
message(STATUS "audioif cmake check: usermod_mpaudio is linked into usermod")

# 3. The source list is real and every file in it is on disk. A path typo in
#    `micropython.cmake` is invisible until a port compiles, and this is the
#    cheap place to catch it.
get_target_property(sources usermod_mpaudio INTERFACE_SOURCES)
list(LENGTH sources source_count)
if(source_count LESS 50)
    message(FATAL_ERROR
        "usermod_mpaudio carries only ${source_count} sources, which cannot be right")
endif()
foreach(source ${sources})
    if(NOT EXISTS ${source})
        message(FATAL_ERROR "usermod_mpaudio names a source that does not exist: ${source}")
    endif()
endforeach()
message(STATUS "audioif cmake check: ${source_count} sources, all present")

# 4. The voice ceiling. Its own comment in `micropython.cmake` says "no gate
#    anywhere exercises this constant: nothing in .github/ or tools/ invokes
#    CMake" - so this prints it, and `scripts/check_voice_ceiling.py` holds
#    the header, the Make path and this one to the same number.
get_target_property(definitions usermod_mpaudio INTERFACE_COMPILE_DEFINITIONS)
set(ceiling "")
foreach(definition ${definitions})
    if(definition MATCHES "^CIRCUITPY_SYNTHIO_MAX_CHANNELS=(.+)$")
        set(ceiling ${CMAKE_MATCH_1})
    endif()
endforeach()
if(ceiling STREQUAL "")
    message(FATAL_ERROR
        "the CMake path defines no CIRCUITPY_SYNTHIO_MAX_CHANNELS")
endif()
message(STATUS "audioif cmake check: CIRCUITPY_SYNTHIO_MAX_CHANNELS=${ceiling}")
