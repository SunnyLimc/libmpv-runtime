/*
 * Dynamically loads libmpv, decodes a deterministic WAV through one audio
 * filter, and writes the post-filter PCM to another WAV. No import library is
 * required, so the same source works for packaged Windows, Linux, macOS, and
 * Android runtimes.
 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Minimal stable client ABI declarations keep the probe independent of a
 * particular upstream header package. Every function is still resolved from
 * the candidate runtime at execution time. */
#include <stdint.h>
typedef struct mpv_handle mpv_handle;
typedef struct mpv_event {
    int event_id;
    int error;
    uint64_t reply_userdata;
    void *data;
} mpv_event;
typedef struct mpv_event_end_file {
    int reason;
    int error;
    int64_t playlist_entry_id;
    int64_t playlist_insert_id;
    int playlist_insert_num_entries;
} mpv_event_end_file;
enum {
    MPV_EVENT_NONE = 0,
    MPV_EVENT_SHUTDOWN = 1,
    MPV_EVENT_END_FILE = 7,
    MPV_EVENT_FILE_LOADED = 8
};

#if defined(_WIN32)
#include <windows.h>
typedef HMODULE library_handle;
static library_handle open_library(const char *path) {
    return LoadLibraryExA(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
}
static void *load_symbol(library_handle library, const char *name) {
    return (void *)GetProcAddress(library, name);
}
static const char *library_error(void) {
    static char message[64];
    snprintf(message, sizeof(message), "Win32 error %lu", (unsigned long)GetLastError());
    return message;
}
static void close_library(library_handle library) {
    FreeLibrary(library);
}
#else
#include <dlfcn.h>
typedef void *library_handle;
static library_handle open_library(const char *path) {
    return dlopen(path, RTLD_NOW | RTLD_LOCAL);
}
static void *load_symbol(library_handle library, const char *name) {
    return dlsym(library, name);
}
static const char *library_error(void) {
    const char *message = dlerror();
    return message ? message : "unknown dlopen error";
}
static void close_library(library_handle library) {
    dlclose(library);
}
#endif

typedef unsigned long (*client_api_version_fn)(void);
typedef mpv_handle *(*create_fn)(void);
typedef int (*initialize_fn)(mpv_handle *);
typedef int (*set_option_string_fn)(mpv_handle *, const char *, const char *);
typedef int (*set_property_string_fn)(mpv_handle *, const char *, const char *);
typedef int (*command_fn)(mpv_handle *, const char *const *);
typedef mpv_event *(*wait_event_fn)(mpv_handle *, double);
typedef char *(*get_property_string_fn)(mpv_handle *, const char *);
typedef void (*mpv_free_fn)(void *);
typedef void (*terminate_destroy_fn)(mpv_handle *);
typedef const char *(*error_string_fn)(int);

struct api {
    client_api_version_fn client_api_version;
    create_fn create;
    initialize_fn initialize;
    set_option_string_fn set_option_string;
    set_property_string_fn set_property_string;
    command_fn command;
    wait_event_fn wait_event;
    get_property_string_fn get_property_string;
    mpv_free_fn free;
    terminate_destroy_fn terminate_destroy;
    error_string_fn error_string;
};

static int bind_api(library_handle library, struct api *api) {
#define LOAD(field, type, symbol)                                                        \
    do {                                                                                 \
        api->field = (type)load_symbol(library, symbol);                                  \
        if (!api->field) {                                                               \
            fprintf(stderr, "missing required symbol %s: %s\n", symbol, library_error()); \
            return 0;                                                                    \
        }                                                                                \
    } while (0)
    LOAD(client_api_version, client_api_version_fn, "mpv_client_api_version");
    LOAD(create, create_fn, "mpv_create");
    LOAD(initialize, initialize_fn, "mpv_initialize");
    LOAD(set_option_string, set_option_string_fn, "mpv_set_option_string");
    LOAD(set_property_string, set_property_string_fn, "mpv_set_property_string");
    LOAD(command, command_fn, "mpv_command");
    LOAD(wait_event, wait_event_fn, "mpv_wait_event");
    LOAD(get_property_string, get_property_string_fn, "mpv_get_property_string");
    LOAD(free, mpv_free_fn, "mpv_free");
    LOAD(terminate_destroy, terminate_destroy_fn, "mpv_terminate_destroy");
    LOAD(error_string, error_string_fn, "mpv_error_string");
#undef LOAD
    return 1;
}

static int set_option(struct api *api, mpv_handle *handle, const char *name, const char *value) {
    int result = api->set_option_string(handle, name, value);
    if (result < 0) {
        fprintf(stderr, "cannot set %s=%s: %s\n", name, value, api->error_string(result));
        return 0;
    }
    return 1;
}

static void print_property(struct api *api, mpv_handle *handle, const char *name) {
    char *value = api->get_property_string(handle, name);
    if (value) {
        printf("%s=%s\n", name, value);
        api->free(value);
    }
}

int main(int argc, char **argv) {
    if (argc != 5 && argc != 6) {
        fprintf(stderr, "usage: %s LIBMPV INPUT OUTPUT.wav LAVFI_FILTER [after-load]\n", argv[0]);
        return 64;
    }
    const char *library_path = argv[1];
    const char *input_path = argv[2];
    const char *output_path = argv[3];
    const char *filter = argv[4];
    int after_load = argc == 6 && strcmp(argv[5], "after-load") == 0;
    if (argc == 6 && !after_load) {
        fprintf(stderr, "unsupported filter timing: %s\n", argv[5]);
        return 64;
    }

    library_handle library = open_library(library_path);
    if (!library) {
        fprintf(stderr, "cannot load %s: %s\n", library_path, library_error());
        return 65;
    }

    struct api api = {0};
    if (!bind_api(library, &api)) {
        close_library(library);
        return 66;
    }
    unsigned long api_version = api.client_api_version();
    printf("client-api=%lu.%lu\n", api_version >> 16, api_version & 0xffffUL);

    mpv_handle *handle = api.create();
    if (!handle) {
        fprintf(stderr, "mpv_create failed\n");
        close_library(library);
        return 67;
    }

    char audio_filter[1024];
    if (snprintf(audio_filter, sizeof(audio_filter), "lavfi=[%s]", filter) >=
        (int)sizeof(audio_filter)) {
        fprintf(stderr, "filter expression is too long\n");
        api.terminate_destroy(handle);
        close_library(library);
        return 68;
    }

    int options_ok =
        set_option(&api, handle, "terminal", "yes") &&
        set_option(&api, handle, "msg-level", "all=warn") &&
        set_option(&api, handle, "video", "no") &&
        set_option(&api, handle, "audio-display", "no") &&
        set_option(&api, handle, "ao", "pcm") &&
        set_option(&api, handle, "ao-pcm-file", output_path) &&
        set_option(&api, handle, "ao-pcm-waveheader", "yes") &&
        set_option(&api, handle, "audio-format", "s16") &&
        set_option(&api, handle, "audio-channels", "stereo") &&
        set_option(&api, handle, "audio-samplerate", "48000") &&
        (!after_load || set_option(&api, handle, "pause", "yes")) &&
        (after_load || set_option(&api, handle, "af", audio_filter));
    if (!options_ok) {
        api.terminate_destroy(handle);
        close_library(library);
        return 69;
    }

    int result = api.initialize(handle);
    if (result < 0) {
        fprintf(stderr, "mpv_initialize failed: %s\n", api.error_string(result));
        api.terminate_destroy(handle);
        close_library(library);
        return 70;
    }
    print_property(&api, handle, "mpv-version");
    print_property(&api, handle, "ffmpeg-version");

    const char *command[] = {"loadfile", input_path, "replace", NULL};
    result = api.command(handle, command);
    if (result < 0) {
        fprintf(stderr, "loadfile failed: %s\n", api.error_string(result));
        api.terminate_destroy(handle);
        close_library(library);
        return 71;
    }

    int exit_code = 72;
    int filter_applied = !after_load;
    for (;;) {
        mpv_event *event = api.wait_event(handle, 30.0);
        if (!event) {
            fprintf(stderr, "mpv_wait_event returned null\n");
            break;
        }
        if (event->event_id == MPV_EVENT_FILE_LOADED && after_load && !filter_applied) {
            result = api.set_property_string(handle, "af", audio_filter);
            if (result < 0) {
                fprintf(stderr, "cannot set af after load: %s\n", api.error_string(result));
                break;
            }
            result = api.set_property_string(handle, "pause", "no");
            if (result < 0) {
                fprintf(stderr, "cannot resume after filter insertion: %s\n", api.error_string(result));
                break;
            }
            filter_applied = 1;
        } else if (event->event_id == MPV_EVENT_END_FILE) {
            mpv_event_end_file *end = (mpv_event_end_file *)event->data;
            if (!filter_applied) {
                fprintf(stderr, "playback ended before filter insertion\n");
            } else if (end && end->error < 0) {
                fprintf(stderr, "playback failed: %s\n", api.error_string(end->error));
            } else {
                exit_code = 0;
            }
            break;
        }
        if (event->event_id == MPV_EVENT_SHUTDOWN) {
            fprintf(stderr, "unexpected shutdown\n");
            break;
        }
        if (event->event_id == MPV_EVENT_NONE) {
            fprintf(stderr, "timed out waiting for decoded output\n");
            break;
        }
    }

    api.terminate_destroy(handle);
    close_library(library);
    if (exit_code == 0) {
        FILE *output = fopen(output_path, "rb");
        if (!output) {
            fprintf(stderr, "output was not created: %s\n", strerror(errno));
            return 73;
        }
        if (fseek(output, 0, SEEK_END) != 0 || ftell(output) <= 44) {
            fprintf(stderr, "output WAV is empty\n");
            exit_code = 74;
        }
        fclose(output);
    }
    return exit_code;
}
