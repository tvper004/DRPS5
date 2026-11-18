/* ui/pair_pad.c - Bluetooth controller pairing modal dialog. */
#include "pair_pad.h"

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

#define PAIR_PAD_W   1040
#define PAIR_PAD_H   620
#define BTN_COUNT    3
#define BTN_H        56

enum {
    BTN_SCAN = 0,
    BTN_TV,
    BTN_CLOSE
};

static struct {
    lv_obj_t *root;
    lv_obj_t *scrim;
    lv_obj_t *card;
    lv_obj_t *lbl_status;
    lv_obj_t *btn[BTN_COUNT];
    int focus;
    lv_timer_t *scan_timer;
    lv_timer_t *auto_close_timer;
    int scan_ticks;
    char last_attempt_addr[32];
} P;

static void update_focus(void) {
    if (!P.root) return;
    for (int i = 0; i < BTN_COUNT; i++) {
        if (P.btn[i]) ctl_button_focus(P.btn[i], P.focus == i);
    }
}

static void on_auto_close_cb(lv_timer_t *t) {
    (void)t;
    P.auto_close_timer = NULL;
    ui_pair_pad_close();
    home_settings_refresh();
}

static void on_scan_timer_cb(lv_timer_t *t) {
    (void)t;
    if (!P.root) return;
    input_tick();
    if (input_pad_state() == PAD_ONLINE) {
        lv_label_set_text_fmt(P.lbl_status, "Mando conectado: %s!\nListo para jugar.", input_pad_name());
        lv_obj_set_style_text_color(P.lbl_status, C(COL_OK), 0);
        if (P.scan_timer) {
            lv_timer_del(P.scan_timer);
            P.scan_timer = NULL;
        }
        if (!P.auto_close_timer) {
            P.auto_close_timer = lv_timer_create(on_auto_close_cb, 1800, NULL);
            lv_timer_set_repeat_count(P.auto_close_timer, 1);
        }
        return;
    }

    if (bluetooth_is_pairing()) {
        lv_label_set_text(P.lbl_status, "Sincronizando enlace Bluetooth con el mando...\nPor favor espera unos segundos.");
        lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);
        return;
    }

    if (bluetooth_is_connecting()) {
        lv_label_set_text(P.lbl_status, "Conectando interfaz del mando (HID)...\nPor favor espera.");
        lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);
        return;
    }

    P.scan_ticks++;
    bt_device_t devs[32];
    int n = bluetooth_get_devices(devs, 32);
    for (int i = 0; i < n; i++) {
        if (devs[i].is_gamepad && devs[i].address[0] && strcmp(P.last_attempt_addr, devs[i].address) != 0) {
            log_event(LOG_INFO, "BT", "Mando detectado: %s (%s, paired=%d, conn=%d)", devs[i].name, devs[i].address,
                      devs[i].paired, devs[i].connected);
            snprintf(P.last_attempt_addr, sizeof(P.last_attempt_addr), "%s", devs[i].address);
            lv_label_set_text_fmt(P.lbl_status, "Mando detectado: %s\n%s", devs[i].name,
                                  devs[i].paired ? "Intentando conectar el mando vinculado..." : "Iniciando emparejamiento...");
            lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);
            if (devs[i].paired) bluetooth_connect_hid(devs[i].address);
            else bluetooth_pair_device(devs[i].address);
            return;
        }
    }

    if (P.scan_ticks >= 25) {
        if (P.scan_timer) {
            lv_timer_del(P.scan_timer);
            P.scan_timer = NULL;
        }
        lv_label_set_text(P.lbl_status,
                          "No se pudo conectar el mando.\nEnciendelo y vuelve a intentar. Si sigue fallando,\ndesvinculalo y emparejalo de nuevo con Create + PS.");
        lv_obj_set_style_text_color(P.lbl_status, C(COL_ERR), 0);
    } else {
        lv_label_set_text_fmt(P.lbl_status,
                              "Buscando mandos Bluetooth cercanos... (%ds)\nPon tu mando en modo de sincronizacion.",
                              25 - P.scan_ticks);
    }
}

static void start_scanning(void) {
    P.scan_ticks = 0;
    P.last_attempt_addr[0] = '\0';

    bluetooth_start_discovery();
    lv_label_set_text(P.lbl_status, "Iniciando busqueda de mandos Bluetooth...\nPon tu mando en modo de sincronizacion.");
    lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);

    if (P.scan_timer) lv_timer_del(P.scan_timer);
    P.scan_timer = lv_timer_create(on_scan_timer_cb, 1000, NULL);
}

static void on_btn_clicked(lv_event_t *e) {
    int id = (int)(intptr_t)lv_event_get_user_data(e);
    P.focus = id;
    update_focus();

    if (id == BTN_SCAN) {
        start_scanning();
    } else if (id == BTN_TV) {
        bluetooth_open_system_settings();
        lv_label_set_text(P.lbl_status, "Se abrieron los Ajustes de Bluetooth de la TV.");
        lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);
    } else if (id == BTN_CLOSE) {
        ui_pair_pad_close();
    }
}

/* custom button for pair_pad using FONT_BODY for perfect fit and no clipping */
static lv_obj_t *pad_btn(lv_obj_t *parent, lv_coord_t w, lv_coord_t h, const char *icon, const char *text) {
    lv_obj_t *b = ctl_pill(parent, w, h);
    lv_obj_t *row = ctl_row(b, 10);
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

void ui_pair_pad_open(void) {
    if (P.root) return;
    memset(&P, 0, sizeof(P));

    P.root = ctl_obj(lv_layer_top());
    lv_obj_set_size(P.root, LV_PCT(100), LV_PCT(100));

    P.scrim = ctl_rect(P.root, LV_PCT(100), LV_PCT(100), 0, COL_SHADE, LV_OPA_TRANSP);
    motion_to(P.scrim, MO_BG_OPA, 200, 260, 0, NULL);

    P.card = ctl_rect(P.root, PAIR_PAD_W, PAIR_PAD_H, 36, COL_SHEET, 252);
    lv_obj_set_style_border_width(P.card, 2, 0);
    lv_obj_set_style_border_color(P.card, lv_color_white(), 0);
    lv_obj_set_style_border_opa(P.card, LV_OPA_20, 0);
    lv_obj_set_style_shadow_width(P.card, 80, 0);
    lv_obj_set_style_shadow_opa(P.card, LV_OPA_60, 0);
    lv_obj_center(P.card);

    /* Left panel: Art illustration */
    lv_obj_t *art_box = ctl_rect(P.card, 240, 240, 30, 0, LV_OPA_COVER);
    ctl_grad(art_box, 0x1f3460, 0x091122);
    lv_obj_set_pos(art_box, 40, 48);
    lv_obj_center(art_create(art_box, ART_DUALSENSE, 180));

    lv_obj_t *art_lbl = ctl_label(P.card, FONT_SMALL, COL_MUTED, "DUALSENSE / DS4 / XBOX");
    lv_obj_set_style_text_letter_space(art_lbl, 2, 0);
    lv_obj_set_pos(art_lbl, 44, 308);

    /* Right panel: Instructions */
    lv_coord_t tx = 310, tw = PAIR_PAD_W - tx - 40; /* 690px */
    lv_obj_t *ttl = ctl_label(P.card, FONT_TITLE, COL_TEXT, "Vincular mando Bluetooth");
    lv_obj_set_pos(ttl, tx, 40);

    lv_obj_t *instr = ctl_label(P.card, FONT_BODY, COL_SUBTLE,
                                "Pasos para sincronizar tu mando inalambrico:\n\n"
                                "1. Pon el mando en modo de emparejamiento:\n"
                                "   - DualSense: Manten pulsados Create y PS.\n"
                                "   - DualShock 4: Manten pulsados Share y PS.\n"
                                "   - Xbox: Manten pulsado el boton de enlace.\n"
                                "2. Pulsa 'Buscar mando' para detectarlo y conectarlo.");
    lv_obj_set_width(instr, tw);
    lv_label_set_long_mode(instr, LV_LABEL_LONG_WRAP);
    lv_obj_set_pos(instr, tx, 96);

    /* Status card - positioned cleanly below instructions */
    lv_obj_t *stat_box = ctl_rect(P.card, tw, 80, 16, COL_FROST, 16);
    lv_obj_set_style_border_width(stat_box, 1, 0);
    lv_obj_set_style_border_color(stat_box, lv_color_white(), 0);
    lv_obj_set_style_border_opa(stat_box, LV_OPA_10, 0);
    lv_obj_set_pos(stat_box, tx, 320);

    P.lbl_status = ctl_label(stat_box, FONT_BODY, COL_TEXT, "Listo para buscar mandos...");
    lv_obj_set_width(P.lbl_status, tw - 32);
    lv_label_set_long_mode(P.lbl_status, LV_LABEL_LONG_WRAP);
    lv_obj_set_pos(P.lbl_status, 16, 14);

    /* Buttons row - spacious layout at bottom right */
    lv_obj_t *btn_row = ctl_obj(P.card);
    lv_obj_set_size(btn_row, tw, BTN_H);
    lv_obj_align(btn_row, LV_ALIGN_BOTTOM_RIGHT, -40, -40);

    P.btn[BTN_SCAN] = pad_btn(btn_row, 240, BTN_H, LV_SYMBOL_REFRESH, "Buscar mando");
    lv_obj_set_pos(P.btn[BTN_SCAN], 0, 0);

    P.btn[BTN_TV] = pad_btn(btn_row, 240, BTN_H, LV_SYMBOL_SETTINGS, "Ajustes de TV");
    lv_obj_set_pos(P.btn[BTN_TV], 256, 0);

    P.btn[BTN_CLOSE] = pad_btn(btn_row, 160, BTN_H, LV_SYMBOL_CLOSE, "Cerrar");
    lv_obj_set_pos(P.btn[BTN_CLOSE], 512, 0);

    for (int i = 0; i < BTN_COUNT; i++) {
        lv_obj_add_flag(P.btn[i], LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(P.btn[i], on_btn_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)i);
    }

    P.focus = BTN_SCAN;
    update_focus();

    motion_from(P.card, MO_GROW, -40, 0, 380, 0, motion_spring);
    motion_from(P.card, MO_OPA, 0, 255, 200, 0, NULL);
    log_event(LOG_INFO, "UI", "dialog: pair controller opened");
}

void ui_pair_pad_close(void) {
    if (!P.root) return;
    if (P.scan_timer) {
        lv_timer_del(P.scan_timer);
        P.scan_timer = NULL;
    }
    if (P.auto_close_timer) {
        lv_timer_del(P.auto_close_timer);
        P.auto_close_timer = NULL;
    }
    if (input_pad_state() != PAD_ONLINE) {
        bluetooth_cancel_discovery();
    }
    lv_obj_del(P.root);
    memset(&P, 0, sizeof(P));
    log_event(LOG_INFO, "UI", "dialog: pair controller closed");
}

bool ui_pair_pad_active(void) {
    return P.root != NULL;
}

void ui_pair_pad_key(uint32_t key) {
    if (!P.root) return;
    if (key == LV_KEY_LEFT) {
        P.focus = (P.focus + BTN_COUNT - 1) % BTN_COUNT;
        update_focus();
    } else if (key == LV_KEY_RIGHT) {
        P.focus = (P.focus + 1) % BTN_COUNT;
        update_focus();
    } else if (key == LV_KEY_ENTER) {
        if (P.focus == BTN_SCAN) {
            start_scanning();
        } else if (P.focus == BTN_TV) {
            bluetooth_open_system_settings();
            lv_label_set_text(P.lbl_status, "Se abrieron los Ajustes de Bluetooth de la TV.");
            lv_obj_set_style_text_color(P.lbl_status, C(COL_ACCENT_HI), 0);
        } else if (P.focus == BTN_CLOSE) {
            ui_pair_pad_close();
        }
    } else if (key == LV_KEY_ESC) {
        ui_pair_pad_close();
    }
}
