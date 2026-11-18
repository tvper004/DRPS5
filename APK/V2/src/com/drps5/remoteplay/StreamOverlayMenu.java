package com.drps5.remoteplay;

import android.content.Context;
import android.graphics.Typeface;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * WebOS V2-inspired frosted dark in-stream overlay menu (COL_SHEET + live chips + quick toggles).
 */
public final class StreamOverlayMenu extends FrameLayout {
    public interface Listener {
        void onResumeGame();
        void onCycleUpscale();
        void onToggleTouchControls();
        void onSendPsButton();
        void onDisconnect();
    }

    private final TextView chipQuality;
    private final TextView chipTelemetry;
    private final TextView btnUpscale;
    private final TextView btnTouch;
    private final TextView btnResume;
    private final Listener listener;

    public StreamOverlayMenu(Context ctx, ConfigStore cfg, Listener listener) {
        super(ctx);
        this.listener = listener;
        setVisibility(GONE);
        setBackgroundColor(0x99050811);
        setClickable(true);
        setFocusable(false);

        LinearLayout sheet = new LinearLayout(ctx);
        sheet.setOrientation(LinearLayout.VERTICAL);
        sheet.setPadding(WebOSTheme.dp(ctx, 28), WebOSTheme.dp(ctx, 24), WebOSTheme.dp(ctx, 28), WebOSTheme.dp(ctx, 24));
        sheet.setBackground(WebOSTheme.makeCardDrawable(ctx, WebOSTheme.COL_SHEET, WebOSTheme.COL_FROST_BORDER, 20, 1));

        FrameLayout.LayoutParams slp = new FrameLayout.LayoutParams(
            WebOSTheme.dp(ctx, 560), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        addView(sheet, slp);

        TextView title = new TextView(ctx);
        title.setText("MENU DE TRANSMISION");
        title.setTextColor(WebOSTheme.COL_ACCENT_HI);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(0.08f);
        sheet.addView(title);

        LinearLayout chipsRow = new LinearLayout(ctx);
        chipsRow.setOrientation(LinearLayout.HORIZONTAL);
        chipsRow.setPadding(0, WebOSTheme.dp(ctx, 10), 0, WebOSTheme.dp(ctx, 16));
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

        TextView btnPs = makeActionBtn(ctx, "⌘  Pulsar Boton PS", false);
        btnPs.setOnClickListener(v -> {
            if (listener != null) listener.onSendPsButton();
            hideMenu();
        });
        sheet.addView(btnPs, rowLp(ctx));

        TextView btnDisconnect = makeActionBtn(ctx, "✕  Desconectar sesion", false);
        btnDisconnect.setTextColor(WebOSTheme.COL_PS_CIRCLE);
        btnDisconnect.setOnClickListener(v -> {
            hideMenu();
            if (listener != null) listener.onDisconnect();
        });
        sheet.addView(btnDisconnect, rowLp(ctx));
    }

    public void updateStats(String qualityText, String telemetryText, String upscaleLabel, boolean touchVisible) {
        chipQuality.setText(qualityText);
        chipTelemetry.setText(telemetryText);
        btnUpscale.setText("✦  Reescalado GPU: " + upscaleLabel);
        btnTouch.setText("🎮  Controles tactiles: " + (touchVisible ? "Visibles" : "Ocultos"));
    }

    public void showMenu() {
        setVisibility(VISIBLE);
        btnResume.requestFocus();
    }

    public void hideMenu() {
        setVisibility(GONE);
    }

    public boolean isMenuOpen() {
        return getVisibility() == VISIBLE;
    }

    private static LinearLayout.LayoutParams rowLp(Context ctx) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = WebOSTheme.dp(ctx, 8);
        return lp;
    }

    private static TextView makeActionBtn(Context ctx, String text, boolean primary) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(WebOSTheme.COL_TEXT);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setPadding(WebOSTheme.dp(ctx, 16), WebOSTheme.dp(ctx, 13), WebOSTheme.dp(ctx, 16), WebOSTheme.dp(ctx, 13));
        tv.setFocusable(true);
        tv.setClickable(true);
        tv.setBackground(primary ? WebOSTheme.makeAccentSelector(ctx, 12) : WebOSTheme.makeFrostSelector(ctx, 12));
        tv.setOnFocusChangeListener((v, hasFocus) -> {
            if (!primary) {
                tv.setTextColor(hasFocus ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_TEXT);
            }
            v.animate().scaleX(hasFocus ? 1.02f : 1.0f).scaleY(hasFocus ? 1.02f : 1.0f).setDuration(100).start();
        });
        return tv;
    }
}
