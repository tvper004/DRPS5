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


def prepare_assets_and_res(build_dir: Path):
    assets_dir = build_dir / "assets"
    devices_dir = assets_dir / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)

    for fname in ("bg_main.png", "drps5_icon.png"):
        src = WEBOS_ASSETS / fname
        if src.exists():
            shutil.copy2(src, assets_dir / fname)

    for dev in ("ps5.png", "ps4.png", "unknown.png", "dualsense.png", "ds4.png"):
        src = WEBOS_ASSETS / "devices" / dev
        if src.exists():
            shutil.copy2(src, devices_dir / dev)

    res_drawable = build_dir / "res" / "drawable"
    res_drawable.mkdir(parents=True, exist_ok=True)
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

    icon_src = WEBOS_ASSETS / "drps5_icon.png"
    img_icon = Image.open(icon_src).convert("RGBA").resize((192, 192), Image.Resampling.LANCZOS)
    img_icon.save(res_drawable / "ic_launcher.png", format="PNG")

    banner = Image.new("RGBA", (320, 180), (11, 19, 41, 255))
    draw = ImageDraw.Draw(banner)
    draw.rectangle([0, 0, 320, 180], fill=(11, 19, 41, 255))
    draw.line([0, 176, 320, 176], fill=(56, 189, 248, 255), width=4)
    icon_sm = Image.open(icon_src).convert("RGBA").resize((112, 112), Image.Resampling.LANCZOS)
    banner.paste(icon_sm, (104, 34), icon_sm)
    banner.save(res_drawable / "tv_banner.png", format="PNG")


def write_manifest(manifest_path: Path, is_personal: bool):
    app_name = "DRPS5 Personal" if is_personal else "DRPS5 Remote Play"
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.drps5.remoteplay"
    android:versionCode="200"
    android:versionName="2.0.0">

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
        android:icon="@drawable/ic_launcher"
        android:banner="@drawable/tv_banner"
        android:theme="@style/AppTheme"
        android:hardwareAccelerated="true"
        android:largeHeap="true"
        android:isGame="true"
        android:usesCleartextTraffic="true">

        <activity
            android:name=".MainActivity"
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
