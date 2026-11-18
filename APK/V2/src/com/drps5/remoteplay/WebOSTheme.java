package com.drps5.remoteplay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.util.TypedValue;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class WebOSTheme {
    private WebOSTheme() {}

    // Palette matching WEBOS/V2/src/ui/theme.h (DRPS5 Deep Navy & Cyan / Sky Blue)
    public static final int COL_BG_TOP      = 0xFF0B1329;
    public static final int COL_BG_BOTTOM   = 0xFF050811;
    public static final int COL_INSET       = 0xFF0F172A;
    public static final int COL_TRACK       = 0xFF1E293B;
    public static final int COL_LINE        = 0xFF1E3A5F;
    public static final int COL_ACCENT      = 0xFF0284C7;
    public static final int COL_ACCENT_HI   = 0xFF38BDF8;
    public static final int COL_ACCENT_DEEP = 0xFF0369A1;
    public static final int COL_TEXT        = 0xFFF8FAFC;
    public static final int COL_MUTED       = 0xFF94A3B8;
    public static final int COL_DIM         = 0xFF64748B;
    public static final int COL_OK          = 0xFF22C55E;
    public static final int COL_WARN        = 0xFFF59E0B;
    public static final int COL_ERR         = 0xFFEF4444;
    public static final int COL_INFO        = 0xFF38BDF8;

    public static final int COL_PS_CROSS    = 0xFF9DBCFF;
    public static final int COL_PS_CIRCLE   = 0xFFFF8F9A;
    public static final int COL_PS_TRIANGLE = 0xFF3FD3B6;
    public static final int COL_PS_SQUARE   = 0xFFE58AD8;

    public static final int COL_FROST_BG    = 0x1AFFFFFF;
    public static final int COL_FROST_BORDER= 0x33FFFFFF;
    public static final int COL_FROST_SOLID = 0xFFFFFFFF;
    public static final int COL_ON_FROST    = 0xFF070B16;
    public static final int COL_SHEET       = 0xEB070B16;
    public static final int COL_SUBTLE      = 0xFFB4BFD6;

    public static final int COL_TINT_LAN    = 0xFF0369A1;
    public static final int COL_TINT_PSN    = 0xFF083344;
    public static final int COL_TINT_NEUTRAL= 0xFF0F172A;

    public static int dp(Context ctx, float dp) {
        return Math.round(TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP, dp, ctx.getResources().getDisplayMetrics()));
    }

    public static GradientDrawable makeAmbientBackdrop(int tintColor) {
        GradientDrawable gd = new GradientDrawable(
            GradientDrawable.Orientation.TL_BR,
            new int[]{ tintColor, COL_BG_TOP, COL_BG_BOTTOM }
        );
        return gd;
    }

    public static GradientDrawable makeCardDrawable(Context ctx, int fillColor, int strokeColor, int radiusDp, int strokeDp) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(fillColor);
        gd.setCornerRadius(dp(ctx, radiusDp));
        if (strokeDp > 0) {
            gd.setStroke(dp(ctx, strokeDp), strokeColor);
        }
        return gd;
    }

    public static StateListDrawable makeFrostSelector(Context ctx, int radiusDp) {
        StateListDrawable sld = new StateListDrawable();
        GradientDrawable focused = makeCardDrawable(ctx, COL_FROST_SOLID, COL_ACCENT_HI, radiusDp, 2);
        GradientDrawable pressed = makeCardDrawable(ctx, 0x3338BDF8, COL_ACCENT_HI, radiusDp, 2);
        GradientDrawable normal  = makeCardDrawable(ctx, COL_FROST_BG, COL_FROST_BORDER, radiusDp, 1);

        sld.addState(new int[]{ android.R.attr.state_focused }, focused);
        sld.addState(new int[]{ android.R.attr.state_selected }, focused);
        sld.addState(new int[]{ android.R.attr.state_pressed }, pressed);
        sld.addState(new int[]{}, normal);
        return sld;
    }

    public static StateListDrawable makeAccentSelector(Context ctx, int radiusDp) {
        StateListDrawable sld = new StateListDrawable();
        GradientDrawable focused = makeCardDrawable(ctx, COL_ACCENT_HI, COL_FROST_SOLID, radiusDp, 2);
        GradientDrawable pressed = makeCardDrawable(ctx, COL_ACCENT_DEEP, COL_ACCENT_HI, radiusDp, 2);
        GradientDrawable normal  = makeCardDrawable(ctx, COL_ACCENT, 0x5538BDF8, radiusDp, 1);

        sld.addState(new int[]{ android.R.attr.state_focused }, focused);
        sld.addState(new int[]{ android.R.attr.state_pressed }, pressed);
        sld.addState(new int[]{}, normal);
        return sld;
    }

    public static void applyFocusTextToggle(View container, TextView primary, TextView secondary, boolean focused) {
        if (primary != null) {
            primary.setTextColor(focused ? COL_ON_FROST : COL_TEXT);
        }
        if (secondary != null) {
            secondary.setTextColor(focused ? 0xFF334155 : COL_SUBTLE);
        }
        container.animate()
            .scaleX(focused ? 1.03f : 1.0f)
            .scaleY(focused ? 1.03f : 1.0f)
            .setDuration(120)
            .start();
    }

    public static TextView makePill(Context ctx, String text, int bgColor, int textColor) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(textColor);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        tv.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        int ph = dp(ctx, 12);
        int pv = dp(ctx, 5);
        tv.setPadding(ph, pv, ph, pv);
        tv.setBackground(makeCardDrawable(ctx, bgColor, 0x33FFFFFF, 50, 1));
        return tv;
    }

    public static LinearLayout makeHintChip(Context ctx, String glyph, int glyphColor, String label) {
        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        int ph = dp(ctx, 10);
        int pv = dp(ctx, 4);
        row.setPadding(ph, pv, ph, pv);
        row.setBackground(makeCardDrawable(ctx, 0x99070B16, 0x26FFFFFF, 50, 1));

        TextView g = new TextView(ctx);
        g.setText(glyph);
        g.setTextColor(glyphColor);
        g.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        g.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        row.addView(g);

        TextView l = new TextView(ctx);
        l.setText("  " + label);
        l.setTextColor(COL_SUBTLE);
        l.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        row.addView(l);
        return row;
    }
}
