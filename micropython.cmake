# MicroPython CMake glue for audiopump (esp32).
# For Make-based ports (unix, windows), see micropython.mk in this dir.
#
# audiopump compiles against audioif's headers but declares no dependency on
# its build: the symbols it calls (`audioif_sample_get`, and the protocol
# struct's own function pointers) come from audioif's objects in the same
# firmware. AUDIOIF_DIR points at the audioif checkout; the default assumes
# the usual workspace layout (audiopump and audioif as siblings, or both
# symlinked into cmods).

set(AUDIOPUMP_MOD_DIR ${CMAKE_CURRENT_LIST_DIR})

if(NOT DEFINED AUDIOPUMP_AUDIOIF_DIR)
    if(EXISTS ${AUDIOPUMP_MOD_DIR}/../audioif/src/shared/audioif_sample.h)
        set(AUDIOPUMP_AUDIOIF_DIR ${AUDIOPUMP_MOD_DIR}/../audioif)
    elseif(DEFINED CMOD_DIR AND EXISTS ${CMOD_DIR}/audioif/src/shared/audioif_sample.h)
        set(AUDIOPUMP_AUDIOIF_DIR ${CMOD_DIR}/audioif)
    endif()
endif()

if(NOT DEFINED AUDIOPUMP_AUDIOIF_DIR)
    message(STATUS "audiopump: skipped -- audioif not found beside it")
    return()
endif()

add_library(usermod_audiopump INTERFACE)

target_sources(usermod_audiopump INTERFACE
    ${AUDIOPUMP_MOD_DIR}/audiopump.c
)

target_include_directories(usermod_audiopump INTERFACE
    ${AUDIOPUMP_AUDIOIF_DIR}/src
)

# The IDF does NOT hand ESP_PLATFORM to user C modules -- it is a CMake
# variable here and a compile definition only inside IDF components. Without
# this the source compiles its POSIX branch instead, and it links, because
# ESP-IDF's newlib has pthread.h: you get an unpinned pump on a default
# pthread stack and no I2S sink, with nothing failing to say so. displayif
# hits the same thing (src/ports/esp32/micropython.cmake:24).
target_compile_definitions(usermod_audiopump INTERFACE AUDIOPUMP_ESP32=1)

target_link_libraries(usermod INTERFACE usermod_audiopump)
