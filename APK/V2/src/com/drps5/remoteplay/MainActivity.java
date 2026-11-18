package com.drps5.remoteplay;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.BitmapDrawable;
import android.hardware.input.InputManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Display;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.InputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Enumeration;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String APP_VERSION = "2.0.0";

    private ConfigStore cfg;
    private final Handler uiHandler = new Handler(Looper.getMainLooper());

    private FrameLayout rootContainer;
    private LinearLayout homeRoot;
    private FrameLayout splashOverlay;

    // Top bar
    private TextView tabConsolesBtn;
    private TextView tabSettingsBtn;
    private TextView badgePad;
    private TextView badgeNet;
    private TextView clockLabel;

    // Pages
    private View consolesPage;
    private View settingsPage;
    private int activeTab = 0; // 0 = Consoles, 1 = Settings
    private int activeSettingsCat = 0; // 0=Stream, 1=Control, 2=Account, 3=Log, 4=About

    // Consoles UI
    private LinearLayout consoleCardsRow;
    private TextView detailTitle;
    private TextView detailSub;
    private TextView detailSummaryPill;
    private LinearLayout detailActionsRow;
    private String selectedConsoleId = "";

    // Settings UI
    private LinearLayout settingsCatRow;
    private LinearLayout settingsRowsContainer;
    private TextView logConsoleView;

    // Stream UI
    private FrameLayout streamContainer;
    private UpscaleRenderer upscaleRenderer;
    private SurfaceView directSurfaceView;
    private TouchGamepadOverlayView touchOverlay;
    private StreamOverlayMenu streamOverlayMenu;
    private TextView streamHudPill;
    private PS5StreamClient streamClient;
    private boolean streaming = false;
    private boolean hasPhysicalGamepad = false;
    private long lastBackPressMs = 0;

    // Gamepad state
    private boolean gpShareDown = false;
    private boolean gpOptionsDown = false;

    private final Runnable clockTick = new Runnable() {
        @Override
        public void run() {
            if (clockLabel != null) {
                clockLabel.setText(new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date()));
            }
            uiHandler.postDelayed(this, 15000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN);

        cfg = new ConfigStore(this);
        AppLogger.init(this, cfg.probeLog);
        AppLogger.i("UI", "DRPS5 V2 starting (edition=" + (Guard.IS_PERSONAL ? "Personal" : "Publica") + ")");

        hasPhysicalGamepad = detectPhysicalGamepad();
        registerInputListener();

        rootContainer = new FrameLayout(this);
        rootContainer.setBackground(WebOSTheme.makeAmbientBackdrop(WebOSTheme.COL_TINT_LAN));
        setContentView(rootContainer);

        buildHomeUi();
        buildStreamUi();
        buildSplashOverlay();

        refreshConsolesUi();
        refreshSettingsUi();
        switchTab(0);
        clockTick.run();

        uiHandler.postDelayed(() -> {
            if (splashOverlay != null) {
                splashOverlay.animate().alpha(0f).setDuration(260).withEndAction(() -> {
                    splashOverlay.setVisibility(View.GONE);
                    focusInitialConsole();
                }).start();
            }
        }, 650);
    }

    @Override
    protected void onResume() {
        super.onResume();
        applyImmersiveFullscreen();
    }

    @Override
    protected void onDestroy() {
        uiHandler.removeCallbacks(clockTick);
        stopStreamSession();
        super.onDestroy();
    }

    private void applyImmersiveFullscreen() {
        try {
            getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            );
        } catch (Throwable ignored) {}
    }

    private void buildSplashOverlay() {
        splashOverlay = new FrameLayout(this);
        splashOverlay.setBackground(WebOSTheme.makeAmbientBackdrop(WebOSTheme.COL_BG_TOP));
        splashOverlay.setClickable(true);

        LinearLayout center = new LinearLayout(this);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER);

        ImageView icon = new ImageView(this);
        Bitmap bmp = loadAssetBitmap("drps5_icon.png");
        if (bmp != null) icon.setImageBitmap(bmp);
        center.addView(icon, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 108), WebOSTheme.dp(this, 108)));

        TextView t = new TextView(this);
        t.setText("DRPS5");
        t.setTextColor(WebOSTheme.COL_TEXT);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 32);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setPadding(0, WebOSTheme.dp(this, 14), 0, WebOSTheme.dp(this, 4));
        center.addView(t);

        TextView sub = new TextView(this);
        sub.setText("Remote Play " + APP_VERSION + "  •  " + (Guard.IS_PERSONAL ? "Edicion Personal" : "Edicion Publica"));
        sub.setTextColor(WebOSTheme.COL_ACCENT_HI);
        sub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        center.addView(sub);

        ProgressBar pb = new ProgressBar(this);
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(WebOSTheme.dp(this, 32), WebOSTheme.dp(this, 32));
        plp.topMargin = WebOSTheme.dp(this, 22);
        center.addView(pb, plp);

        splashOverlay.addView(center, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        rootContainer.addView(splashOverlay, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void buildHomeUi() {
        homeRoot = new LinearLayout(this);
        homeRoot.setOrientation(LinearLayout.VERTICAL);

        // Optional subtle background art
        Bitmap bg = loadAssetBitmap("bg_main.png");
        if (bg != null) {
            BitmapDrawable bd = new BitmapDrawable(getResources(), bg);
            bd.setAlpha(42);
            ImageView bgView = new ImageView(this);
            bgView.setScaleType(ImageView.ScaleType.CENTER_CROP);
            bgView.setImageDrawable(bd);
            rootContainer.addView(bgView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }

        int padH = WebOSTheme.dp(this, 28);
        int padV = WebOSTheme.dp(this, 16);
        homeRoot.setPadding(padH, padV, padH, padV);

        // --- TOP BAR ---
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);

        ImageView logo = new ImageView(this);
        Bitmap bmp = loadAssetBitmap("drps5_icon.png");
        if (bmp != null) logo.setImageBitmap(bmp);
        topBar.addView(logo, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 36), WebOSTheme.dp(this, 36)));

        TextView brand = new TextView(this);
        brand.setText("  DRPS5");
        brand.setTextColor(WebOSTheme.COL_TEXT);
        brand.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        brand.setTypeface(Typeface.DEFAULT_BOLD);
        topBar.addView(brand);

        TextView edBadge = WebOSTheme.makePill(
            this,
            Guard.IS_PERSONAL ? "PERSONAL" : "PUBLICA",
            Guard.IS_PERSONAL ? 0x3338BDF8 : 0x3322C55E,
            Guard.IS_PERSONAL ? WebOSTheme.COL_ACCENT_HI : WebOSTheme.COL_OK
        );
        LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        elp.leftMargin = WebOSTheme.dp(this, 10);
        topBar.addView(edBadge, elp);

        View tabSpacerL = new View(this);
        topBar.addView(tabSpacerL, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 24), 1));

        tabConsolesBtn = makeTabPill("Consolas", 0);
        topBar.addView(tabConsolesBtn);

        View tabGap = new View(this);
        topBar.addView(tabGap, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 8), 1));

        tabSettingsBtn = makeTabPill("Ajustes", 1);
        topBar.addView(tabSettingsBtn);

        View flexSpacer = new View(this);
        topBar.addView(flexSpacer, new LinearLayout.LayoutParams(0, 1, 1f));

        badgePad = WebOSTheme.makePill(this, hasPhysicalGamepad ? "Mando OK" : "Tactil / TV", WebOSTheme.COL_TRACK, WebOSTheme.COL_SUBTLE);
        topBar.addView(badgePad);

        View bGap = new View(this);
        topBar.addView(bGap, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 8), 1));

        badgeNet = WebOSTheme.makePill(this, getLocalIpAddress(), WebOSTheme.COL_TRACK, WebOSTheme.COL_ACCENT_HI);
        topBar.addView(badgeNet);

        clockLabel = new TextView(this);
        clockLabel.setTextColor(WebOSTheme.COL_TEXT);
        clockLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        clockLabel.setTypeface(Typeface.DEFAULT_BOLD);
        clockLabel.setPadding(WebOSTheme.dp(this, 14), 0, 0, 0);
        topBar.addView(clockLabel);

        homeRoot.addView(topBar, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // --- CONTENT AREA ---
        FrameLayout contentFrame = new FrameLayout(this);
        LinearLayout.LayoutParams cflp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        cflp.topMargin = WebOSTheme.dp(this, 14);
        homeRoot.addView(contentFrame, cflp);

        consolesPage = buildConsolesPage();
        settingsPage = buildSettingsPage();
        contentFrame.addView(consolesPage);
        contentFrame.addView(settingsPage);

        // --- BOTTOM HINT BAR ---
        LinearLayout hintBar = new LinearLayout(this);
        hintBar.setOrientation(LinearLayout.HORIZONTAL);
        hintBar.setGravity(Gravity.CENTER_VERTICAL);
        hintBar.setPadding(0, WebOSTheme.dp(this, 8), 0, 0);
        hintBar.addView(WebOSTheme.makeHintChip(this, "✕", WebOSTheme.COL_PS_CROSS, "Seleccionar"));
        View h1 = new View(this); hintBar.addView(h1, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 8), 1));
        hintBar.addView(WebOSTheme.makeHintChip(this, "◯", WebOSTheme.COL_PS_CIRCLE, "Atras / Menu"));
        View h2 = new View(this); hintBar.addView(h2, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 8), 1));
        hintBar.addView(WebOSTheme.makeHintChip(this, "L1/R1", WebOSTheme.COL_PS_TRIANGLE, "Pestañas"));
        homeRoot.addView(hintBar, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        rootContainer.addView(homeRoot, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private TextView makeTabPill(String label, int tabIdx) {
        TextView tv = new TextView(this);
        tv.setText(label);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setPadding(WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 8), WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 8));
        tv.setFocusable(true);
        tv.setClickable(true);
        tv.setOnClickListener(v -> switchTab(tabIdx));
        return tv;
    }

    private void switchTab(int tabIdx) {
        activeTab = tabIdx;
        consolesPage.setVisibility(tabIdx == 0 ? View.VISIBLE : View.GONE);
        settingsPage.setVisibility(tabIdx == 1 ? View.VISIBLE : View.GONE);

        styleTabPill(tabConsolesBtn, tabIdx == 0);
        styleTabPill(tabSettingsBtn, tabIdx == 1);

        if (tabIdx == 0) {
            focusInitialConsole();
        } else {
            refreshSettingsUi();
        }
    }

    private void styleTabPill(TextView tv, boolean active) {
        tv.setTextColor(active ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_SUBTLE);
        tv.setBackground(WebOSTheme.makeCardDrawable(
            this,
            active ? WebOSTheme.COL_FROST_SOLID : WebOSTheme.COL_FROST_BG,
            active ? WebOSTheme.COL_ACCENT_HI : WebOSTheme.COL_FROST_BORDER,
            50,
            1
        ));
    }

    private View buildConsolesPage() {
        ScrollView sv = new ScrollView(this);
        sv.setFillViewport(true);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);

        HorizontalScrollView hsv = new HorizontalScrollView(this);
        hsv.setHorizontalScrollBarEnabled(false);
        consoleCardsRow = new LinearLayout(this);
        consoleCardsRow.setOrientation(LinearLayout.HORIZONTAL);
        consoleCardsRow.setPadding(WebOSTheme.dp(this, 4), WebOSTheme.dp(this, 8), WebOSTheme.dp(this, 4), WebOSTheme.dp(this, 12));
        hsv.addView(consoleCardsRow);
        page.addView(hsv, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // Detail panel (WebOS V2 hero summary card)
        LinearLayout detailCard = new LinearLayout(this);
        detailCard.setOrientation(LinearLayout.VERTICAL);
        detailCard.setPadding(WebOSTheme.dp(this, 24), WebOSTheme.dp(this, 20), WebOSTheme.dp(this, 24), WebOSTheme.dp(this, 20));
        detailCard.setBackground(WebOSTheme.makeCardDrawable(this, 0x88070B16, WebOSTheme.COL_FROST_BORDER, 18, 1));

        LinearLayout headerRow = new LinearLayout(this);
        headerRow.setOrientation(LinearLayout.HORIZONTAL);
        headerRow.setGravity(Gravity.CENTER_VERTICAL);

        LinearLayout titlesCol = new LinearLayout(this);
        titlesCol.setOrientation(LinearLayout.VERTICAL);
        detailTitle = new TextView(this);
        detailTitle.setTextColor(WebOSTheme.COL_TEXT);
        detailTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        detailTitle.setTypeface(Typeface.DEFAULT_BOLD);
        titlesCol.addView(detailTitle);

        detailSub = new TextView(this);
        detailSub.setTextColor(WebOSTheme.COL_SUBTLE);
        detailSub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        detailSub.setPadding(0, WebOSTheme.dp(this, 4), 0, 0);
        titlesCol.addView(detailSub);
        headerRow.addView(titlesCol, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        detailSummaryPill = WebOSTheme.makePill(this, "", WebOSTheme.COL_TRACK, WebOSTheme.COL_ACCENT_HI);
        headerRow.addView(detailSummaryPill);
        detailCard.addView(headerRow);

        HorizontalScrollView actionsScroll = new HorizontalScrollView(this);
        actionsScroll.setHorizontalScrollBarEnabled(false);
        detailActionsRow = new LinearLayout(this);
        detailActionsRow.setOrientation(LinearLayout.HORIZONTAL);
        detailActionsRow.setPadding(0, WebOSTheme.dp(this, 18), 0, WebOSTheme.dp(this, 4));
        actionsScroll.addView(detailActionsRow);
        detailCard.addView(actionsScroll);

        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        dlp.topMargin = WebOSTheme.dp(this, 10);
        page.addView(detailCard, dlp);

        sv.addView(page);
        return sv;
    }

    private void refreshConsolesUi() {
        consoleCardsRow.removeAllViews();
        if (selectedConsoleId.isEmpty() && !cfg.profiles.isEmpty()) {
            ConfigStore.ConsoleProfile act = cfg.getActiveProfile();
            if (act != null) selectedConsoleId = act.id;
        }

        for (ConfigStore.ConsoleProfile cp : cfg.profiles) {
            View card = makeConsoleCard(cp);
            consoleCardsRow.addView(card);
        }
        consoleCardsRow.addView(makeAddConsoleCard());

        updateConsoleDetailPanel();
    }

    private View makeConsoleCard(ConfigStore.ConsoleProfile cp) {
        boolean isSel = cp.id != null && cp.id.equals(selectedConsoleId);
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER_HORIZONTAL);
        card.setPadding(WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16));
        card.setFocusable(true);
        card.setClickable(true);
        card.setBackground(WebOSTheme.makeFrostSelector(this, 16));
        card.setSelected(isSel);

        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(WebOSTheme.dp(this, 210), WebOSTheme.dp(this, 200));
        clp.rightMargin = WebOSTheme.dp(this, 14);
        card.setLayoutParams(clp);

        ImageView art = new ImageView(this);
        String artName = cp.isPs4() ? "devices/ps4.png" : "devices/ps5.png";
        Bitmap bmp = loadAssetBitmap(artName);
        if (bmp != null) art.setImageBitmap(bmp);
        art.setScaleType(ImageView.ScaleType.FIT_CENTER);
        card.addView(art, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 104), WebOSTheme.dp(this, 104)));

        TextView nameTv = new TextView(this);
        nameTv.setText(cp.name != null && !cp.name.isEmpty() ? cp.name : cp.hostName);
        nameTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        nameTv.setTypeface(Typeface.DEFAULT_BOLD);
        nameTv.setSingleLine(true);
        nameTv.setPadding(0, WebOSTheme.dp(this, 10), 0, WebOSTheme.dp(this, 2));
        card.addView(nameTv);

        String sub = cp.isLinked() ? (cp.localIp.isEmpty() ? cp.remoteIp : cp.localIp) : "Sin vincular";
        TextView subTv = new TextView(this);
        subTv.setText(sub);
        subTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        subTv.setSingleLine(true);
        card.addView(subTv);

        WebOSTheme.applyFocusTextToggle(card, nameTv, subTv, isSel);

        card.setOnFocusChangeListener((v, hasFocus) -> {
            WebOSTheme.applyFocusTextToggle(card, nameTv, subTv, hasFocus || cp.id.equals(selectedConsoleId));
            if (hasFocus) {
                selectedConsoleId = cp.id;
                cfg.activeProfileId = cp.id;
                updateConsoleDetailPanel();
            }
        });
        card.setOnClickListener(v -> {
            selectedConsoleId = cp.id;
            cfg.activeProfileId = cp.id;
            cfg.save();
            refreshConsolesUi();
            if (cp.isLinked()) {
                startStreamSmart(cp, cfg.connectionMode);
            } else {
                showConsoleEditorDialog(cp);
            }
        });
        return card;
    }

    private View makeAddConsoleCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setPadding(WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16), WebOSTheme.dp(this, 16));
        card.setFocusable(true);
        card.setClickable(true);
        card.setBackground(WebOSTheme.makeFrostSelector(this, 16));

        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(WebOSTheme.dp(this, 210), WebOSTheme.dp(this, 200));
        card.setLayoutParams(clp);

        ImageView art = new ImageView(this);
        Bitmap bmp = loadAssetBitmap("devices/unknown.png");
        if (bmp != null) art.setImageBitmap(bmp);
        art.setScaleType(ImageView.ScaleType.FIT_CENTER);
        card.addView(art, new LinearLayout.LayoutParams(WebOSTheme.dp(this, 90), WebOSTheme.dp(this, 90)));

        TextView t = new TextView(this);
        t.setText("+ Agregar Consola");
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setPadding(0, WebOSTheme.dp(this, 12), 0, 0);
        card.addView(t);

        TextView s = new TextView(this);
        s.setText("LAN o Remoto (PIN)");
        s.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        card.addView(s);

        WebOSTheme.applyFocusTextToggle(card, t, s, false);
        card.setOnFocusChangeListener((v, hasFocus) -> WebOSTheme.applyFocusTextToggle(card, t, s, hasFocus));
        card.setOnClickListener(v -> showAddConsoleMenu());
        return card;
    }

    private void updateConsoleDetailPanel() {
        ConfigStore.ConsoleProfile cp = null;
        for (ConfigStore.ConsoleProfile p : cfg.profiles) {
            if (p.id != null && p.id.equals(selectedConsoleId)) {
                cp = p;
                break;
            }
        }
        detailActionsRow.removeAllViews();

        String qualitySummary = cfg.getResolutionLabel() + " • " + cfg.fps + " fps • " +
            (cfg.isHdr() ? "H.265 HDR" : ("h264".equals(cfg.codec) ? "H.264" : "H.265")) +
            " • " + cfg.getUpscaleLabel();
        detailSummaryPill.setText(qualitySummary);

        if (cp == null) {
            detailTitle.setText("Sin consola seleccionada");
            detailSub.setText("Agrega o vincula tu PlayStation 5 / PlayStation 4 para comenzar.");
            detailActionsRow.addView(makeActionChip("+ Buscar en Red (DDP)", true, v -> discoverAndShowConsoles()));
            detailActionsRow.addView(makeActionChip("✎ Agregar Manual", false, v -> showConsoleEditorDialog(null)));
            return;
        }

        final ConfigStore.ConsoleProfile target = cp;
        detailTitle.setText((cp.name != null && !cp.name.isEmpty() ? cp.name : cp.hostName) + "  (" + cp.hostType + ")");
        String ips = "Local: " + (cp.localIp.isEmpty() ? "—" : cp.localIp) +
            "   |   Remota: " + (cp.remoteIp.isEmpty() ? "—" : cp.remoteIp) +
            "   |   Estado: " + (cp.isLinked() ? "Vinculada" : "Pendiente de PIN");
        detailSub.setText(ips);

        if (cp.isLinked()) {
            detailActionsRow.addView(makeActionChip("▶ Conectar (Auto)", true, v -> startStreamSmart(target, "auto")));
            if (!cp.localIp.isEmpty()) {
                detailActionsRow.addView(makeActionChip("🏠 Local", false, v -> startStreamSmart(target, "local")));
            }
            if (!cp.remoteIp.isEmpty()) {
                detailActionsRow.addView(makeActionChip("🌐 Remoto", false, v -> startStreamSmart(target, "remote")));
            }
            detailActionsRow.addView(makeActionChip("⚡ Despertar", false, v -> sendWakeupToConsole(target)));
        } else {
            detailActionsRow.addView(makeActionChip("🔗 Vincular con PIN", true, v -> showConsoleEditorDialog(target)));
        }
        detailActionsRow.addView(makeActionChip("⚙ Editar / Borrar", false, v -> showConsoleEditorDialog(target)));
    }

    private TextView makeActionChip(String label, boolean primary, View.OnClickListener onClick) {
        TextView btn = new TextView(this);
        btn.setText(label);
        btn.setTextColor(WebOSTheme.COL_TEXT);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setPadding(WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 11), WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 11));
        btn.setFocusable(true);
        btn.setClickable(true);
        btn.setBackground(primary ? WebOSTheme.makeAccentSelector(this, 12) : WebOSTheme.makeFrostSelector(this, 12));
        btn.setOnFocusChangeListener((v, hasFocus) -> {
            if (!primary) btn.setTextColor(hasFocus ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_TEXT);
            v.animate().scaleX(hasFocus ? 1.04f : 1.0f).scaleY(hasFocus ? 1.04f : 1.0f).setDuration(100).start();
        });
        btn.setOnClickListener(onClick);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = WebOSTheme.dp(this, 10);
        btn.setLayoutParams(lp);
        return btn;
    }

    private void focusInitialConsole() {
        if (consoleCardsRow != null && consoleCardsRow.getChildCount() > 0) {
            consoleCardsRow.getChildAt(0).requestFocus();
        }
    }

    // =========================================================================
    // SETTINGS PAGE (WebOS V2 5-tile structure)
    // =========================================================================

    private View buildSettingsPage() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);

        HorizontalScrollView catHsv = new HorizontalScrollView(this);
        catHsv.setHorizontalScrollBarEnabled(false);
        settingsCatRow = new LinearLayout(this);
        settingsCatRow.setOrientation(LinearLayout.HORIZONTAL);
        settingsCatRow.setPadding(0, WebOSTheme.dp(this, 4), 0, WebOSTheme.dp(this, 12));
        catHsv.addView(settingsCatRow);
        page.addView(catHsv);

        ScrollView rowsSv = new ScrollView(this);
        settingsRowsContainer = new LinearLayout(this);
        settingsRowsContainer.setOrientation(LinearLayout.VERTICAL);
        settingsRowsContainer.setPadding(0, WebOSTheme.dp(this, 4), 0, WebOSTheme.dp(this, 16));
        rowsSv.addView(settingsRowsContainer);
        page.addView(rowsSv, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        return page;
    }

    private void refreshSettingsUi() {
        String[] cats = { "Transmision", "Control", "Cuenta PSN y Remoto", "Registro", "Acerca de" };
        settingsCatRow.removeAllViews();
        for (int i = 0; i < cats.length; i++) {
            final int idx = i;
            boolean active = (i == activeSettingsCat);
            TextView tile = new TextView(this);
            tile.setText(cats[i]);
            tile.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
            tile.setTypeface(Typeface.DEFAULT_BOLD);
            tile.setTextColor(active ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_TEXT);
            tile.setPadding(WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 11), WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 11));
            tile.setFocusable(true);
            tile.setClickable(true);
            tile.setBackground(WebOSTheme.makeFrostSelector(this, 12));
            tile.setSelected(active);
            tile.setOnFocusChangeListener((v, f) -> {
                tile.setTextColor((f || idx == activeSettingsCat) ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_TEXT);
                if (f && activeSettingsCat != idx) {
                    activeSettingsCat = idx;
                    populateSettingsRows();
                }
            });
            tile.setOnClickListener(v -> {
                activeSettingsCat = idx;
                refreshSettingsUi();
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.rightMargin = WebOSTheme.dp(this, 10);
            settingsCatRow.addView(tile, lp);
        }
        populateSettingsRows();
    }

    private void populateSettingsRows() {
        settingsRowsContainer.removeAllViews();
        logConsoleView = null;

        if (activeSettingsCat == 0) {
            addSettingRow("Resolucion / Reescalado", "PS5 envia hasta 1080p; 2K/4K usan reescalado GPU", cfg.getResolutionLabel(), v -> {
                String[] opts = { "720p", "1080p", "1440p", "2160p" };
                cfg.resolution = nextInCycle(opts, cfg.resolution);
                cfg.save();
                populateSettingsRows();
                updateConsoleDetailPanel();
            });
            addSettingRow("Motor de Reescalado GPU", "CAS 5-tap mantiene nitidez 2K/4K a 60FPS; Directo evita shader en Sticks debiles", cfg.getUpscaleLabel(), v -> {
                String[] opts = { "auto", "cas_high", "cas_med", "direct" };
                cfg.upscaleMode = nextInCycle(opts, cfg.upscaleMode);
                cfg.save();
                populateSettingsRows();
                updateConsoleDetailPanel();
            });
            addSettingRow("Velocidad de Cuadros (FPS)", "60 fps para fluidez maxima; 30 fps para redes lentas", cfg.fps + " fps", v -> {
                cfg.fps = (cfg.fps >= 60) ? 30 : 60;
                cfg.save();
                populateSettingsRows();
                updateConsoleDetailPanel();
            });
            addSettingRow("Codec de Video", "H.265 recomendado para 1080p/2K/4K",
                cfg.isHdr() ? "H.265 HDR" : ("h264".equals(cfg.codec) ? "H.264" : "H.265 (HEVC)"), v -> {
                String[] opts = { "hevc", "hevc_hdr", "h264" };
                cfg.codec = nextInCycle(opts, cfg.codec);
                cfg.save();
                populateSettingsRows();
                updateConsoleDetailPanel();
            });
            addSettingRow("Bitrate de Streaming", "Mayor bitrate mejora nitidez del reescalado 2K/4K",
                cfg.bitrateKbps == 0 ? "Auto" : (cfg.bitrateKbps / 1000) + " Mbps", v -> {
                int[] vals = { 0, 8000, 12000, 15000, 20000 };
                int curIdx = 0;
                for (int i = 0; i < vals.length; i++) if (vals[i] == cfg.bitrateKbps) curIdx = i;
                cfg.bitrateKbps = vals[(curIdx + 1) % vals.length];
                cfg.save();
                populateSettingsRows();
            });
            addSettingRow("Modo de Conexion", "Auto intenta Local y pasa a IP Remota/Tailscale si falla",
                "auto".equals(cfg.connectionMode) ? "Auto (Local -> Remoto)" : ("remote".equals(cfg.connectionMode) ? "Solo Remoto" : "Solo Local"), v -> {
                String[] opts = { "auto", "local", "remote" };
                cfg.connectionMode = nextInCycle(opts, cfg.connectionMode);
                cfg.save();
                populateSettingsRows();
            });
            addSettingRow("Audio (Opus 48kHz)", "Audio estereo de baja latencia", cfg.audioEnabled ? "Activado" : "Desactivado", v -> {
                cfg.audioEnabled = !cfg.audioEnabled;
                cfg.save();
                populateSettingsRows();
            });
        } else if (activeSettingsCat == 1) {
            addSettingRow("Controles Tactiles en Pantalla", "Auto los oculta si usas TV o mando fisico",
                "auto".equals(cfg.touchControls) ? "Auto" : ("always".equals(cfg.touchControls) ? "Siempre visibles" : "Ocultos (TV)"), v -> {
                String[] opts = { "auto", "always", "never" };
                cfg.touchControls = nextInCycle(opts, cfg.touchControls);
                cfg.save();
                populateSettingsRows();
            });
            addSettingRow("Vibracion (Rumble)", "Retroalimentacion haptica al usar controles", cfg.rumble ? "Activado" : "Desactivado", v -> {
                cfg.rumble = !cfg.rumble;
                cfg.save();
                populateSettingsRows();
            });
            addSettingRow("Boton Confirmar en PS", "Intercambia Cruz y Circulo", cfg.circleConfirm ? "Circulo (◯)" : "Cruz (✕)", v -> {
                cfg.circleConfirm = !cfg.circleConfirm;
                cfg.save();
                populateSettingsRows();
            });
        } else if (activeSettingsCat == 2) {
            String psnState = cfg.psnAccountId.isEmpty() ? "No vinculada" :
                ((cfg.psnOnlineId.isEmpty() ? "Vinculada" : cfg.psnOnlineId) + " (" + cfg.psnAccountId + ")");
            addSettingRow("Cuenta PlayStation Network", "Necesaria para vincular consolas por PIN", psnState, v -> {
                PsnAuthDialog.show(this, new PsnAuthDialog.Callback() {
                    @Override
                    public void onSuccess(String accountIdB64, String onlineId) {
                        cfg.psnAccountId = accountIdB64;
                        cfg.psnOnlineId = onlineId;
                        cfg.save();
                        populateSettingsRows();
                        Toast.makeText(MainActivity.this, "PSN vinculada: " + onlineId, Toast.LENGTH_SHORT).show();
                    }
                    @Override
                    public void onError(String message) {
                        Toast.makeText(MainActivity.this, "Error PSN: " + message, Toast.LENGTH_LONG).show();
                    }
                });
            });
            addSettingRow("Ingresar Account ID Manual", "Formato Base64 de 8 bytes (opcional)", cfg.psnAccountId.isEmpty() ? "—" : cfg.psnAccountId, v -> {
                promptTextInput("Account ID (Base64)", cfg.psnAccountId, val -> {
                    cfg.psnAccountId = val.trim();
                    cfg.save();
                    populateSettingsRows();
                });
            });
            addSettingRow("Buscar Consolas en Red Local (DDP)", "Detecta PS5/PS4 encendidas o en reposo", "Escanear", v -> discoverAndShowConsoles());
        } else if (activeSettingsCat == 3) {
            addSettingRow("Guardar Log en Archivo", "Escribe diagnostico en drps5_v2.log", cfg.probeLog ? "Activado" : "Desactivado", v -> {
                cfg.probeLog = !cfg.probeLog;
                AppLogger.setFileEnabled(cfg.probeLog);
                cfg.save();
                populateSettingsRows();
            });
            addSettingRow("Limpiar Registro", "Borra las lineas actuales en memoria", "Limpiar", v -> {
                AppLogger.clear();
                if (logConsoleView != null) logConsoleView.setText("");
            });

            logConsoleView = new TextView(this);
            logConsoleView.setText(AppLogger.dumpText());
            logConsoleView.setTextColor(WebOSTheme.COL_SUBTLE);
            logConsoleView.setTypeface(Typeface.MONOSPACE);
            logConsoleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
            logConsoleView.setPadding(WebOSTheme.dp(this, 14), WebOSTheme.dp(this, 12), WebOSTheme.dp(this, 14), WebOSTheme.dp(this, 12));
            logConsoleView.setBackground(WebOSTheme.makeCardDrawable(this, WebOSTheme.COL_INSET, WebOSTheme.COL_LINE, 12, 1));
            settingsRowsContainer.addView(logConsoleView);
        } else {
            Display disp = getWindowManager().getDefaultDisplay();
            float hz = disp != null ? disp.getRefreshRate() : 60f;
            addSettingRow("DRPS5 Version", "Interfaz nativa Android (WebOS V2 style)", APP_VERSION + " (" + (Guard.IS_PERSONAL ? "Personal" : "Publica") + ")", null);
            addSettingRow("Dispositivo", Build.MANUFACTURER + " " + Build.MODEL, "Android " + Build.VERSION.RELEASE + " • " + Math.round(hz) + " Hz", null);
            addSettingRow("Red Local", "Direccion IPv4 actual", getLocalIpAddress(), null);
            addSettingRow("Pipeline de Video", "MediaCodec Hardware + OpenGL ES CAS 5-Tap", "2K / 4K @ 60FPS", null);
        }
    }

    private void addSettingRow(String title, String subtitle, String value, View.OnClickListener onClick) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 14), WebOSTheme.dp(this, 18), WebOSTheme.dp(this, 14));
        row.setFocusable(onClick != null);
        row.setClickable(onClick != null);
        row.setBackground(onClick != null
            ? WebOSTheme.makeFrostSelector(this, 12)
            : WebOSTheme.makeCardDrawable(this, 0x66070B16, WebOSTheme.COL_LINE, 12, 1));

        LinearLayout left = new LinearLayout(this);
        left.setOrientation(LinearLayout.VERTICAL);
        TextView t = new TextView(this);
        t.setText(title);
        t.setTextColor(WebOSTheme.COL_TEXT);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        left.addView(t);

        TextView s = new TextView(this);
        s.setText(subtitle);
        s.setTextColor(WebOSTheme.COL_MUTED);
        s.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        left.addView(s);
        row.addView(left, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        TextView valTv = new TextView(this);
        valTv.setText(value);
        valTv.setTextColor(WebOSTheme.COL_ACCENT_HI);
        valTv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        valTv.setTypeface(Typeface.DEFAULT_BOLD);
        row.addView(valTv);

        if (onClick != null) {
            row.setOnFocusChangeListener((v, f) -> {
                t.setTextColor(f ? WebOSTheme.COL_ON_FROST : WebOSTheme.COL_TEXT);
                s.setTextColor(f ? 0xFF334155 : WebOSTheme.COL_MUTED);
                valTv.setTextColor(f ? WebOSTheme.COL_ACCENT_DEEP : WebOSTheme.COL_ACCENT_HI);
            });
            row.setOnClickListener(onClick);
        }

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = WebOSTheme.dp(this, 8);
        settingsRowsContainer.addView(row, lp);
    }

    // =========================================================================
    // CONSOLE DISCOVERY, PAIRING & WAKEUP
    // =========================================================================

    private void showAddConsoleMenu() {
        String[] items = { "Buscar en red local (DDP)", "Agregar manualmente (IP Local / Remota)" };
        new AlertDialog.Builder(this)
            .setTitle("Agregar Consola")
            .setItems(items, (d, which) -> {
                if (which == 0) discoverAndShowConsoles();
                else showConsoleEditorDialog(null);
            })
            .show();
    }

    private void discoverAndShowConsoles() {
        Toast.makeText(this, "Buscando PS5/PS4 en la red...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            JSONArray found = PS5Protocol.discoverConsoles(3, null);
            uiHandler.post(() -> {
                if (found.length() == 0) {
                    Toast.makeText(this, "No se encontraron consolas por DDP. Usa Agregar Manual.", Toast.LENGTH_LONG).show();
                    return;
                }
                String[] labels = new String[found.length()];
                for (int i = 0; i < found.length(); i++) {
                    JSONObject o = found.optJSONObject(i);
                    labels[i] = o.optString("host_name", "PS5") + " (" + o.optString("host_ip") + ") - " + o.optString("status");
                }
                new AlertDialog.Builder(this)
                    .setTitle("Consolas detectadas")
                    .setItems(labels, (d, which) -> {
                        JSONObject o = found.optJSONObject(which);
                        ConfigStore.ConsoleProfile cp = new ConfigStore.ConsoleProfile();
                        cp.id = "prof_" + o.optString("host_id", String.valueOf(System.currentTimeMillis()));
                        cp.hostId = o.optString("host_id", "");
                        cp.hostName = o.optString("host_name", "PS5");
                        cp.name = cp.hostName;
                        cp.hostType = o.optString("host_type", "PS5");
                        cp.localIp = o.optString("host_ip", "");
                        cp.status = o.optString("status", "Detectada");
                        showConsoleEditorDialog(cp);
                    })
                    .show();
            });
        }, "DRPS5-Discover").start();
    }

    private void showConsoleEditorDialog(ConfigStore.ConsoleProfile existing) {
        final ConfigStore.ConsoleProfile cp = existing != null ? existing : new ConfigStore.ConsoleProfile();
        if (cp.id == null || cp.id.isEmpty()) cp.id = "prof_" + System.currentTimeMillis();

        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(WebOSTheme.dp(this, 20), WebOSTheme.dp(this, 12), WebOSTheme.dp(this, 20), WebOSTheme.dp(this, 8));

        final EditText etName = addFormInput(form, "Nombre", cp.name != null ? cp.name : "Mi PS5", InputType.TYPE_CLASS_TEXT);
        final EditText etLocal = addFormInput(form, "IP Local (LAN)", cp.localIp != null ? cp.localIp : "", InputType.TYPE_CLASS_TEXT);
        final EditText etRemote = addFormInput(form, "IP Remota (Tailscale / Publica)", cp.remoteIp != null ? cp.remoteIp : "", InputType.TYPE_CLASS_TEXT);
        final EditText etPin = addFormInput(form, "PIN de vinculacion (8 digitos, solo si vas a vincular)", "", InputType.TYPE_CLASS_NUMBER);

        AlertDialog.Builder b = new AlertDialog.Builder(this)
            .setTitle(existing != null && existing.isLinked() ? "Editar Consola" : "Vincular Consola")
            .setView(form)
            .setPositiveButton("Guardar / Vincular", (d, w) -> {
                cp.name = etName.getText().toString().trim();
                if (cp.name.isEmpty()) cp.name = "PS5";
                cp.hostName = cp.name;
                cp.localIp = etLocal.getText().toString().trim();
                cp.remoteIp = etRemote.getText().toString().trim();
                String pin = etPin.getText().toString().trim();
                if (!pin.isEmpty()) {
                    String acc = (cp.accountId != null && !cp.accountId.isEmpty()) ? cp.accountId : cfg.psnAccountId;
                    if (acc == null || acc.isEmpty()) {
                        Toast.makeText(this, "Primero vincula tu cuenta PSN en Ajustes", Toast.LENGTH_LONG).show();
                        cfg.upsertProfile(cp);
                        refreshConsolesUi();
                        return;
                    }
                    cp.accountId = acc;
                    String targetIp = !cp.localIp.isEmpty() ? cp.localIp : cp.remoteIp;
                    runPinPairing(cp, targetIp, pin);
                } else {
                    cfg.upsertProfile(cp);
                    selectedConsoleId = cp.id;
                    refreshConsolesUi();
                }
            })
            .setNegativeButton("Cancelar", null);

        if (existing != null) {
            b.setNeutralButton("Eliminar", (d, w) -> {
                cfg.removeProfile(existing.id);
                selectedConsoleId = "";
                refreshConsolesUi();
            });
        }
        b.show();
    }

    private void runPinPairing(ConfigStore.ConsoleProfile cp, String targetIp, String pin) {
        Toast.makeText(this, "Vinculando con " + targetIp + "...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                JSONObject res = PS5Protocol.pairConsole(targetIp, pin, cp.accountId, cp.isPs4());
                uiHandler.post(() -> {
                    if (res.optBoolean("success", false)) {
                        cp.registKey = res.optString("regist_key", "");
                        cp.rpKey = res.optString("rp_key", "");
                        cp.hostName = res.optString("host_name", cp.name);
                        cp.hostId = res.optString("host_id", cp.hostId);
                        cp.status = "Vinculada";
                        cfg.upsertProfile(cp);
                        selectedConsoleId = cp.id;
                        refreshConsolesUi();
                        Toast.makeText(this, "Consola vinculada correctamente", Toast.LENGTH_LONG).show();
                    } else {
                        Toast.makeText(this, "Fallo vinculacion: " + res.optString("error", "Error"), Toast.LENGTH_LONG).show();
                    }
                });
            } catch (Throwable e) {
                uiHandler.post(() -> Toast.makeText(this, "Error vinculando: " + e.getMessage(), Toast.LENGTH_LONG).show());
            }
        }, "DRPS5-Register").start();
    }

    private void sendWakeupToConsole(ConfigStore.ConsoleProfile cp) {
        if (cp.registKey == null || cp.registKey.isEmpty()) {
            Toast.makeText(this, "Consola sin regist_key", Toast.LENGTH_SHORT).show();
            return;
        }
        Toast.makeText(this, "Enviando senal de encendido...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            boolean ok = false;
            if (!cp.localIp.isEmpty()) {
                ok |= PS5Protocol.wakeupPs5(cp.localIp, cp.registKey);
            }
            if (!cp.remoteIp.isEmpty()) {
                ok |= PS5Protocol.wakeupPs5(cp.remoteIp, cp.registKey);
            }
            final boolean sent = ok;
            uiHandler.post(() -> Toast.makeText(this, sent ? "Senal Wakeup enviada" : "No se pudo enviar Wakeup", Toast.LENGTH_SHORT).show());
        }, "DRPS5-Wakeup").start();
    }

    // =========================================================================
    // STREAMING & 2K / 4K 60FPS GPU UPSCALING
    // =========================================================================

    private void buildStreamUi() {
        streamContainer = new FrameLayout(this);
        streamContainer.setBackgroundColor(Color.BLACK);
        streamContainer.setVisibility(View.GONE);

        touchOverlay = new TouchGamepadOverlayView(this);
        touchOverlay.setInputTarget(new TouchGamepadOverlayView.InputTarget() {
            @Override
            public void sendButtonEvent(int code, boolean pressed) {
                if (streamClient != null) streamClient.sendButtonEvent(code, pressed);
            }
            @Override
            public void setSticks(short lx, short ly, short rx, short ry) {
                if (streamClient != null) streamClient.setSticks(lx, ly, rx, ry);
            }
            @Override
            public void onMenuRequested() {
                toggleStreamOverlayMenu();
            }
        });
        touchOverlay.setVisibility(View.GONE);

        streamHudPill = WebOSTheme.makePill(this, "Conectando...", 0xAA070B16, WebOSTheme.COL_TEXT);
        streamHudPill.setClickable(true);
        streamHudPill.setOnClickListener(v -> toggleStreamOverlayMenu());
        FrameLayout.LayoutParams hlp = new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.END);
        hlp.topMargin = WebOSTheme.dp(this, 12);
        hlp.rightMargin = WebOSTheme.dp(this, 14);

        streamOverlayMenu = new StreamOverlayMenu(this, cfg, new StreamOverlayMenu.Listener() {
            @Override
            public void onResumeGame() {}
            @Override
            public void onCycleUpscale() {
                String[] opts = { "auto", "cas_high", "cas_med", "direct" };
                cfg.upscaleMode = nextInCycle(opts, cfg.upscaleMode);
                cfg.save();
                if (upscaleRenderer != null && !"direct".equals(cfg.upscaleMode)) {
                    upscaleRenderer.configure(cfg.resolution, cfg.upscaleMode);
                }
                updateStreamOverlayInfo();
            }
            @Override
            public void onToggleTouchControls() {
                boolean show = touchOverlay.getVisibility() != View.VISIBLE;
                touchOverlay.setVisibility(show ? View.VISIBLE : View.GONE);
                updateStreamOverlayInfo();
            }
            @Override
            public void onSendPsButton() {
                if (streamClient != null) {
                    streamClient.sendButtonEvent(0x8E, true);
                    uiHandler.postDelayed(() -> {
                        if (streamClient != null) streamClient.sendButtonEvent(0x8E, false);
                    }, 120);
                }
            }
            @Override
            public void onDisconnect() {
                stopStreamSession();
            }
        });

        streamContainer.addView(touchOverlay, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        streamContainer.addView(streamHudPill, hlp);
        streamContainer.addView(streamOverlayMenu, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        rootContainer.addView(streamContainer, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void startStreamSmart(ConfigStore.ConsoleProfile cp, String mode) {
        if (streaming) return;
        Toast.makeText(this, "Resolviendo conexion (" + mode + ")...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String chosenIp = cp.localIp;
            if ("remote".equals(mode)) {
                chosenIp = !cp.remoteIp.isEmpty() ? cp.remoteIp : cp.localIp;
            } else if ("local".equals(mode)) {
                chosenIp = !cp.localIp.isEmpty() ? cp.localIp : cp.remoteIp;
            } else {
                // Auto: fast TCP probe on port 9295 local, fallback to remote_ip if unreachable
                if (!cp.localIp.isEmpty() && isTcpPortReachable(cp.localIp, 9295, 1100)) {
                    chosenIp = cp.localIp;
                    AppLogger.i("NET", "Auto-ruta: LAN alcanzable (" + chosenIp + ")");
                } else if (!cp.remoteIp.isEmpty()) {
                    chosenIp = cp.remoteIp;
                    AppLogger.i("NET", "Auto-ruta: usando IP Remota (" + chosenIp + ")");
                }
            }
            final String targetIp = chosenIp;
            uiHandler.post(() -> {
                if (targetIp == null || targetIp.isEmpty()) {
                    Toast.makeText(this, "Configura una IP Local o Remota primero", Toast.LENGTH_LONG).show();
                    return;
                }
                launchStreamView(cp, targetIp);
            });
        }, "DRPS5-RouteProbe").start();
    }

    private void launchStreamView(ConfigStore.ConsoleProfile cp, String targetIp) {
        streaming = true;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        homeRoot.setVisibility(View.GONE);
        streamContainer.setVisibility(View.VISIBLE);
        applyImmersiveFullscreen();

        boolean showTouch = "always".equals(cfg.touchControls) ||
            ("auto".equals(cfg.touchControls) && !hasPhysicalGamepad && hasTouchScreen());
        touchOverlay.setVisibility(showTouch ? View.VISIBLE : View.GONE);
        streamHudPill.setText("Conectando a " + targetIp + "...");
        streamOverlayMenu.hideMenu();

        // Remove previous video view if any
        if (upscaleRenderer != null) {
            streamContainer.removeView(upscaleRenderer);
            upscaleRenderer.releaseSurface();
            upscaleRenderer = null;
        }
        if (directSurfaceView != null) {
            streamContainer.removeView(directSurfaceView);
            directSurfaceView = null;
        }

        if ("direct".equals(cfg.upscaleMode)) {
            directSurfaceView = new SurfaceView(this);
            streamContainer.addView(directSurfaceView, 0, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            directSurfaceView.getHolder().addCallback(new SurfaceHolder.Callback() {
                @Override
                public void surfaceCreated(SurfaceHolder holder) {
                    startClientOnSurface(cp, targetIp, holder.getSurface());
                }
                @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}
                @Override public void surfaceDestroyed(SurfaceHolder holder) {}
            });
        } else {
            upscaleRenderer = new UpscaleRenderer(this, surface -> {
                if (streaming) startClientOnSurface(cp, targetIp, surface);
            });
            upscaleRenderer.configure(cfg.resolution, cfg.upscaleMode);
            streamContainer.addView(upscaleRenderer, 0, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
    }

    private void startClientOnSurface(ConfigStore.ConsoleProfile cp, String targetIp, Surface surface) {
        if (streamClient != null) {
            streamClient.stop();
        }
        streamClient = new PS5StreamClient(
            targetIp,
            cp.registKey,
            cp.rpKey,
            cfg.resolution,
            cfg.fps,
            cfg.getCodecBase(),
            cfg.isHdr(),
            cfg.audioEnabled,
            cp.isPs4(),
            surface,
            new PS5StreamClient.StreamListener() {
                @Override
                public void onStatus(String message) {
                    uiHandler.post(() -> streamHudPill.setText(message));
                }
                @Override
                public void onConnected() {
                    AppLogger.i("STREAM", "Sesion conectada con " + targetIp);
                }
                @Override
                public void onError(String error) {
                    AppLogger.e("STREAM", "Error de sesion: " + error);
                    uiHandler.post(() -> {
                        Toast.makeText(MainActivity.this, error, Toast.LENGTH_LONG).show();
                        stopStreamSession();
                    });
                }
                @Override
                public void onStats(float fps, int width, int height, String codec, boolean hdr, int rxPackets, int lostPackets) {
                    uiHandler.post(() -> {
                        String gpuInfo = "";
                        if (upscaleRenderer != null) {
                            gpuInfo = " • GPU " + String.format(Locale.US, "%.1f", upscaleRenderer.getAvgGpuMs()) + "ms";
                        }
                        String txt = String.format(Locale.US, "%.0f fps • %s%s  ⚙",
                            fps, cfg.getResolutionLabel(), gpuInfo);
                        streamHudPill.setText(txt);
                        if (streamOverlayMenu.isMenuOpen()) {
                            updateStreamOverlayInfo();
                        }
                    });
                }
            }
        );
        streamClient.setBitrateKbps(cfg.bitrateKbps);
        streamClient.start();
    }

    private void stopStreamSession() {
        streaming = false;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (streamClient != null) {
            streamClient.stop();
            streamClient = null;
        }
        if (upscaleRenderer != null) {
            upscaleRenderer.releaseSurface();
            streamContainer.removeView(upscaleRenderer);
            upscaleRenderer = null;
        }
        if (directSurfaceView != null) {
            streamContainer.removeView(directSurfaceView);
            directSurfaceView = null;
        }
        streamOverlayMenu.hideMenu();
        streamContainer.setVisibility(View.GONE);
        homeRoot.setVisibility(View.VISIBLE);
        focusInitialConsole();
    }

    private void toggleStreamOverlayMenu() {
        if (!streaming) return;
        if (streamOverlayMenu.isMenuOpen()) {
            streamOverlayMenu.hideMenu();
        } else {
            updateStreamOverlayInfo();
            streamOverlayMenu.showMenu();
        }
    }

    private void updateStreamOverlayInfo() {
        String gpu = upscaleRenderer != null
            ? String.format(Locale.US, "GPU %.1f ms", upscaleRenderer.getAvgGpuMs())
            : "Directo Zero-Copy";
        streamOverlayMenu.updateStats(
            cfg.getResolutionLabel() + " • " + cfg.fps + " fps",
            gpu,
            cfg.getUpscaleLabel(),
            touchOverlay.getVisibility() == View.VISIBLE
        );
    }

    // =========================================================================
    // INPUT: GAMEPAD, TV REMOTE & TOUCH
    // =========================================================================

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        int code = event.getKeyCode();
        boolean down = event.getAction() == KeyEvent.ACTION_DOWN;

        if (!streaming) {
            if (down && code == KeyEvent.KEYCODE_BUTTON_L1) {
                switchTab(0);
                return true;
            }
            if (down && code == KeyEvent.KEYCODE_BUTTON_R1) {
                switchTab(1);
                return true;
            }
            return super.dispatchKeyEvent(event);
        }

        if (streamOverlayMenu.isMenuOpen()) {
            if (down && (code == KeyEvent.KEYCODE_BACK || code == KeyEvent.KEYCODE_BUTTON_B)) {
                streamOverlayMenu.hideMenu();
                return true;
            }
            return super.dispatchKeyEvent(event);
        }

        if (code == KeyEvent.KEYCODE_BUTTON_SELECT) gpShareDown = down;
        if (code == KeyEvent.KEYCODE_BUTTON_START) gpOptionsDown = down;

        if (down && ((gpShareDown && gpOptionsDown) || code == KeyEvent.KEYCODE_MENU || code == KeyEvent.KEYCODE_BUTTON_MODE)) {
            toggleStreamOverlayMenu();
            return true;
        }

        if (down && code == KeyEvent.KEYCODE_BACK) {
            long now = SystemClock.uptimeMillis();
            if (now - lastBackPressMs < 1500) {
                toggleStreamOverlayMenu();
            } else {
                lastBackPressMs = now;
                Toast.makeText(this, "Pulsa Atras de nuevo para abrir el menu", Toast.LENGTH_SHORT).show();
            }
            return true;
        }

        int psBtn = mapKeyToPsButton(code);
        if (psBtn != -1 && streamClient != null) {
            if (event.getRepeatCount() == 0) {
                streamClient.sendButtonEvent(psBtn, down);
            }
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent ev) {
        if (streaming && !streamOverlayMenu.isMenuOpen() && streamClient != null &&
            (ev.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK &&
            ev.getAction() == MotionEvent.ACTION_MOVE) {
            float lx = applyDeadzone(ev.getAxisValue(MotionEvent.AXIS_X));
            float ly = applyDeadzone(ev.getAxisValue(MotionEvent.AXIS_Y));
            float rx = applyDeadzone(ev.getAxisValue(MotionEvent.AXIS_Z));
            float ry = applyDeadzone(ev.getAxisValue(MotionEvent.AXIS_RZ));
            streamClient.setSticks(
                (short) (lx * 32767f), (short) (ly * 32767f),
                (short) (rx * 32767f), (short) (ry * 32767f)
            );
            float lt = ev.getAxisValue(MotionEvent.AXIS_LTRIGGER);
            float rt = ev.getAxisValue(MotionEvent.AXIS_RTRIGGER);
            streamClient.sendButtonEvent(0x86, lt > 0.25f);
            streamClient.sendButtonEvent(0x87, rt > 0.25f);
            return true;
        }
        return super.dispatchGenericMotionEvent(ev);
    }

    private int mapKeyToPsButton(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:       return 0x80;
            case KeyEvent.KEYCODE_DPAD_DOWN:     return 0x81;
            case KeyEvent.KEYCODE_DPAD_LEFT:     return 0x82;
            case KeyEvent.KEYCODE_DPAD_RIGHT:    return 0x83;
            case KeyEvent.KEYCODE_BUTTON_L1:     return 0x84;
            case KeyEvent.KEYCODE_BUTTON_R1:     return 0x85;
            case KeyEvent.KEYCODE_BUTTON_L2:     return 0x86;
            case KeyEvent.KEYCODE_BUTTON_R2:     return 0x87;
            case KeyEvent.KEYCODE_BUTTON_A:
            case KeyEvent.KEYCODE_DPAD_CENTER:   return cfg.circleConfirm ? 0x89 : 0x88;
            case KeyEvent.KEYCODE_BUTTON_B:      return cfg.circleConfirm ? 0x88 : 0x89;
            case KeyEvent.KEYCODE_BUTTON_X:      return 0x8A;
            case KeyEvent.KEYCODE_BUTTON_Y:      return 0x8B;
            case KeyEvent.KEYCODE_BUTTON_START:  return 0x8C;
            case KeyEvent.KEYCODE_BUTTON_SELECT: return 0x8D;
            case KeyEvent.KEYCODE_BUTTON_MODE:   return 0x8E;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return 0x8F;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return 0x90;
            default: return -1;
        }
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    private static float applyDeadzone(float v) {
        return Math.abs(v) < 0.12f ? 0f : v;
    }

    private static String nextInCycle(String[] opts, String cur) {
        for (int i = 0; i < opts.length; i++) {
            if (opts[i].equals(cur)) return opts[(i + 1) % opts.length];
        }
        return opts[0];
    }

    private static boolean isTcpPortReachable(String ip, int port, int timeoutMs) {
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(ip, port), timeoutMs);
            return true;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private boolean hasTouchScreen() {
        return getPackageManager().hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN);
    }

    private boolean detectPhysicalGamepad() {
        int[] ids = InputDevice.getDeviceIds();
        for (int id : ids) {
            InputDevice d = InputDevice.getDevice(id);
            if (d == null) continue;
            int src = d.getSources();
            if ((src & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD ||
                (src & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
                return true;
            }
        }
        return false;
    }

    private void registerInputListener() {
        InputManager im = (InputManager) getSystemService(Context.INPUT_SERVICE);
        if (im == null) return;
        im.registerInputDeviceListener(new InputManager.InputDeviceListener() {
            @Override public void onInputDeviceAdded(int id) { updatePadBadge(); }
            @Override public void onInputDeviceRemoved(int id) { updatePadBadge(); }
            @Override public void onInputDeviceChanged(int id) { updatePadBadge(); }
        }, uiHandler);
    }

    private void updatePadBadge() {
        hasPhysicalGamepad = detectPhysicalGamepad();
        if (badgePad != null) {
            badgePad.setText(hasPhysicalGamepad ? "Mando OK" : "Tactil / TV");
        }
    }

    private Bitmap loadAssetBitmap(String path) {
        try (InputStream is = getAssets().open(path)) {
            return BitmapFactory.decodeStream(is);
        } catch (Throwable ignored) {
            return null;
        }
    }

    private static String getLocalIpAddress() {
        try {
            Enumeration<NetworkInterface> ifs = NetworkInterface.getNetworkInterfaces();
            while (ifs != null && ifs.hasMoreElements()) {
                NetworkInterface nif = ifs.nextElement();
                if (!nif.isUp() || nif.isLoopback()) continue;
                Enumeration<InetAddress> addrs = nif.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (a instanceof Inet4Address) {
                        String ip = a.getHostAddress();
                        if (ip != null && !ip.startsWith("127.")) return ip;
                    }
                }
            }
        } catch (Throwable ignored) {}
        return "Sin red";
    }

    private EditText addFormInput(LinearLayout parent, String hint, String value, int inputType) {
        TextView lbl = new TextView(this);
        lbl.setText(hint);
        lbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        lbl.setPadding(0, WebOSTheme.dp(this, 8), 0, WebOSTheme.dp(this, 2));
        parent.addView(lbl);

        EditText et = new EditText(this);
        et.setText(value);
        et.setInputType(inputType);
        parent.addView(et);
        return et;
    }

    private void promptTextInput(String title, String initial, java.util.function.Consumer<String> onOk) {
        EditText et = new EditText(this);
        et.setText(initial);
        new AlertDialog.Builder(this)
            .setTitle(title)
            .setView(et)
            .setPositiveButton("Aceptar", (d, w) -> onOk.accept(et.getText().toString()))
            .setNegativeButton("Cancelar", null)
            .show();
    }
}
