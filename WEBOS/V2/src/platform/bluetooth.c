/* platform/bluetooth.c - Bluetooth controller pairing and discovery via Luna on webOS. */
#define _GNU_SOURCE
#include "bluetooth.h"

#include <SDL.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#include "../log.h"

#ifdef DRPS5_HAVE_LIBCHIAKI
#include <json-c/json.h>
#endif

void bluetooth_init(void) {
    log_msg("bluetooth: initialized");
}

static char *luna_call(const char *url, const char *payload) {
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "luna-send-pub -n 1 -w 2000 -f %s '%s' 2>/dev/null", url, payload ? payload : "{}");
    FILE *fp = popen(cmd, "r");
    if (!fp) {
        log_msg("bluetooth: failed to run popen for %s", url);
        return NULL;
    }
    size_t cap = 32768;
    char *buf = malloc(cap);
    if (!buf) {
        pclose(fp);
        return NULL;
    }
    size_t len = fread(buf, 1, cap - 1, fp);
    buf[len] = '\0';
    pclose(fp);
    return buf;
}

bool bluetooth_start_discovery(void) {
    log_msg("bluetooth: starting discovery...");
    char *res = luna_call("luna://com.webos.service.bluetooth2/adapter/startDiscovery", "{}");
    bool ok = res && strstr(res, "\"returnValue\":true") != NULL;
    if (!ok && res && strstr(res, "\"returnValue\": true")) ok = true;
    log_msg("bluetooth: startDiscovery result: %s", res ? res : "NULL");
    free(res);
    return ok;
}

bool bluetooth_cancel_discovery(void) {
    log_msg("bluetooth: cancelling discovery");
    char *res = luna_call("luna://com.webos.service.bluetooth2/adapter/cancelDiscovery", "{}");
    bool ok = res && (strstr(res, "\"returnValue\":true") != NULL || strstr(res, "\"returnValue\": true") != NULL);
    free(res);
    return ok;
}

static bool is_tv_remote_name(const char *name) {
    if (!name || !*name) return true;
    if (strncmp(name, "LGE", 3) == 0 || strncmp(name, "LG ", 3) == 0) return true;
    if (strstr(name, "WEE") || strstr(name, "MR20") || strstr(name, "Remote") || strstr(name, "remote")) return true;
    if (strstr(name, "RCU") || strstr(name, "rcu") || strstr(name, "keypad") || strstr(name, "Keypad")) return true;
    if (strstr(name, "CHECK INPUT") || strstr(name, "Network Input") || strstr(name, "Bluetooth-audio") || strstr(name, "Builtin")) return true;
    return false;
}

static bool check_is_gamepad(const char *name, int cod) {
    if (!name || is_tv_remote_name(name)) return false;
    /* Class of Device: Peripheral / Gamepad / Joystick */
    if (cod == 1288 || cod == 2428168) return true;
    if ((cod & 0x1f00) == 0x0500) {
        /* Minor device class for Joystick / Gamepad */
        int minor = cod & 0x00fc;
        if (minor == 0x04 || minor == 0x08) return true;
    }
    /* Name matching case-insensitive */
    if (strcasestr(name, "Wireless Controller")) return true;
    if (strcasestr(name, "DualSense")) return true;
    if (strcasestr(name, "DualShock")) return true;
    if (strcasestr(name, "Xbox")) return true;
    if (strcasestr(name, "Gamepad")) return true;
    if (strcasestr(name, "Joy-Con")) return true;
    if (strcasestr(name, "Pro Controller")) return true;
    if (strcasestr(name, "Controller")) return true;
    return false;
}

int bluetooth_get_devices(bt_device_t *out_devices, int max_devices) {
    if (!out_devices || max_devices <= 0) return 0;
    char *res = luna_call("luna://com.webos.service.bluetooth2/device/getStatus", "{}");
    if (!res) return 0;

    int count = 0;
#ifdef DRPS5_HAVE_LIBCHIAKI
    json_object *root = json_tokener_parse(res);
    if (root) {
        json_object *devs_obj = NULL;
        if (json_object_object_get_ex(root, "devices", &devs_obj) && json_object_is_type(devs_obj, json_type_array)) {
            int len = (int)json_object_array_length(devs_obj);
            for (int i = 0; i < len && count < max_devices; i++) {
                json_object *item = json_object_array_get_idx(devs_obj, i);
                if (!item) continue;

                json_object *v_name = NULL, *v_addr = NULL, *v_paired = NULL, *v_cod = NULL, *v_conn = NULL;
                json_object_object_get_ex(item, "name", &v_name);
                json_object_object_get_ex(item, "address", &v_addr);
                json_object_object_get_ex(item, "paired", &v_paired);
                json_object_object_get_ex(item, "classOfDevice", &v_cod);
                json_object_object_get_ex(item, "connectedProfiles", &v_conn);

                const char *name = v_name ? json_object_get_string(v_name) : "";
                const char *addr = v_addr ? json_object_get_string(v_addr) : "";
                bool paired = v_paired ? json_object_get_boolean(v_paired) : false;
                int cod = v_cod ? json_object_get_int(v_cod) : 0;
                bool connected = false;
                if (v_conn && json_object_is_type(v_conn, json_type_array)) {
                    connected = json_object_array_length(v_conn) > 0;
                }

                bt_device_t *d = &out_devices[count];
                snprintf(d->name, sizeof(d->name), "%s", name);
                snprintf(d->address, sizeof(d->address), "%s", addr);
                d->paired = paired;
                d->connected = connected;
                d->is_gamepad = check_is_gamepad(name, cod);

                count++;
            }
        }
        json_object_put(root);
    }
#endif
    free(res);
    return count;
}

struct pair_arg {
    char address[32];
};

static SDL_atomic_t g_pairing;
static SDL_atomic_t g_connecting;

static int pair_worker(void *data) {
    struct pair_arg *arg = (struct pair_arg *)data;
    if (!arg) {
        SDL_AtomicSet(&g_pairing, 0);
        return 0;
    }
    char addr[32];
    snprintf(addr, sizeof(addr), "%s", arg->address);
    free(arg);

    log_msg("bluetooth: interactive pair_worker started for %s", addr);
    int output[2], input[2];
    bool ended = false;
    if (pipe(output) == 0) {
        if (pipe(input) == 0) {
            pid_t pid = fork();
            if (pid == 0) {
                dup2(input[0], STDIN_FILENO);
                dup2(output[1], STDOUT_FILENO);
                close(input[0]); close(input[1]); close(output[0]); close(output[1]);
                char payload[128];
                snprintf(payload, sizeof(payload), "{\"subscribe\":true,\"address\":\"%s\"}", addr);
                execlp("luna-send-pub", "luna-send-pub", "-i", "-f",
                       "luna://com.webos.service.bluetooth2/adapter/pair", payload, (char *)NULL);
                _exit(127);
            }
            close(input[0]); close(output[1]);
            if (pid > 0) {
                uint32_t started = SDL_GetTicks();
                char line[1024]; size_t used = 0;
                while (SDL_GetTicks() - started < 25000 && !ended) {
                    struct pollfd fd = { .fd = output[0], .events = POLLIN };
                    int ready = poll(&fd, 1, 250);
                    if (ready < 0 && errno == EINTR) continue;
                    if (ready < 0 || (ready > 0 && !(fd.revents & POLLIN))) break;
                    if (!ready) continue;
                    char ch;
                    if (read(output[0], &ch, 1) != 1) break;
                    if (used < sizeof(line) - 1) line[used++] = ch;
                    if (ch != '\n' && used < sizeof(line) - 1) continue;
                    line[used] = 0;
                    log_msg("bluetooth: pair event: %s", line);
                    if (strstr(line, "confirmPasskey")) {
                        char payload[128];
                        snprintf(payload, sizeof(payload), "{\"address\":\"%s\",\"accept\":true}", addr);
                        char *reply = luna_call("luna://com.webos.service.bluetooth2/adapter/supplyPasskeyConfirmation", payload);
                        log_msg("bluetooth: passkey confirmation: %s", reply ? reply : "no response");
                        free(reply);
                    }
                    if (strstr(line, "enterPinCode")) {
                        log_msg("bluetooth: pairing requires a PIN; no PIN supplied automatically");
                    }
                    if (strstr(line, "endPairing")) ended = true;
                    used = 0;
                }
                close(input[1]); close(output[0]);
                kill(pid, SIGTERM);
                while (waitpid(pid, NULL, 0) < 0 && errno == EINTR) {}
            } else {
                log_msg("bluetooth: cannot start pairing process");
                close(input[1]); close(output[0]);
            }
        } else {
            close(output[0]); close(output[1]);
        }
    }
    log_msg("bluetooth: pairing subscription ended=%d for %s", ended, addr);

    SDL_Delay(600);

    /* Verify if device was successfully paired */
    bt_device_t devs[32];
    int n = bluetooth_get_devices(devs, 32);
    bool paired = false;
    for (int i = 0; i < n; i++) {
        if (strcasecmp(devs[i].address, addr) == 0 && devs[i].paired) {
            paired = true;
            break;
        }
    }

    if (paired) {
        log_msg("bluetooth: device %s successfully paired and verified! Connecting HID...", addr);
        bluetooth_connect_hid(addr);
    } else {
        log_msg("bluetooth: device %s pairing did not complete successfully", addr);
    }

    SDL_AtomicSet(&g_pairing, 0);
    return 0;
}

bool bluetooth_pair_device(const char *address) {
    if (!address || !*address) return false;
    if (SDL_AtomicGet(&g_pairing)) {
        log_msg("bluetooth: pair already in progress, skipping %s", address);
        return false;
    }
    SDL_AtomicSet(&g_pairing, 1);
    log_msg("bluetooth: initiating background interactive pairing for %s", address);
    struct pair_arg *arg = malloc(sizeof(struct pair_arg));
    if (!arg) {
        SDL_AtomicSet(&g_pairing, 0);
        return false;
    }
    snprintf(arg->address, sizeof(arg->address), "%s", address);
    SDL_Thread *t = SDL_CreateThread(pair_worker, "bt_pair", arg);
    if (t) {
        SDL_DetachThread(t);
        return true;
    }
    free(arg);
    SDL_AtomicSet(&g_pairing, 0);
    return false;
}

bool bluetooth_is_pairing(void) {
    return SDL_AtomicGet(&g_pairing) != 0;
}

bool bluetooth_is_connecting(void) {
    return SDL_AtomicGet(&g_connecting) != 0;
}

struct connect_arg {
    char address[32];
};

static int connect_worker(void *data) {
    struct connect_arg *arg = (struct connect_arg *)data;
    if (!arg) {
        SDL_AtomicSet(&g_connecting, 0);
        return 0;
    }
    char payload[128];
    snprintf(payload, sizeof(payload), "{\"address\":\"%s\"}", arg->address);
    log_msg("bluetooth: checking HID state for %s", arg->address);
    bool requested = false;
    for (int attempt = 0; attempt < 15; attempt++) {
        char *status = luna_call("luna://com.webos.service.bluetooth2/hid/getStatus", payload);
        bool connected = false, connecting = false, known = false;
#ifdef DRPS5_HAVE_LIBCHIAKI
        json_object *obj = status ? json_tokener_parse(status) : NULL;
        if (obj) {
            json_object *value = NULL;
            if (json_object_object_get_ex(obj, "connected", &value)) {
                connected = json_object_get_boolean(value);
                known = true;
            }
            if (json_object_object_get_ex(obj, "connecting", &value)) connecting = json_object_get_boolean(value);
            json_object_put(obj);
        }
#endif
        log_msg("bluetooth: hid/status %s", status ? status : "no response");
        free(status);
        if (connected) break;
        if (known && !connecting && !requested) {
            char *reply = luna_call("luna://com.webos.service.bluetooth2/hid/connect", payload);
            log_msg("bluetooth: hid/connect %s", reply ? reply : "no response");
            free(reply);
            requested = true;
        }
        SDL_Delay(1000);
    }
    log_msg("bluetooth: HID wait finished for %s; input device must still be verified", arg->address);

    free(arg);
    SDL_Delay(600);
    SDL_AtomicSet(&g_connecting, 0);
    return 0;
}

bool bluetooth_connect_hid(const char *address) {
    if (!address || !*address) return false;
    if (SDL_AtomicGet(&g_connecting)) {
        log_msg("bluetooth: connect already in progress, skipping %s", address);
        return false;
    }
    SDL_AtomicSet(&g_connecting, 1);
    log_msg("bluetooth: initiating background hid/connect for %s", address);
    struct connect_arg *arg = malloc(sizeof(struct connect_arg));
    if (!arg) {
        SDL_AtomicSet(&g_connecting, 0);
        return false;
    }
    snprintf(arg->address, sizeof(arg->address), "%s", address);
    SDL_Thread *t = SDL_CreateThread(connect_worker, "bt_conn", arg);
    if (t) {
        SDL_DetachThread(t);
        return true;
    }
    free(arg);
    SDL_AtomicSet(&g_connecting, 0);
    return false;
}

bool bluetooth_disconnect_hid(const char *address) {
    if (!address || !*address) return false;
    log_msg("bluetooth: disconnecting hid %s", address);
    char payload[128];
    snprintf(payload, sizeof(payload), "{\"address\":\"%s\"}", address);
    char *res = luna_call("luna://com.webos.service.bluetooth2/hid/disconnect", payload);
    bool ok = res && (strstr(res, "\"returnValue\":true") != NULL || strstr(res, "\"returnValue\": true") != NULL);
    log_msg("bluetooth: hid/disconnect result: %s", res ? res : "NULL");
    free(res);
    return ok;
}

bool bluetooth_unpair_device(const char *address) {
    if (!address || !*address) return false;
    log_msg("bluetooth: unpairing device %s", address);
    bluetooth_disconnect_hid(address);
    char payload[128];
    snprintf(payload, sizeof(payload), "{\"address\":\"%s\"}", address);
    char *res = luna_call("luna://com.webos.service.bluetooth2/adapter/unpair", payload);
    bool ok = res && (strstr(res, "\"returnValue\":true") != NULL || strstr(res, "\"returnValue\": true") != NULL);
    log_msg("bluetooth: unpair result: %s", res ? res : "NULL");
    free(res);
    return ok;
}

void bluetooth_auto_reconnect(void) {
    if (SDL_AtomicGet(&g_connecting) || SDL_AtomicGet(&g_pairing)) return;
    bt_device_t devs[32];
    int n = bluetooth_get_devices(devs, 32);
    for (int i = 0; i < n; i++) {
        if (devs[i].is_gamepad && devs[i].paired && !devs[i].connected) {
            log_msg("bluetooth: auto-reconnecting paired gamepad %s (%s)", devs[i].name, devs[i].address);
            bluetooth_connect_hid(devs[i].address);
            break;
        }
    }
}

struct prune_arg {
    char keep_address[32];
};

static SDL_atomic_t g_pruning;

static int prune_worker(void *data) {
    struct prune_arg *arg = (struct prune_arg *)data;
    char keep[32] = { 0 };
    if (arg) {
        snprintf(keep, sizeof(keep), "%s", arg->keep_address);
        free(arg);
    }

    bt_device_t devs[32];
    int n = bluetooth_get_devices(devs, 32);

    /* If keep was not specified, see if there is an active connected gamepad */
    if (!keep[0]) {
        for (int i = 0; i < n; i++) {
            if (devs[i].is_gamepad && devs[i].connected && devs[i].paired) {
                snprintf(keep, sizeof(keep), "%s", devs[i].address);
                break;
            }
        }
    }

    /* If still no keep, and there are multiple paired gamepads, keep the last one (most recent) */
    if (!keep[0]) {
        for (int i = n - 1; i >= 0; i--) {
            if (devs[i].is_gamepad && devs[i].paired) {
                snprintf(keep, sizeof(keep), "%s", devs[i].address);
                break;
            }
        }
    }

    /* If we have a gamepad to keep, unpair all OTHER paired gamepads */
    if (keep[0]) {
        log_msg("bluetooth: pruning stale gamepads, keeping active %s", keep);
        for (int i = 0; i < n; i++) {
            if (devs[i].is_gamepad && devs[i].paired && strcasecmp(devs[i].address, keep) != 0) {
                log_msg("bluetooth: removing stale paired gamepad %s (%s)", devs[i].name, devs[i].address);
                bluetooth_unpair_device(devs[i].address);
            }
        }
    }

    SDL_AtomicSet(&g_pruning, 0);
    return 0;
}

void bluetooth_prune_stale_gamepads(const char *keep_address) {
    if (SDL_AtomicGet(&g_pruning)) return;
    SDL_AtomicSet(&g_pruning, 1);
    struct prune_arg *arg = calloc(1, sizeof(struct prune_arg));
    if (arg && keep_address) snprintf(arg->keep_address, sizeof(arg->keep_address), "%s", keep_address);
    SDL_Thread *t = SDL_CreateThread(prune_worker, "bt_prune", arg);
    if (t) {
        SDL_DetachThread(t);
    } else {
        free(arg);
        SDL_AtomicSet(&g_pruning, 0);
    }
}

bool bluetooth_open_system_settings(void) {
    log_msg("bluetooth: launching system settings");
    char *res = luna_call("luna://com.webos.applicationManager/launch",
                          "{\"id\": \"com.palm.app.settings\", \"params\": {\"target\": \"bluetooth\"}}");
    bool ok = res && (strstr(res, "\"returnValue\":true") != NULL || strstr(res, "\"returnValue\": true") != NULL);
    free(res);
    return ok;
}
