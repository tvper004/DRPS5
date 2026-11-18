#!/usr/bin/env python3
"""
Builder for DRPS5 V2 Android APKs (WebOS V2-inspired native UI + 2K/4K 60FPS GPU CAS Upscaling):
1. /Users/rleon/Documents/PXPLAY/APK/V2/DRPS5_V2_Personal.apk (Pre-linked Mi PS5: 192.168.1.100 / )
2. /Users/rleon/Documents/PXPLAY/APK/V2/DRPS5_V2_Publico.apk  (Clean public edition with PSN OAuth + PIN pairing)
"""

from __future__ import annotations
import base64
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
SRC_KEYS_PY = WORKSPACE_DIR / "DRPS5" / "pyremoteplay" / "pyremoteplay" / "keys.py"
WEBOS_ASSETS = WORKSPACE_DIR / "WEBOS" / "V2" / "assets"
V2_DIR = WORKSPACE_DIR / "APK" / "V2"
V2_SRC_JAVA = V2_DIR / "src"
KEYSTORE_PATH = WORKSPACE_DIR / "APK" / ".drps5_release.keystore"

ANDROID_SDK = Path.home() / "Library" / "Android" / "sdk"
BUILD_TOOLS = ANDROID_SDK / "build-tools" / "34.0.0"
PLATFORM_JAR = ANDROID_SDK / "platforms" / "android-34" / "android.jar"
JDK_BIN = Path.home() / ".local" / "jdk-17" / "Contents" / "Home" / "bin"

AAPT2 = BUILD_TOOLS / "aapt2"
D8 = BUILD_TOOLS / "d8"
ZIPALIGN = BUILD_TOOLS / "zipalign"
APKSIGNER = BUILD_TOOLS / "apksigner"
JAVAC = JDK_BIN / "javac"

PERSONAL_CONFIG = {
    "version": "2.0.0",
    "resolution": "1080p",
    "upscale_mode": "auto",
    "fps": 60,
    "codec": "hevc",
    "hdr": False,
    "audio_enabled": True,
    "circle_confirm": False,
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "Mi PS5",
            "local_ip": "192.168.1.100",
            "remote_ip": "",
            "connection_mode": "auto",
            "host_id": "",
            "host_name": "PS5",
            "host_type": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada"
        }
    }
}

PUBLIC_CONFIG = {
    "version": "2.0.0",
    "resolution": "1080p",
    "upscale_mode": "auto",
    "fps": 60,
    "codec": "hevc",
    "hdr": False,
    "audio_enabled": True,
    "circle_confirm": False,
    "active_profile_id": "",
    "profiles": {}
}



_PSEED = WORKSPACE_DIR / "personal_seed.json"
if _PSEED.exists():
    PERSONAL_SEED_CONFIG = json.loads(_PSEED.read_text(encoding="utf-8"))
    PERSONAL_CONFIG = PERSONAL_SEED_CONFIG

def load_ps5_keys():
    spec = importlib.util.spec_from_file_location("keys", str(SRC_KEYS_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {
        "HMAC_KEY_PS5": bytes(mod.HMAC_KEY_PS5),
        "REG_KEY_0_PS5": bytes(mod.REG_KEY_0_PS5),
        "REG_KEY_1_PS5": bytes(mod.REG_KEY_1_PS5),
        "SESSION_KEY_0_PS5": bytes(mod.SESSION_KEY_0_PS5),
        "SESSION_KEY_1_PS5": bytes(mod.SESSION_KEY_1_PS5),
        "HMAC_KEY_PS4": bytes(mod.HMAC_KEY_PS4),
        "REG_KEY_0_PS4": bytes(mod.REG_KEY_0_PS4),
        "REG_KEY_1_PS4": bytes(mod.REG_KEY_1_PS4),
        "SESSION_KEY_0_PS4": bytes(mod.SESSION_KEY_0_PS4),
        "SESSION_KEY_1_PS4": bytes(mod.SESSION_KEY_1_PS4),
    }


def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes((b ^ key[i % len(key)] ^ ((i * 37) & 0xFF)) for i, b in enumerate(data))


def generate_guard_java(out_dir: Path, is_personal: bool):
    xor_key = secrets.token_bytes(32)
    keys = load_ps5_keys()
    seed = PERSONAL_CONFIG if is_personal else PUBLIC_CONFIG
    seed_bytes = json.dumps(seed, ensure_ascii=False).encode("utf-8")

    def b64(raw: bytes) -> str:
        return base64.b64encode(xor_bytes(raw, xor_key)).decode("ascii")

    guard = f"""package com.drps5.remoteplay;

import android.util.Base64;
import java.nio.charset.StandardCharsets;

public final class Guard {{
    private static final byte[] K = Base64.decode("{base64.b64encode(xor_key).decode('ascii')}", Base64.DEFAULT);
    private static final byte[] E_HMAC_PS5 = Base64.decode("{b64(keys['HMAC_KEY_PS5'])}", Base64.DEFAULT);
    private static final byte[] E_RK0_PS5 = Base64.decode("{b64(keys['REG_KEY_0_PS5'])}", Base64.DEFAULT);
    private static final byte[] E_RK1_PS5 = Base64.decode("{b64(keys['REG_KEY_1_PS5'])}", Base64.DEFAULT);
    private static final byte[] E_SK0_PS5 = Base64.decode("{b64(keys['SESSION_KEY_0_PS5'])}", Base64.DEFAULT);
    private static final byte[] E_SK1_PS5 = Base64.decode("{b64(keys['SESSION_KEY_1_PS5'])}", Base64.DEFAULT);

    private static final byte[] E_HMAC_PS4 = Base64.decode("{b64(keys['HMAC_KEY_PS4'])}", Base64.DEFAULT);
    private static final byte[] E_RK0_PS4 = Base64.decode("{b64(keys['REG_KEY_0_PS4'])}", Base64.DEFAULT);
    private static final byte[] E_RK1_PS4 = Base64.decode("{b64(keys['REG_KEY_1_PS4'])}", Base64.DEFAULT);
    private static final byte[] E_SK0_PS4 = Base64.decode("{b64(keys['SESSION_KEY_0_PS4'])}", Base64.DEFAULT);
    private static final byte[] E_SK1_PS4 = Base64.decode("{b64(keys['SESSION_KEY_1_PS4'])}", Base64.DEFAULT);

    private static final byte[] E_SEED = Base64.decode("{b64(seed_bytes)}", Base64.DEFAULT);
    public static final boolean IS_PERSONAL = {"true" if is_personal else "false"};

    private static byte[] dec(byte[] src) {{
        byte[] out = new byte[src.length];
        for (int i = 0; i < src.length; i++) {{
            out[i] = (byte) ((src[i] & 0xFF) ^ (K[i % K.length] & 0xFF) ^ ((i * 37) & 0xFF));
        }}
        return out;
    }}

    public static byte[] getHmacKey(boolean isPs4) {{ return dec(isPs4 ? E_HMAC_PS4 : E_HMAC_PS5); }}
    public static byte[] getRegKey0(boolean isPs4) {{ return dec(isPs4 ? E_RK0_PS4 : E_RK0_PS5); }}
    public static byte[] getRegKey1(boolean isPs4) {{ return dec(isPs4 ? E_RK1_PS4 : E_RK1_PS5); }}
    public static byte[] getSessionKey0(boolean isPs4) {{ return dec(isPs4 ? E_SK0_PS4 : E_SK0_PS5); }}
    public static byte[] getSessionKey1(boolean isPs4) {{ return dec(isPs4 ? E_SK1_PS4 : E_SK1_PS5); }}

    public static byte[] getHmacKey() {{ return getHmacKey(false); }}
    public static byte[] getRegKey0() {{ return getRegKey0(false); }}
    public static byte[] getRegKey1() {{ return getRegKey1(false); }}
    public static byte[] getSessionKey0() {{ return getSessionKey0(false); }}
    public static byte[] getSessionKey1() {{ return getSessionKey1(false); }}

    public static String getSeedConfigJson() {{
        return new String(dec(E_SEED), StandardCharsets.UTF_8);
    }}
}}
"""
    pkg = out_dir / "com" / "drps5" / "remoteplay"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "Guard.java").write_text(guard, encoding="utf-8")


def make_pure_black_gamepad_master() -> Image.Image:
    raw_src = WORKSPACE_DIR / "DRPS5" / "app_icon_1024.png"
    if not raw_src.exists():
        raw_src = WEBOS_ASSETS / "drps5_icon.png"
    src_im = Image.open(raw_src).convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)
    src_px = src_im.load()

    clean = Image.new("RGB", (1024, 1024), (0, 0, 0))
    dst_px = clean.load()
    for y in range(1024):
        dy = abs(y - 512) / 412.0
        dy4 = dy * dy * dy * dy
        if dy4 >= 1.0:
            continue
        for x in range(1024):
            dx = abs(x - 512) / 412.0
            d4 = dx * dx * dx * dx + dy4
            if d4 >= 1.0:
                continue
            r, g, b, a = src_px[x, y]
            if a < 32:
                continue
            # Pure monochrome luminance (no blue/other colors) + pure #000000 floor
            lum = max(r, int(0.299 * r + 0.587 * g + 0.114 * b))
            if d4 > 0.86:
                lum = int(lum * (1.0 - (d4 - 0.86) / 0.14))
            if lum <= 22:
                continue
            v = min(255, int((lum - 22) * 255 / 233))
            dst_px[x, y] = (v, v, v)

    # Crop around optical mass center (516, 526) with smooth radial fade into #000000
    cx, cy, half = 516, 526, 430
    cropped = Image.new("RGB", (half * 2, half * 2), (0, 0, 0))
    cropped.paste(clean, (half - cx, half - cy))
    cpx = cropped.load()
    size = half * 2
    for y in range(size):
        ny = (y - half) / float(half)
        for x in range(size):
            nx = (x - half) / float(half)
            dist = (nx * nx + ny * ny) ** 0.5
            if dist >= 0.98:
                cpx[x, y] = (0, 0, 0)
            elif dist > 0.82:
                r0, _, _ = cpx[x, y]
                if r0 > 0:
                    v = int(r0 * (0.98 - dist) / 0.16)
                    cpx[x, y] = (v, v, v)
    return cropped


def prepare_assets_and_res(build_dir: Path):
    assets_dir = build_dir / "assets"
    devices_dir = assets_dir / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)

    bg_src = WEBOS_ASSETS / "bg_main.png"
    if bg_src.exists():
        shutil.copy2(bg_src, assets_dir / "bg_main.png")

    for dev in ("ps5.png", "ps4.png", "unknown.png", "dualsense.png", "ds4.png"):
        src = WEBOS_ASSETS / "devices" / dev
        if src.exists():
            shutil.copy2(src, devices_dir / dev)

    res_drawable_xhdpi = build_dir / "res" / "drawable-xhdpi"
    res_drawable_xhdpi.mkdir(parents=True, exist_ok=True)
    res_drawable_xxxhdpi = build_dir / "res" / "drawable-xxxhdpi"
    res_drawable_xxxhdpi.mkdir(parents=True, exist_ok=True)
    res_mipmap_xhdpi = build_dir / "res" / "mipmap-xhdpi"
    res_mipmap_xhdpi.mkdir(parents=True, exist_ok=True)
    res_mipmap_xxhdpi = build_dir / "res" / "mipmap-xxhdpi"
    res_mipmap_xxhdpi.mkdir(parents=True, exist_ok=True)
    res_mipmap_xxxhdpi = build_dir / "res" / "mipmap-xxxhdpi"
    res_mipmap_xxxhdpi.mkdir(parents=True, exist_ok=True)
    res_mipmap_anydpi_v26 = build_dir / "res" / "mipmap-anydpi-v26"
    res_mipmap_anydpi_v26.mkdir(parents=True, exist_ok=True)
    res_values = build_dir / "res" / "values"
    res_values.mkdir(parents=True, exist_ok=True)

    styles_xml = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="@android:style/Theme.Black.NoTitleBar.Fullscreen">
        <item name="android:windowBackground">@android:color/black</item>
        <item name="android:colorBackground">@android:color/black</item>
    </style>
</resources>
"""
    (res_values / "styles.xml").write_text(styles_xml, encoding="utf-8")

    master_pad = make_pure_black_gamepad_master()

    # In-app icon (512x512 crisp, pure black + centered monochrome gamepad)
    master_pad.resize((512, 512), Image.Resampling.LANCZOS).save(assets_dir / "drps5_icon.png", format="PNG")

    # Proper density-qualified mipmap launcher icons (pure #000000 edge-to-edge + large centered gamepad)
    for folder, sz in ((res_mipmap_xhdpi, 96), (res_mipmap_xxhdpi, 144), (res_mipmap_xxxhdpi, 192)):
        ic = Image.new("RGB", (sz, sz), (0, 0, 0))
        pad_sz = int(round(sz * 0.90))
        pad_im = master_pad.resize((pad_sz, pad_sz), Image.Resampling.LANCZOS)
        ic.paste(pad_im, ((sz - pad_sz) // 2, (sz - pad_sz) // 2))
        ic.save(folder / "ic_launcher.png", format="PNG")

    # Adaptive icon foreground MUST be in mipmap-xxxhdpi (where 108dp == 432px!) so Android never shifts/clips it
    fg_icon = Image.new("RGB", (432, 432), (0, 0, 0))
    pad_fg = master_pad.resize((288, 288), Image.Resampling.LANCZOS)
    fg_icon.paste(pad_fg, ((432 - 288) // 2, (432 - 288) // 2))
    fg_icon.save(res_mipmap_xxxhdpi / "ic_launcher_fg.png", format="PNG")

    adaptive_xml = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@android:color/black" />
    <foreground android:drawable="@mipmap/ic_launcher_fg" />
</adaptive-icon>
"""
    (res_mipmap_anydpi_v26 / "ic_launcher.xml").write_text(adaptive_xml, encoding="utf-8")

    # Android TV / Stick Leanback banner in BOTH xhdpi (320x180) and xxxhdpi (640x360 HD):
    # 100% pure #000000 black + large crisp centered gamepad
    banner_hd = Image.new("RGB", (640, 360), (0, 0, 0))
    pad_bhd = master_pad.resize((336, 336), Image.Resampling.LANCZOS)
    banner_hd.paste(pad_bhd, ((640 - 336) // 2, (360 - 336) // 2))
    banner_hd.save(res_drawable_xxxhdpi / "tv_banner.png", format="PNG")
    banner_hd.resize((320, 180), Image.Resampling.LANCZOS).save(res_drawable_xhdpi / "tv_banner.png", format="PNG")


def write_manifest(manifest_path: Path, is_personal: bool):
    app_name = "DRPS5 Personal" if is_personal else "DRPS5 Remote Play"
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.drps5.remoteplay"
    android:versionCode="203"
    android:versionName="2.0.17">

    <uses-sdk android:minSdkVersion="23" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />

    <uses-feature android:name="android.software.leanback" android:required="false" />
    <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
    <uses-feature android:name="android.hardware.gamepad" android:required="false" />
    <uses-feature android:glEsVersion="0x00020000" android:required="true" />

    <application
        android:label="{app_name}"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher"
        android:banner="@drawable/tv_banner"
        android:theme="@style/AppTheme"
        android:hardwareAccelerated="true"
        android:largeHeap="true"
        android:isGame="true"
        android:usesCleartextTraffic="true">

        <activity
            android:name=".MainActivity"
            android:label="{app_name}"
            android:icon="@mipmap/ic_launcher"
            android:roundIcon="@mipmap/ic_launcher"
            android:banner="@drawable/tv_banner"
            android:exported="true"
            android:screenOrientation="sensorLandscape"
            android:configChanges="orientation|screenSize|screenLayout|keyboard|keyboardHidden|navigation|uiMode">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
                <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
    manifest_path.write_text(manifest, encoding="utf-8")


def build_apk(output_apk: Path, is_personal: bool):
    work_dir = V2_DIR / ("_build_personal" if is_personal else "_build_public")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    src_dir = work_dir / "src"
    shutil.copytree(V2_SRC_JAVA, src_dir)
    generate_guard_java(src_dir, is_personal)

    prepare_assets_and_res(work_dir)
    manifest = work_dir / "AndroidManifest.xml"
    write_manifest(manifest, is_personal)

    compiled_res = work_dir / "res.zip"
    subprocess.run([str(AAPT2), "compile", "--dir", str(work_dir / "res"), "-o", str(compiled_res)], check=True)

    unsigned_apk = work_dir / "unsigned.apk"
    subprocess.run([
        str(AAPT2), "link",
        "-o", str(unsigned_apk),
        "-I", str(PLATFORM_JAR),
        "--manifest", str(manifest),
        "--java", str(src_dir),
        "-A", str(work_dir / "assets"),
        str(compiled_res),
    ], check=True)

    classes_dir = work_dir / "classes"
    classes_dir.mkdir()
    java_files = [str(p) for p in src_dir.rglob("*.java")]
    subprocess.run([
        str(JAVAC),
        "-g:none",
        "--release", "8",
        "-encoding", "UTF-8",
        "-cp", str(PLATFORM_JAR),
        "-d", str(classes_dir),
        *java_files,
    ], check=True)

    dex_dir = work_dir / "dex"
    dex_dir.mkdir()
    class_files = [str(p) for p in classes_dir.rglob("*.class")]
    subprocess.run([
        str(D8),
        "--release",
        "--min-api", "23",
        "--lib", str(PLATFORM_JAR),
        "--output", str(dex_dir),
        *class_files,
    ], check=True)

    # Inject classes.dex into unsigned.apk using zip
    subprocess.run(["zip", "-j", str(unsigned_apk), str(dex_dir / "classes.dex")], check=True)

    aligned_apk = work_dir / "aligned.apk"
    subprocess.run([str(ZIPALIGN), "-f", "-p", "4", str(unsigned_apk), str(aligned_apk)], check=True)

    if output_apk.exists():
        output_apk.unlink()
    subprocess.run([
        str(APKSIGNER), "sign",
        "--ks", str(KEYSTORE_PATH),
        "--ks-key-alias", "drps5key",
        "--ks-pass", "pass:drps5pass",
        "--key-pass", "pass:drps5pass",
        "--out", str(output_apk),
        str(aligned_apk),
    ], check=True)

    shutil.rmtree(work_dir)
    print(f"Built: {output_apk} ({output_apk.stat().st_size} bytes)")


def main():
    os.environ["PATH"] = f"{JDK_BIN}:{os.environ.get('PATH', '')}"
    V2_DIR.mkdir(parents=True, exist_ok=True)
    build_apk(V2_DIR / "DRPS5_V2_Personal.apk", True)
    build_apk(V2_DIR / "DRPS5_V2_Publico.apk", False)


if __name__ == "__main__":
    main()
