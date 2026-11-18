/* ui/pair_pad.h - Bluetooth controller pairing modal dialog. */
#ifndef DRPS5_PAIR_PAD_H
#define DRPS5_PAIR_PAD_H

#include <stdbool.h>
#include <stdint.h>
#include <lvgl.h>

void ui_pair_pad_open(void);
void ui_pair_pad_close(void);
bool ui_pair_pad_active(void);
void ui_pair_pad_key(uint32_t key);

#endif
