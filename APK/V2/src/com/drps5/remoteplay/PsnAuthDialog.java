package com.drps5.remoteplay;

import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Color;
import android.net.Uri;
import android.util.Base64;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/**
 * On-demand PSN OAuth login dialog (instantiates WebView only while linking PSN,
 * keeping zero Chromium RAM overhead during normal TV/Stick/Phone streaming).
 */
public final class PsnAuthDialog {
    public interface Callback {
        void onSuccess(String accountIdB64, String onlineId);
        void onError(String message);
    }

    private static final String CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891";
    private static final String REDIRECT_URI = "com.playstation.remoteplay://redirect";
    private static final String AUTH_HEADER = "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A=";

    private PsnAuthDialog() {}

    public static void show(Context ctx, Callback cb) {
        LinearLayout root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(WebOSTheme.COL_BG_BOTTOM);

        TextView header = new TextView(ctx);
        header.setText("Iniciar sesion en PlayStation Network");
        header.setTextColor(WebOSTheme.COL_TEXT);
        header.setTextSize(16);
        header.setPadding(WebOSTheme.dp(ctx, 16), WebOSTheme.dp(ctx, 12), WebOSTheme.dp(ctx, 16), WebOSTheme.dp(ctx, 8));
        root.addView(header);

        WebView web = new WebView(ctx);
        LinearLayout.LayoutParams wlp = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, WebOSTheme.dp(ctx, 420));
        web.setLayoutParams(wlp);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        root.addView(web);

        AlertDialog dlg = new AlertDialog.Builder(ctx)
            .setView(root)
            .setNegativeButton("Cancelar", (d, w) -> {
                web.destroy();
                d.dismiss();
            })
            .create();

        web.setWebViewClient(new WebViewClient() {
            private boolean handled = false;

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl().toString());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url);
            }

            private boolean handleUrl(String url) {
                if (handled || url == null) return false;
                if (url.startsWith(REDIRECT_URI)) {
                    handled = true;
                    Uri uri = Uri.parse(url);
                    String code = uri.getQueryParameter("code");
                    if (code != null && !code.isEmpty()) {
                        header.setText("Obteniendo Account ID de PSN...");
                        exchangeCode(code, dlg, web, cb);
                    } else {
                        dlg.dismiss();
                        web.destroy();
                        if (cb != null) cb.onError("No se recibio codigo de autorizacion PSN");
                    }
                    return true;
                }
                return false;
            }
        });

        String authUrl = "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
            + "?access_type=offline"
            + "&client_id=" + CLIENT_ID
            + "&redirect_uri=" + Uri.encode(REDIRECT_URI)
            + "&response_type=code"
            + "&scope=" + Uri.encode("psn:clientapp user:account.get kamaji:get_account_hash oauth:manage_user_auth_sessions");

        dlg.show();
        web.loadUrl(authUrl);
    }

    private static void exchangeCode(String code, AlertDialog dlg, WebView web, Callback cb) {
        new Thread(() -> {
            try {
                URL url = new URL("https://ca.account.sony.com/api/authz/v3/oauth/token");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Authorization", AUTH_HEADER);
                conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                conn.setDoOutput(true);
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(10000);

                String body = "grant_type=authorization_code"
                    + "&code=" + Uri.encode(code)
                    + "&redirect_uri=" + Uri.encode(REDIRECT_URI)
                    + "&token_format=jwt";
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(body.getBytes(StandardCharsets.UTF_8));
                }

                int rc = conn.getResponseCode();
                String resp = readStream(rc >= 200 && rc < 300 ? conn.getInputStream() : conn.getErrorStream());
                if (rc < 200 || rc >= 300) {
                    throw new RuntimeException("HTTP " + rc + ": " + resp);
                }
                JSONObject tok = new JSONObject(resp);
                String accessToken = tok.getString("access_token");

                // Fetch user profile to get accountId + onlineId
                URL profUrl = new URL("https://us-prof.np.community.playstation.net/userProfile/v1/users/me/profile2?fields=npId,onlineId,accountId");
                HttpURLConnection pConn = (HttpURLConnection) profUrl.openConnection();
                pConn.setRequestProperty("Authorization", "Bearer " + accessToken);
                pConn.setConnectTimeout(10000);
                pConn.setReadTimeout(10000);

                int prc = pConn.getResponseCode();
                String profResp = readStream(prc >= 200 && prc < 300 ? pConn.getInputStream() : pConn.getErrorStream());
                if (prc < 200 || prc >= 300) {
                    throw new RuntimeException("Profile HTTP " + prc + ": " + profResp);
                }
                JSONObject profRoot = new JSONObject(profResp);
                JSONObject profile = profRoot.getJSONObject("profile");
                String accountIdDec = profile.getString("accountId");
                String onlineId = profile.optString("onlineId", "PSN User");

                long uid = Long.parseUnsignedLong(accountIdDec);
                byte[] le = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(uid).array();
                String accountIdB64 = Base64.encodeToString(le, Base64.NO_WRAP);

                AppLogger.i("PSN", "Cuenta PSN vinculada: " + onlineId + " (id=" + accountIdB64 + ")");
                web.post(() -> {
                    dlg.dismiss();
                    web.destroy();
                    if (cb != null) cb.onSuccess(accountIdB64, onlineId);
                });
            } catch (Throwable e) {
                AppLogger.e("PSN", "Error OAuth PSN: " + e.getMessage());
                web.post(() -> {
                    dlg.dismiss();
                    web.destroy();
                    if (cb != null) cb.onError(e.getMessage());
                });
            }
        }, "DRPS5-PSN-Auth").start();
    }

    private static String readStream(InputStream is) throws Exception {
        if (is == null) return "";
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = is.read(buf)) != -1) {
            bos.write(buf, 0, n);
        }
        return bos.toString("UTF-8");
    }
}
