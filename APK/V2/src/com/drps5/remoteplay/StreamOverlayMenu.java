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
        void onSendTouchpad();
        void onCycleUpscale();
        void onToggleTouchControls();
        void onToggleCompactHud();
        void onDisconnect();
    }

    private final TextView chipQuality;
    private final TextView chipTelemetry;
    private final TextView btnResume;
    private final TextView btnTouchpad;
    private final TextView btnUpscale;
    private final TextView btnTouch;
    private final TextView btnCompactHud;
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
            selectedIndex = 0;
            updateVisualSelection();
            hideMenu();
            if (listener != null) listener.onResumeGame();
        });
        sheet.addView(btnResume, rowLp(ctx));

        btnTouchpad = makeActionBtn(ctx, "⬜  Pulsar Boton Touchpad", false);
        btnTouchpad.setOnClickListener(v -> {
            selectedIndex = 1;
            updateVisualSelection();
            hideMenu();
            if (listener != null) listener.onSendTouchpad();
        });
        sheet.addView(btnTouchpad, rowLp(ctx));

        btnUpscale = makeActionBtn(ctx, "✦  Reescalado GPU: " + cfg.getUpscaleLabel(), false);
        btnUpscale.setOnClickListener(v -> {
            selectedIndex = 2;
            updateVisualSelection();
            if (listener != null) listener.onCycleUpscale();
        });
        sheet.addView(btnUpscale, rowLp(ctx));

        btnTouch = makeActionBtn(ctx, "🎮  Controles tactiles", false);
        btnTouch.setOnClickListener(v -> {
            selectedIndex = 3;
            updateVisualSelection();
            if (listener != null) listener.onToggleTouchControls();
        });
        sheet.addView(btnTouch, rowLp(ctx));

        btnCompactHud = makeActionBtn(ctx, "⚙  HUD en pantalla: " + (cfg.compactHud ? "Solo icono" : "Completo"), false);
        btnCompactHud.setOnClickListener(v -> {
            selectedIndex = 4;
            updateVisualSelection();
            if (listener != null) listener.onToggleCompactHud();
        });
        sheet.addView(btnCompactHud, rowLp(ctx));

        btnDisconnect = makeActionBtn(ctx, "✕  Desconectar sesion", false);
        btnDisconnect.setOnClickListener(v -> {
            selectedIndex = 5;
            updateVisualSelection();
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
        post(() -> {
            updateVisualSelection();
            scroll.smoothScrollTo(0, 0);
        });
    }

    public void hideMenu() {
        setVisibility(GONE);
    }

    public boolean isMenuOpen() {
        return getVisibility() == VISIBLE;
    }

    public void moveSelection(int delta) {
        if (actionButtons.isEmpty()) return;
        selectedIndex = (selectedIndex + delta + actionButtons.size()) % actionButtons.size();
        updateVisualSelection();
    }

    public void updateVisualSelection() {
        if (actionButtons.isEmpty()) return;
        for (int i = 0; i < actionButtons.size(); i++) {
            TextView btn = actionButtons.get(i);
            boolean isSel = (i == selectedIndex);
            btn.setSelected(isSel);
            if (isSel) {
                if (btn == btnDisconnect) {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), 0xFFDC2626, 0xFFFFFFFF, 12, 2));
                    btn.setTextColor(0xFFFFFFFF);
                } else if (btn == btnResume) {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), WebOSTheme.COL_ACCENT_HI, 0xFFFFFFFF, 12, 2));
                    btn.setTextColor(0xFF030712);
                } else {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), WebOSTheme.COL_ACCENT, WebOSTheme.COL_ACCENT_HI, 12, 2));
                    btn.setTextColor(0xFFFFFFFF);
                }
                btn.setScaleX(1.04f);
                btn.setScaleY(1.04f);
                try { btn.setElevation(WebOSTheme.dp(getContext(), 4)); } catch (Throwable ignored) {}
                btn.requestFocus();
                final TextView target = btn;
                post(() -> {
                    int targetY = target.getTop() - (scroll.getHeight() / 2) + (target.getHeight() / 2);
                    scroll.smoothScrollTo(0, Math.max(0, targetY));
                });
            } else {
                if (btn == btnDisconnect) {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), WebOSTheme.COL_FROST_BG, 0x55EF4444, 12, 1));
                    btn.setTextColor(WebOSTheme.COL_PS_CIRCLE);
                } else if (btn == btnResume) {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), 0x330284C7, WebOSTheme.COL_FROST_BORDER, 12, 1));
                    btn.setTextColor(WebOSTheme.COL_TEXT);
                } else {
                    btn.setBackground(WebOSTheme.makeCardDrawable(getContext(), WebOSTheme.COL_FROST_BG, WebOSTheme.COL_FROST_BORDER, 12, 1));
                    btn.setTextColor(WebOSTheme.COL_TEXT);
                }
                btn.setScaleX(1.0f);
                btn.setScaleY(1.0f);
                try { btn.setElevation(0f); } catch (Throwable ignored) {}
            }
        }
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
        tv.setFocusableInTouchMode(true);
        tv.setClickable(true);
        tv.setBackground(WebOSTheme.makeCardDrawable(ctx, WebOSTheme.COL_FROST_BG, WebOSTheme.COL_FROST_BORDER, 12, 1));

        final int myIdx = actionButtons.size();
        tv.setOnFocusChangeListener((v, hasFocus) -> {
            if (hasFocus && selectedIndex != myIdx) {
                selectedIndex = myIdx;
                updateVisualSelection();
            }
        });
        actionButtons.add(tv);
        return tv;
    }
}
