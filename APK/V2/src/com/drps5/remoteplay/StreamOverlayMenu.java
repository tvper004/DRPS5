package com.drps5.remoteplay;

import android.content.Context;
import android.graphics.Typeface;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

/**
 * WebOS V2-inspired frosted dark in-stream overlay menu (COL_SHEET + live chips + quick toggles).
 * Soporta navegación fluida por Control Remoto (TV), Cruceta (D-Pad) y Análogo Izquierdo.
 */
public final class StreamOverlayMenu extends FrameLayout {
    public interface Listener {
        void onResumeGame();
        void onCycleUpscale();
        void onToggleTouchControls();
        void onToggleCompactHud();
        void onSendPsButton();
        void onDisconnect();
    }

    private final TextView chipQuality;
    private final TextView chipTelemetry;
    private final TextView btnUpscale;
    private final TextView btnTouch;
    private final TextView btnCompactHud;
    private final TextView btnResume;
    private final TextView btnDisconnect;
    private final List<TextView> actionButtons = new ArrayList<>();
    private int selectedIndex = 0;
    private final ScrollView scroll;
    private final Listener listener;

    public StreamOverlayMenu(Context ctx, ConfigStore cfg, Listener listener) {
        super(ctx);
        this.listener = listener;
        setVisibility(GONE);
        setBackgroundColor(0x99050811);
        setClickable(true);
        setFocusable(false);

        scroll = new ScrollView(ctx);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setFocusable(false);
        scroll.setDescendantFocusability(ViewGroup.FOCUS_AFTER_DESCENDANTS);
        FrameLayout.LayoutParams scLp = new FrameLayout.LayoutParams(
            WebOSTheme.dp(ctx, 560), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        scLp.topMargin = WebOSTheme.dp(ctx, 8);
        scLp.bottomMargin = WebOSTheme.dp(ctx, 8);
        addView(scroll, scLp);

        LinearLayout sheet = new LinearLayout(ctx);
        sheet.setOrientation(LinearLayout.VERTICAL);
        sheet.setFocusable(false);
        sheet.setDescendantFocusability(ViewGroup.FOCUS_AFTER_DESCENDANTS);
        sheet.setPadding(WebOSTheme.dp(ctx, 20), WebOSTheme.dp(ctx, 14), WebOSTheme.dp(ctx, 20), WebOSTheme.dp(ctx, 14));
        sheet.setBackground(WebOSTheme.makeCardDrawable(ctx, WebOSTheme.COL_SHEET, WebOSTheme.COL_FROST_BORDER, 20, 1));
        scroll.addView(sheet, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(ctx);
        title.setText("MENU DE TRANSMISION");
        title.setTextColor(WebOSTheme.COL_ACCENT_HI);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(0.08f);
        sheet.addView(title);

        LinearLayout chipsRow = new LinearLayout(ctx);
        chipsRow.setOrientation(LinearLayout.HORIZONTAL);
        chipsRow.setPadding(0, WebOSTheme.dp(ctx, 6), 0, WebOSTheme.dp(ctx, 10));
        sheet.addView(chipsRow);

        chipQuality = WebOSTheme.makePill(ctx, cfg.getResolutionLabel() + " • " + cfg.fps + " fps", WebOSTheme.COL_TRACK, WebOSTheme.COL_TEXT);
        chipsRow.addView(chipQuality);

        View spacer = new View(ctx);
        chipsRow.addView(spacer, new LinearLayout.LayoutParams(WebOSTheme.dp(ctx, 8), 1));

        chipTelemetry = WebOSTheme.makePill(ctx, "Conectado", 0x3322C55E, WebOSTheme.COL_OK);
        chipsRow.addView(chipTelemetry);

        btnResume = makeActionBtn(ctx, "▶  Volver al juego", true);
        btnResume.setOnClickListener(v -> {
            hideMenu();
            if (listener != null) listener.onResumeGame();
        });
        sheet.addView(btnResume, rowLp(ctx));

        btnUpscale = makeActionBtn(ctx, "✦  Reescalado GPU: " + cfg.getUpscaleLabel(), false);
        btnUpscale.setOnClickListener(v -> {
            if (listener != null) listener.onCycleUpscale();
        });
        sheet.addView(btnUpscale, rowLp(ctx));

        btnTouch = makeActionBtn(ctx, "🎮  Controles tactiles", false);
        btnTouch.setOnClickListener(v -> {
            if (listener != null) listener.onToggleTouchControls();
        });
        sheet.addView(btnTouch, rowLp(ctx));

        btnCompactHud = makeActionBtn(ctx, "⚙  HUD en pantalla: " + (cfg.compactHud ? "Solo icono" : "Completo"), false);
        btnCompactHud.setOnClickListener(v -> {
            if (listener != null) listener.onToggleCompactHud();
        });
        sheet.addView(btnCompactHud, rowLp(ctx));

        btnDisconnect = makeActionBtn(ctx, "✕  Desconectar sesion", false);
        btnDisconnect.setTextColor(WebOSTheme.COL_PS_CIRCLE);
        btnDisconnect.setOnClickListener(v -> {
            hideMenu();
            if (listener != null) listener.onDisconnect();
        });
        sheet.addView(btnDisconnect, rowLp(ctx));
    }

    public void updateStats(String qualityText, String telemetryText, String upscaleLabel, boolean touchVisible, boolean compactHud) {
        chipQuality.setText(qualityText);
        chipTelemetry.setText(telemetryText);
        btnUpscale.setText("✦  Reescalado GPU: " + upscaleLabel);
        btnTouch.setText("🎮  Controles tactiles: " + (touchVisible ? "Visibles" : "Ocultos"));
        btnCompactHud.setText("⚙  HUD en pantalla: " + (compactHud ? "Solo icono" : "Completo"));
    }

    public void showMenu() {
        setVisibility(VISIBLE);
        selectedIndex = 0;
        if (!actionButtons.isEmpty()) {
            TextView first = actionButtons.get(0);
            first.requestFocus();
            scroll.smoothScrollTo(0, 0);
        }
    }

    public void hideMenu() {
        setVisibility(GONE);
    }

    public boolean isMenuOpen() {
        return getVisibility() == VISIBLE;
    }

    public void moveSelection(int delta) {
        if (actionButtons.isEmpty()) return;
        selectedIndex = Math.max(0, Math.min(actionButtons.size() - 1, selectedIndex + delta));
        TextView target = actionButtons.get(selectedIndex);
        target.requestFocus();
        scroll.requestChildFocus(target, target);
    }

    public void activateCurrent() {
        if (selectedIndex >= 0 && selectedIndex < actionButtons.size()) {
            actionButtons.get(selectedIndex).performClick();
        }
    }

    private static LinearLayout.LayoutParams rowLp(Context ctx) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = WebOSTheme.dp(ctx, 6);
        return lp;
    }

    private TextView makeActionBtn(Context ctx, String text, boolean primary) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(WebOSTheme.COL_TEXT);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setPadding(WebOSTheme.dp(ctx, 14), WebOSTheme.dp(ctx, 9), WebOSTheme.dp(ctx, 14), WebOSTheme.dp(ctx, 9));
        tv.setFocusable(true);
        tv.setClickable(true);
        tv.setBackground(primary ? WebOSTheme.makeAccentSelector(ctx, 12) : WebOSTheme.makeFrostSelector(ctx, 12));
        
        final int myIdx = actionButtons.size();
        tv.setOnFocusChangeListener((v, hasFocus) -> {
            if (hasFocus) {
                selectedIndex = myIdx;
            }
            if (!primary) {
                tv.setTextColor(hasFocus ? WebOSTheme.COL_ON_FROST : (v == btnDisconnect ? WebOSTheme.COL_PS_CIRCLE : WebOSTheme.COL_TEXT));
            }
            v.animate().scaleX(hasFocus ? 1.02f : 1.0f).scaleY(hasFocus ? 1.02f : 1.0f).setDuration(100).start();
        });
        actionButtons.add(tv);
        return tv;
    }
}
