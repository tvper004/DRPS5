package com.drps5.remoteplay;

import android.content.Context;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

public final class ConfigStore {
    public static final class ConsoleProfile {
        public String id;
        public String name;
        public String hostId;
        public String hostName;
        public String hostType; // "PS5" or "PS4"
        public String localIp;
        public String remoteIp;
        public String connectionMode; // "auto", "local", "remote"
        public String registKey;
        public String rpKey;
        public String accountId;
        public String status;
        public String lastWakeAt;

        public boolean isLinked() {
            return registKey != null && !registKey.isEmpty() && rpKey != null && !rpKey.isEmpty();
        }

        public boolean isPs4() {
            return "PS4".equalsIgnoreCase(hostType);
        }

        public JSONObject toJson() {
            JSONObject o = new JSONObject();
            try {
                o.put("id", id != null ? id : "");
                o.put("name", name != null ? name : "PS5");
                o.put("host_id", hostId != null ? hostId : "");
                o.put("host_name", hostName != null ? hostName : "PS5");
                o.put("host_type", hostType != null ? hostType : "PS5");
                o.put("local_ip", localIp != null ? localIp : "");
                o.put("remote_ip", remoteIp != null ? remoteIp : "");
                o.put("connection_mode", connectionMode != null ? connectionMode : "auto");
                o.put("regist_key", registKey != null ? registKey : "");
                o.put("rp_key", rpKey != null ? rpKey : "");
                o.put("account_id", accountId != null ? accountId : "");
                o.put("status", status != null ? status : (isLinked() ? "Vinculada" : "Pendiente"));
            } catch (Throwable ignored) {}
            return o;
        }

        public static ConsoleProfile fromJson(String fallbackId, JSONObject o) {
            ConsoleProfile p = new ConsoleProfile();
            p.id = o.optString("id", fallbackId);
            p.name = o.optString("name", o.optString("host_name", "PS5"));
            p.hostId = o.optString("host_id", "");
            p.hostName = o.optString("host_name", p.name);
            p.hostType = o.optString("host_type", "PS5");
            p.localIp = o.optString("local_ip", o.optString("host_ip", ""));
            p.remoteIp = o.optString("remote_ip", "");
            p.connectionMode = o.optString("connection_mode", "auto");
            p.registKey = o.optString("regist_key", "");
            p.rpKey = o.optString("rp_key", "");
            p.accountId = o.optString("account_id", "");
            p.status = o.optString("status", p.isLinked() ? "Vinculada" : "Pendiente");
            return p;
        }
    }

    private final File configFile;
    public String resolution = "1080p";      // "720p", "1080p", "1440p" (2K), "2160p" (4K)
    public String upscaleMode = "auto";      // "auto", "cas_high", "cas_med", "direct"
    public int fps = 60;                     // 30 or 60
    public String codec = "hevc";            // "hevc", "hevc_hdr", "h264"
    public int bitrateKbps = 0;              // 0 = Auto, 8000, 12000, 15000, 20000
    public String connectionMode = "auto";   // "auto", "local", "remote"
    public boolean audioEnabled = true;
    public boolean rumble = true;
    public boolean circleConfirm = false;
    public String touchControls = "auto";    // "auto", "always", "never"
    public boolean probeLog = false;
    public String psnAccountId = "";
    public String psnOnlineId = "";
    public String activeProfileId = "";
    public final List<ConsoleProfile> profiles = new ArrayList<>();

    public ConfigStore(Context ctx) {
        this.configFile = new File(ctx.getFilesDir(), "drps5_v2_config.json");
        load();
    }

    public void load() {
        profiles.clear();
        String raw = readText(configFile);
        if (raw == null || raw.trim().isEmpty()) {
            seedFromGuard();
            save();
            return;
        }
        try {
            JSONObject root = new JSONObject(raw);
            resolution = root.optString("resolution", "1080p");
            upscaleMode = root.optString("upscale_mode", "auto");
            fps = root.optInt("fps", 60);
            codec = root.optString("codec", "hevc");
            if (root.optBoolean("hdr", false) && "hevc".equals(codec)) {
                codec = "hevc_hdr";
            }
            bitrateKbps = root.optInt("bitrate_kbps", 0);
            connectionMode = root.optString("connection_mode", "auto");
            audioEnabled = root.optBoolean("audio_enabled", true);
            rumble = root.optBoolean("rumble", true);
            circleConfirm = root.optBoolean("circle_confirm", false);
            touchControls = root.optString("touch_controls", "auto");
            probeLog = root.optBoolean("probe_log", false);
            psnAccountId = root.optString("psn_account_id", "");
            psnOnlineId = root.optString("psn_online_id", "");
            activeProfileId = root.optString("active_profile_id", "");

            JSONArray arr = root.optJSONArray("profiles_list");
            if (arr != null) {
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject po = arr.optJSONObject(i);
                    if (po != null) {
                        profiles.add(ConsoleProfile.fromJson("prof_" + i, po));
                    }
                }
            }
        } catch (Throwable e) {
            AppLogger.w("CONFIG", "Error leyendo config, restaurando seed: " + e.getMessage());
            seedFromGuard();
        }
    }

    private void seedFromGuard() {
        profiles.clear();
        try {
            JSONObject seed = new JSONObject(Guard.getSeedConfigJson());
            resolution = seed.optString("resolution", Guard.IS_PERSONAL ? "1080p" : "1080p");
            fps = seed.optInt("fps", 60);
            String c = seed.optString("codec", "hevc");
            boolean hdr = seed.optBoolean("hdr", false);
            codec = hdr ? "hevc_hdr" : c;
            audioEnabled = seed.optBoolean("audio_enabled", true);
            circleConfirm = seed.optBoolean("circle_confirm", false);
            activeProfileId = seed.optString("active_profile_id", "");

            JSONObject profMap = seed.optJSONObject("profiles");
            if (profMap != null) {
                Iterator<String> it = profMap.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    JSONObject po = profMap.optJSONObject(k);
                    if (po != null) {
                        ConsoleProfile cp = ConsoleProfile.fromJson(k, po);
                        if (cp.isLinked() || !cp.localIp.isEmpty() || !cp.remoteIp.isEmpty()) {
                            cp.connectionMode = "auto";
                            profiles.add(cp);
                            if (psnAccountId.isEmpty() && cp.accountId != null && !cp.accountId.isEmpty()) {
                                psnAccountId = cp.accountId;
                            }
                        }
                    }
                }
            }
        } catch (Throwable e) {
            AppLogger.w("CONFIG", "Error leyendo Guard seed: " + e.getMessage());
        }
    }

    public void save() {
        try {
            JSONObject root = new JSONObject();
            root.put("version", "2.0.0");
            root.put("resolution", resolution);
            root.put("upscale_mode", upscaleMode);
            root.put("fps", fps);
            root.put("codec", codec);
            root.put("hdr", isHdr());
            root.put("bitrate_kbps", bitrateKbps);
            root.put("connection_mode", connectionMode);
            root.put("audio_enabled", audioEnabled);
            root.put("rumble", rumble);
            root.put("circle_confirm", circleConfirm);
            root.put("touch_controls", touchControls);
            root.put("probe_log", probeLog);
            root.put("psn_account_id", psnAccountId);
            root.put("psn_online_id", psnOnlineId);
            root.put("active_profile_id", activeProfileId);

            JSONArray arr = new JSONArray();
            for (ConsoleProfile p : profiles) {
                arr.put(p.toJson());
            }
            root.put("profiles_list", arr);

            try (FileOutputStream fos = new FileOutputStream(configFile)) {
                fos.write(root.toString(2).getBytes(StandardCharsets.UTF_8));
            }
        } catch (Throwable e) {
            AppLogger.e("CONFIG", "Error guardando config: " + e.getMessage());
        }
    }

    public boolean isHdr() {
        return "hevc_hdr".equals(codec);
    }

    public String getCodecBase() {
        return "h264".equals(codec) ? "h264" : "hevc";
    }

    public String getResolutionLabel() {
        switch (resolution) {
            case "2160p": return "4K (2160p)";
            case "1440p": return "2K (1440p)";
            case "1080p": return "1080p FHD";
            case "720p":  return "720p HD";
            default:      return resolution;
        }
    }

    public String getUpscaleLabel() {
        switch (upscaleMode) {
            case "cas_high": return "CAS Alto";
            case "cas_med":  return "CAS Medio";
            case "direct":   return "Directo (0-Copy)";
            default:         return "Auto 60FPS";
        }
    }

    public ConsoleProfile getActiveProfile() {
        for (ConsoleProfile p : profiles) {
            if (p.id != null && p.id.equals(activeProfileId)) return p;
        }
        return profiles.isEmpty() ? null : profiles.get(0);
    }

    public void upsertProfile(ConsoleProfile cp) {
        for (int i = 0; i < profiles.size(); i++) {
            ConsoleProfile cur = profiles.get(i);
            if ((cp.id != null && cp.id.equals(cur.id)) ||
                (cp.hostId != null && !cp.hostId.isEmpty() && cp.hostId.equalsIgnoreCase(cur.hostId))) {
                profiles.set(i, cp);
                activeProfileId = cp.id;
                save();
                return;
            }
        }
        profiles.add(cp);
        activeProfileId = cp.id;
        save();
    }

    public void removeProfile(String id) {
        for (int i = 0; i < profiles.size(); i++) {
            if (id != null && id.equals(profiles.get(i).id)) {
                profiles.remove(i);
                break;
            }
        }
        if (id != null && id.equals(activeProfileId)) {
            activeProfileId = profiles.isEmpty() ? "" : profiles.get(0).id;
        }
        save();
    }

    private static String readText(File f) {
        if (!f.exists()) return null;
        try (FileInputStream fis = new FileInputStream(f)) {
            byte[] buf = new byte[(int) f.length()];
            int n = fis.read(buf);
            if (n <= 0) return null;
            return new String(buf, 0, n, StandardCharsets.UTF_8);
        } catch (Throwable ignored) {
            return null;
        }
    }
}
