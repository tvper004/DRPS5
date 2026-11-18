/* ui/language.c - translations for common interface labels. */
#include "language.h"
#include <string.h>
#include "../config/config.h"
static const char *const g_text[][4] = {
    { "Transmision", "Streaming", "Transmission", "Transmissao" },
    { "Mando", "Controller", "Manette", "Controle" },
    { "Cuenta PSN", "PSN account", "Compte PSN", "Conta PSN" },
    { "Registro", "Log", "Journal", "Registro" },
    { "Acerca de", "About", "A propos", "Sobre" },
    { "Resolucion", "Resolution", "Resolution", "Resolucao" },
    { "Tasa de cuadros", "Frame rate", "Images par seconde", "Taxa de quadros" },
    { "Tasa de bits", "Bitrate", "Debit video", "Taxa de bits" },
    { "Suavizado", "Smooth playback", "Lecture fluide", "Reproducao suave" },
    { "Idioma", "Language", "Langue", "Idioma" },
    { "Selecciona el idioma del sistema", "Select the interface language", "Choisir la langue de interface", "Selecione o idioma da interface" },
    { "Diagnostico", "Diagnostics", "Diagnostic", "Diagnostico" },
    { "Red", "Network", "Reseau", "Rede" },
    { "Compilado con", "Built with", "Compile avec", "Compilado com" },
    { "Vincular mando", "Pair controller", "Associer manette", "Parear controle" },
    { "Retirar dispositivos", "Remove devices", "Retirer appareils", "Remover dispositivos" },
    { "Vibracion", "Vibration", "Vibration", "Vibracao" },
    { "Panel tactil", "Touchpad", "Pave tactile", "Painel de toque" },
    { "Anadir consola", "Add console", "Ajouter console", "Adicionar console" },
    { "Buscar mis consolas", "Find my consoles", "Trouver mes consoles", "Buscar meus consoles" },
    { "Cerrar sesion de PSN", "Sign out of PSN", "Se deconnecter du PSN", "Sair da PSN" },
    { "Desactivado", "Off", "Desactive", "Desativado" },
    { "DATOS DE TRANSMISION", "STREAM DETAILS", "DONNEES DU FLUX", "DADOS DA TRANSMISSAO" },
    { "ANCHO DE BANDA", "BANDWIDTH", "BANDE PASSANTE", "LARGURA DE BANDA" },
    { "MANDO", "CONTROLLER", "MANETTE", "CONTROLE" },
    { "ACERCA DE", "ABOUT", "A PROPOS", "SOBRE" },
    { "Mayor resolucion requiere mas ancho de banda", "Higher resolution needs more bandwidth", "Une resolution superieure utilise plus de debit", "Maior resolucao exige mais banda" },
    { "60 fps ofrece mayor fluidez en juegos", "60 fps provides smoother gameplay", "60 fps offre un jeu plus fluide", "60 fps oferece mais fluidez" },
    { "Reducela si la imagen presenta tirones", "Lower it if the picture stutters", "Reduire si image saccade", "Reduza se a imagem travar" },
    { "Compensa microcortes de Wi-Fi anadiendo retardo", "Buffers Wi-Fi interruptions with added delay", "Compense les coupures Wi-Fi avec un delai", "Compensa falhas de Wi-Fi com atraso" },
    { "Buscar y emparejar mando DualSense, DualShock o Xbox", "Find and pair DualSense, DualShock or Xbox", "Chercher une manette DualSense, DualShock ou Xbox", "Buscar controle DualSense, DualShock ou Xbox" },
    { "Desvincular mandos Bluetooth guardados en la TV", "Remove Bluetooth controllers saved on the TV", "Retirer les manettes Bluetooth de la TV", "Remover controles Bluetooth salvos na TV" },
    { "Retirar", "Remove", "Retirer", "Remover" },
    { "Actualizar", "Refresh", "Actualiser", "Atualizar" },
    { "Cerrar", "Close", "Fermer", "Fechar" },
    { "Ajustes de TV", "TV settings", "Reglages TV", "Ajustes da TV" },
    { "Buscar mando", "Find controller", "Chercher manette", "Buscar controle" },
    { "Limpiar antiguos", "Clear old", "Effacer anciens", "Limpar antigos" },
    { "Retirar dispositivos Bluetooth", "Remove Bluetooth devices", "Retirer appareils Bluetooth", "Remover dispositivos Bluetooth" },
    { "Vincular mando Bluetooth", "Pair Bluetooth controller", "Associer manette Bluetooth", "Parear controle Bluetooth" },
    { "Conectado", "Connected", "Connecte", "Conectado" },
    { "Vinculado", "Paired", "Associe", "Pareado" },
};
const char *ui_translate(const char *text) {
    if (!text) return "";
    int lang = config_get()->language;
    if (lang < 0 || lang > 3) lang = 0;
    for (unsigned i = 0; i < sizeof(g_text) / sizeof(g_text[0]); i++)
        for (int j = 0; j < 4; j++)
            if (!strcmp(text, g_text[i][j])) return g_text[i][lang];
    return text;
}
void ui_language_refresh(lv_obj_t *root) {
    if (!root) return;
    if (lv_obj_check_type(root, &lv_label_class)) {
        const char *before = lv_label_get_text(root);
        const char *after = ui_translate(before);
        if (after != before) lv_label_set_text(root, after);
    }
    uint32_t n = lv_obj_get_child_cnt(root);
    for (uint32_t i = 0; i < n; i++) ui_language_refresh(lv_obj_get_child(root, i));
}
