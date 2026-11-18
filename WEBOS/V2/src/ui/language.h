/* ui/language.h - interface text translations. */
#ifndef DRPS5_LANGUAGE_H
#define DRPS5_LANGUAGE_H
#include <lvgl.h>
const char *ui_translate(const char *text);
void ui_language_refresh(lv_obj_t *root);
#endif
