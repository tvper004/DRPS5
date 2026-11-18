/* platform/bluetooth.h - Bluetooth controller pairing and discovery via Luna on webOS. */
#ifndef DRPS5_BLUETOOTH_H
#define DRPS5_BLUETOOTH_H

#include <stdbool.h>

typedef struct {
    char name[128];
    char address[32];
    bool paired;
    bool connected;
    bool is_gamepad;
} bt_device_t;

void bluetooth_init(void);
bool bluetooth_start_discovery(void);
bool bluetooth_cancel_discovery(void);
int bluetooth_get_devices(bt_device_t *out_devices, int max_devices);
bool bluetooth_pair_device(const char *address);
bool bluetooth_is_pairing(void);
bool bluetooth_connect_hid(const char *address);
bool bluetooth_is_connecting(void);
bool bluetooth_disconnect_hid(const char *address);
bool bluetooth_unpair_device(const char *address);
void bluetooth_auto_reconnect(void);
void bluetooth_prune_stale_gamepads(const char *keep_address);
bool bluetooth_open_system_settings(void);

#endif
