/* ui/unpair_pad.h - Bluetooth controller/device unpairing modal dialog. */
#ifndef DRPS5_UNPAIR_PAD_H
#define DRPS5_UNPAIR_PAD_H

#include <stdbool.h>
#include <stdint.h>

void ui_unpair_pad_open(void);
void ui_unpair_pad_close(void);
bool ui_unpair_pad_active(void);
void ui_unpair_pad_key(uint32_t key);

#endif
