/* ui/unpair_pad.c - Bluetooth controller/device unpairing modal dialog. */
#include "unpair_pad.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../input/input.h"
#include "../log.h"
#include "../platform/bluetooth.h"
#include "art.h"
#include "controls.h"
#include "home_internal.h"
#include "motion.h"
#include "language.h"
#include "theme.h"

#define UNPAIR_W       1080
#define UNPAIR_H       640
#define MAX_ITEMS      16
#define BOTTOM_BTNS    4

enum {
    BTN_PRUNE = 0,
    BTN_REFRESH,
    BTN_TV,
    BTN_CLOSE
};

typedef struct {
    char name[128];
    char address[32];
    bool connected;
    bool is_gamepad;
    lv_obj_t *box;
    lv_obj_t *btn_unpair;
} dev_item_t;

static struct {
    lv_obj_t *root;
    lv_obj_t *scrim;
    lv_obj_t *card;
    lv_obj_t *list;
    lv_obj_t *lbl_status;
    lv_obj_t *empty_box;
    lv_obj_t *btn_bottom[BOTTOM_BTNS];
    dev_item_t items[MAX_ITEMS];
    int item_count;
    int focus; /* 0..item_count-1: dev items; item_count..item_count+2: bottom buttons */
} U;

static void update_focus(void);
static void refresh_list(void);

static lv_obj_t *make_btn(lv_obj_t *parent, lv_coord_t w, lv_coord_t h, const char *icon, const char *text) {
    lv_obj_t *b = ctl_pill(parent, w, h);
    lv_obj_t *row = ctl_row(b, 8);
    if (icon) {
        lv_obj_t *i = lv_label_create(row);
        lv_label_set_text(i, icon);
        lv_obj_set_style_text_font(i, FONT_CAPTION, 0);
    }
    lv_obj_t *t = lv_label_create(row);
    lv_label_set_text(t, ui_translate(text));
    lv_obj_set_style_text_font(t, FONT_CAPTION, 0);
    lv_obj_center(row);
    return b;
}

static void on_unpair_clicked(lv_event_t *e) {
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    if (idx < 0 || idx >= U.item_count) return;

    char addr[32], name[128];
    snprintf(addr, sizeof(addr), "%s", U.items[idx].address);
    snprintf(name, sizeof(name), "%s", U.items[idx].name[0] ? U.items[idx].name : "Dispositivo");

    log_event(LOG_INFO, "BT", "Desvinculando dispositivo: %s (%s)", name, addr);
    bluetooth_unpair_device(addr);

    lv_label_set_text_fmt(U.lbl_status, "Dispositivo retirado: %s", name);
    lv_obj_set_style_text_color(U.lbl_status, C(COL_OK), 0);

    refresh_list();
    home_settings_refresh();
}

static void on_prune_timer_cb(lv_timer_t *t) {
    (void)t;
    refresh_list();
    home_settings_refresh();
    lv_label_set_text(U.lbl_status, "Mandos antiguos retirados. Solo persiste el mas reciente.");
    lv_obj_set_style_text_color(U.lbl_status, C(COL_OK), 0);
}

static void on_bottom_btn_clicked(lv_event_t *e) {
    int id = (int)(intptr_t)lv_event_get_user_data(e);
    if (id == BTN_PRUNE) {
        bluetooth_prune_stale_gamepads(NULL);
        lv_label_set_text(U.lbl_status, "Borrando mandos anteriores... un momento.");
        lv_obj_set_style_text_color(U.lbl_status, C(COL_ACCENT_HI), 0);
        lv_timer_t *tmr = lv_timer_create(on_prune_timer_cb, 800, NULL);
        lv_timer_set_repeat_count(tmr, 1);
    } else if (id == BTN_REFRESH) {
        refresh_list();
        lv_label_set_text(U.lbl_status, "Lista de dispositivos actualizada.");
        lv_obj_set_style_text_color(U.lbl_status, C(COL_ACCENT_HI), 0);
    } else if (id == BTN_TV) {
        bluetooth_open_system_settings();
        lv_label_set_text(U.lbl_status, "Se abrieron los Ajustes de Bluetooth de la TV.");
        lv_obj_set_style_text_color(U.lbl_status, C(COL_ACCENT_HI), 0);
    } else if (id == BTN_CLOSE) {
        ui_unpair_pad_close();
    }
}

static void on_item_row_clicked(lv_event_t *e) {
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    U.focus = idx;
    update_focus();
    on_unpair_clicked(e);
}

static void update_focus(void) {
    if (!U.root) return;
    int total = U.item_count + BOTTOM_BTNS;
    if (U.focus < 0) U.focus = 0;
    if (U.focus >= total) U.focus = total - 1;

    for (int i = 0; i < U.item_count; i++) {
        bool on = (U.focus == i);
        lv_obj_set_style_border_color(U.items[i].box, C(on ? COL_ACCENT_HI : COL_FROST), 0);
        lv_obj_set_style_border_width(U.items[i].box, on ? 3 : 1, 0);
        lv_obj_set_style_border_opa(U.items[i].box, on ? LV_OPA_COVER : LV_OPA_20, 0);
        if (U.items[i].btn_unpair) {
            ctl_button_danger_focus(U.items[i].btn_unpair, on);
        }
    }

    for (int i = 0; i < BOTTOM_BTNS; i++) {
        bool on = (U.focus == U.item_count + i);
        if (U.btn_bottom[i]) ctl_button_focus(U.btn_bottom[i], on);
    }
}

static void refresh_list(void) {
    if (!U.list) return;
    lv_obj_clean(U.list);
    memset(U.items, 0, sizeof(U.items));
    U.item_count = 0;

    bt_device_t raw[32];
    int raw_n = bluetooth_get_devices(raw, 32);

    /* First pass: paired gamepads */
    for (int i = 0; i < raw_n && U.item_count < MAX_ITEMS; i++) {
        if (raw[i].paired && raw[i].is_gamepad) {
            dev_item_t *it = &U.items[U.item_count++];
            snprintf(it->name, sizeof(it->name), "%s", raw[i].name[0] ? raw[i].name : "Mando Bluetooth");
            snprintf(it->address, sizeof(it->address), "%s", raw[i].address);
            it->connected = raw[i].connected;
            it->is_gamepad = true;
        }
    }

    /* Second pass: other paired devices (skip internal TV remotes) */
    for (int i = 0; i < raw_n && U.item_count < MAX_ITEMS; i++) {
        if (raw[i].paired && !raw[i].is_gamepad) {
            if (strstr(raw[i].name, "WEE") || strstr(raw[i].name, "MR20") ||
                strstr(raw[i].name, "LGE") || strstr(raw[i].name, "Remote") ||
                strstr(raw[i].name, "RCU")) continue;
            dev_item_t *it = &U.items[U.item_count++];
            snprintf(it->name, sizeof(it->name), "%s", raw[i].name[0] ? raw[i].name : "Dispositivo Bluetooth");
            snprintf(it->address, sizeof(it->address), "%s", raw[i].address);
            it->connected = raw[i].connected;
            it->is_gamepad = false;
        }
    }

    if (U.item_count == 0) {
        lv_obj_clear_flag(U.empty_box, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(U.list, LV_OBJ_FLAG_HIDDEN);
        if (U.focus < U.item_count) U.focus = U.item_count + BTN_CLOSE;
        update_focus();
        return;
    }

    lv_obj_add_flag(U.empty_box, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(U.list, LV_OBJ_FLAG_HIDDEN);

    for (int i = 0; i < U.item_count; i++) {
        dev_item_t *it = &U.items[i];
        lv_obj_t *r = ctl_rect(U.list, 1000, 72, 18, COL_FROST, 18);
        it->box = r;
        lv_obj_set_style_border_width(r, 1, 0);
        lv_obj_set_style_border_color(r, lv_color_white(), 0);
        lv_obj_set_style_border_opa(r, LV_OPA_10, 0);
        lv_obj_add_flag(r, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(r, on_item_row_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)i);

        /* Icon */
        lv_obj_t *icon_box = ctl_rect(r, 48, 48, 12, COL_SHADE, 160);
        lv_obj_set_pos(icon_box, 14, 12);
        lv_obj_t *ic = lv_label_create(icon_box);
        lv_label_set_text(ic, it->is_gamepad ? LV_SYMBOL_PLAY : LV_SYMBOL_BLUETOOTH);
        lv_obj_set_style_text_font(ic, FONT_BODY, 0);
        lv_obj_set_style_text_color(ic, C(it->is_gamepad ? COL_ACCENT_HI : COL_MUTED), 0);
        lv_obj_center(ic);

        /* Text: Name */
        lv_obj_t *lbl_name = ctl_label(r, FONT_HEADING, COL_TEXT, it->name);
        lv_obj_set_width(lbl_name, 730);
        lv_label_set_long_mode(lbl_name, LV_LABEL_LONG_DOT);
        lv_obj_set_pos(lbl_name, 76, 12);

        /* Text: MAC + status */
        char sub[128];
        snprintf(sub, sizeof(sub), "%s   #%06x " BULLET " %s#", it->address,
                 (unsigned)(it->connected ? COL_OK : COL_MUTED),
                 it->connected ? "Conectado" : "Vinculado");
        lv_obj_t *lbl_sub = ctl_label(r, FONT_CAPTION, COL_SUBTLE, sub);
        lv_label_set_recolor(lbl_sub, true);
        lv_obj_set_pos(lbl_sub, 76, 42);

        /* Button: Desvincular */
        it->btn_unpair = ctl_pill(r, 160, 48);
        lv_obj_align(it->btn_unpair, LV_ALIGN_RIGHT_MID, -16, 0);
        lv_obj_t *btn_row = ctl_row(it->btn_unpair, 8);
        lv_obj_t *b_ic = lv_label_create(btn_row);
        lv_label_set_text(b_ic, LV_SYMBOL_TRASH);
        lv_obj_set_style_text_font(b_ic, FONT_BODY, 0);
        lv_obj_t *b_tx = lv_label_create(btn_row);
        lv_label_set_text(b_tx, ui_translate("Retirar"));
        lv_obj_set_style_text_font(b_tx, FONT_CAPTION, 0);
        lv_obj_center(btn_row);
        lv_obj_add_flag(it->btn_unpair, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(it->btn_unpair, on_unpair_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)i);
    }

    update_focus();
}

void ui_unpair_pad_open(void) {
    if (U.root) return;
    memset(&U, 0, sizeof(U));

    U.root = ctl_obj(lv_layer_top());
    lv_obj_set_size(U.root, LV_PCT(100), LV_PCT(100));

    U.scrim = ctl_rect(U.root, LV_PCT(100), LV_PCT(100), 0, COL_SHADE, LV_OPA_TRANSP);
    motion_to(U.scrim, MO_BG_OPA, 200, 260, 0, NULL);

    U.card = ctl_rect(U.root, UNPAIR_W, UNPAIR_H, 36, COL_SHEET, 252);
    lv_obj_set_style_border_width(U.card, 2, 0);
    lv_obj_set_style_border_color(U.card, lv_color_white(), 0);
    lv_obj_set_style_border_opa(U.card, LV_OPA_20, 0);
    lv_obj_set_style_shadow_width(U.card, 80, 0);
    lv_obj_set_style_shadow_opa(U.card, LV_OPA_60, 0);
    lv_obj_center(U.card);

    /* Header */
    lv_obj_t *ttl = ctl_label(U.card, FONT_TITLE, COL_TEXT, "Retirar dispositivos Bluetooth");
    lv_obj_set_pos(ttl, 40, 32);

    lv_obj_t *sub = ctl_label(U.card, FONT_BODY, COL_SUBTLE,
                              "Selecciona un mando para desvincularlo de la TV y liberar el slot de conexion.");
    lv_obj_set_pos(sub, 40, 78);

    /* Scrollable device list */
    U.list = ctl_obj(U.card);
    lv_obj_set_size(U.list, 1000, 370);
    lv_obj_set_pos(U.list, 40, 120);
    lv_obj_set_flex_flow(U.list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(U.list, 10, 0);
    lv_obj_set_scroll_dir(U.list, LV_DIR_VER);

    /* Empty state box */
    U.empty_box = ctl_rect(U.card, 1000, 370, 24, COL_FROST, 10);
    lv_obj_set_pos(U.empty_box, 40, 120);
    lv_obj_t *em_col = ctl_obj(U.empty_box);
    lv_obj_set_size(em_col, LV_PCT(100), LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(em_col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(em_col, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_center(em_col);
    lv_obj_t *em_ic = lv_label_create(em_col);
    lv_label_set_text(em_ic, LV_SYMBOL_OK);
    lv_obj_set_style_text_font(em_ic, FONT_HERO, 0);
    lv_obj_set_style_text_color(em_ic, C(COL_OK), 0);
    lv_obj_t *em_txt = ctl_label(em_col, FONT_HEADING, COL_TEXT, "No hay mandos Bluetooth vinculados en la TV");
    lv_obj_t *em_hint = ctl_label(em_col, FONT_CAPTION, COL_MUTED,
                                  "Todos los slots de mandos estan libres.");
    (void)em_txt;
    (void)em_hint;
    lv_obj_add_flag(U.empty_box, LV_OBJ_FLAG_HIDDEN);

    /* Bottom status message */
    U.lbl_status = ctl_label(U.card, FONT_CAPTION, COL_MUTED, "");
    lv_obj_set_pos(U.lbl_status, 40, 495);
    lv_obj_set_width(U.lbl_status, 1000);

    /* Bottom action buttons */
    lv_obj_t *btn_row = ctl_obj(U.card);
    lv_obj_set_size(btn_row, 1000, 56);
    lv_obj_align(btn_row, LV_ALIGN_BOTTOM_MID, 0, -32);

    U.btn_bottom[BTN_PRUNE] = make_btn(btn_row, 260, 56, LV_SYMBOL_TRASH, "Limpiar antiguos");
    lv_obj_set_pos(U.btn_bottom[BTN_PRUNE], 0, 0);

    U.btn_bottom[BTN_REFRESH] = make_btn(btn_row, 220, 56, LV_SYMBOL_REFRESH, "Actualizar");
    lv_obj_set_pos(U.btn_bottom[BTN_REFRESH], 275, 0);

    U.btn_bottom[BTN_TV] = make_btn(btn_row, 230, 56, LV_SYMBOL_SETTINGS, "Ajustes de TV");
    lv_obj_set_pos(U.btn_bottom[BTN_TV], 510, 0);

    U.btn_bottom[BTN_CLOSE] = make_btn(btn_row, 200, 56, LV_SYMBOL_CLOSE, "Cerrar");
    lv_obj_set_pos(U.btn_bottom[BTN_CLOSE], 755, 0);

    for (int i = 0; i < BOTTOM_BTNS; i++) {
        lv_obj_add_flag(U.btn_bottom[i], LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(U.btn_bottom[i], on_bottom_btn_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)i);
    }

    refresh_list();

    U.focus = U.item_count > 0 ? 0 : U.item_count + BTN_CLOSE;
    update_focus();

    motion_from(U.card, MO_GROW, -40, 0, 380, 0, motion_spring);
    motion_from(U.card, MO_OPA, 0, 255, 200, 0, NULL);
    log_event(LOG_INFO, "UI", "dialog: unpair controller opened");
}

void ui_unpair_pad_close(void) {
    if (!U.root) return;
    lv_obj_del(U.root);
    memset(&U, 0, sizeof(U));
    log_event(LOG_INFO, "UI", "dialog: unpair controller closed");
}

bool ui_unpair_pad_active(void) {
    return U.root != NULL;
}

void ui_unpair_pad_key(uint32_t key) {
    if (!U.root) return;

    if (key == LV_KEY_UP) {
        if (U.focus >= U.item_count) {
            /* From bottom buttons to last item (or stay if no items) */
            if (U.item_count > 0) U.focus = U.item_count - 1;
        } else if (U.focus > 0) {
            U.focus--;
        }
        update_focus();
    } else if (key == LV_KEY_DOWN) {
        if (U.focus < U.item_count - 1) {
            U.focus++;
        } else if (U.focus < U.item_count) {
            /* Move to first bottom button */
            U.focus = U.item_count + BTN_CLOSE;
        }
        update_focus();
    } else if (key == LV_KEY_LEFT) {
        if (U.focus >= U.item_count) {
            int b = U.focus - U.item_count;
            if (b > 0) {
                U.focus = U.item_count + b - 1;
                update_focus();
            }
        }
    } else if (key == LV_KEY_RIGHT) {
        if (U.focus >= U.item_count) {
            int b = U.focus - U.item_count;
            if (b < BOTTOM_BTNS - 1) {
                U.focus = U.item_count + b + 1;
                update_focus();
            }
        }
    } else if (key == LV_KEY_ENTER) {
        if (U.focus < U.item_count) {
            /* Unpair focused item */
            char addr[32], name[128];
            snprintf(addr, sizeof(addr), "%s", U.items[U.focus].address);
            snprintf(name, sizeof(name), "%s", U.items[U.focus].name[0] ? U.items[U.focus].name : "Dispositivo");

            log_event(LOG_INFO, "BT", "Desvinculando dispositivo por teclado: %s (%s)", name, addr);
            bluetooth_unpair_device(addr);

            lv_label_set_text_fmt(U.lbl_status, "Dispositivo retirado: %s", name);
            lv_obj_set_style_text_color(U.lbl_status, C(COL_OK), 0);

            refresh_list();
            home_settings_refresh();
        } else {
            int b = U.focus - U.item_count;
            if (b == BTN_REFRESH) {
                refresh_list();
                lv_label_set_text(U.lbl_status, "Lista de dispositivos actualizada.");
                lv_obj_set_style_text_color(U.lbl_status, C(COL_ACCENT_HI), 0);
            } else if (b == BTN_TV) {
                bluetooth_open_system_settings();
                lv_label_set_text(U.lbl_status, "Se abrieron los Ajustes de Bluetooth de la TV.");
                lv_obj_set_style_text_color(U.lbl_status, C(COL_ACCENT_HI), 0);
            } else if (b == BTN_CLOSE) {
                ui_unpair_pad_close();
            }
        }
    } else if (key == LV_KEY_ESC) {
        ui_unpair_pad_close();
    }
}
