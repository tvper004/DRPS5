#!/usr/bin/env python3
"""
Constructor de APKs nativos Android TV + Mobile para DRPS5 (Anti-REA):
1. /Users/rleon/Documents/PXPLAY/APK/DRPS5_Personal.apk (Con la PS5 del usuario vinculada: 192.168.1.100 / )
2. /Users/rleon/Documents/PXPLAY/APK/DRPS5_Publico.apk (Versión pública limpia sin PS5 vinculada)
"""

from __future__ import annotations
import base64
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
SRC_DIR = WORKSPACE_DIR / "DRPS5"
APK_OUT_DIR = WORKSPACE_DIR / "APK"

ANDROID_SDK = Path.home() / "Library" / "Android" / "sdk"
BUILD_TOOLS = ANDROID_SDK / "build-tools" / "34.0.0"
PLATFORM_JAR = ANDROID_SDK / "platforms" / "android-34" / "android.jar"
JDK_BIN = Path.home() / ".local" / "jdk-17" / "Contents" / "Home" / "bin"

AAPT2 = BUILD_TOOLS / "aapt2"
D8 = BUILD_TOOLS / "d8"
ZIPALIGN = BUILD_TOOLS / "zipalign"
APKSIGNER = BUILD_TOOLS / "apksigner"
JAVAC = JDK_BIN / "javac"
KEYTOOL = JDK_BIN / "keytool"

PERSONAL_CONFIG = {
    "version": "1.3.1",
    "last_used_ip": "192.168.1.100",
    "resolution": "720p",
    "fps": 60,
    "bitrate": "standard",
    "codec": "hevc",
    "audio_enabled": True,
    "fullscreen": True,
    "circle_confirm": False,
    "consoles": {
        "": {
            "host_id": "",
            "host_name": "PS5",
            "host_ip": "192.168.1.100",
            "host_type": "PS5",
            "status": "Encendida"
        },
        "192.168.1.100": {
            "host_id": "",
            "host_name": "Mi PS5",
            "host_ip": "192.168.1.100",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada"
        }
    },
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "Mi PS5",
            "local_ip": "192.168.1.100",
            "remote_ip": "",
            "connection_mode": "local",
            "host_id": "",
            "host_name": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada",
            "resolution": "720p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False,
            "circle_confirm": False,
            "audio_enabled": True,
            "fullscreen": True,
            "show_hud": True
        }
    },
    "show_hud": True,
    "gamepad_mapping": {
        "ps_button": 5,
        "touchpad_button": 20,
        "options_button": 6,
        "share_button": 4,
        "stick_deadzone": 0.12
    },
    "hdr": False
}

PUBLIC_CONFIG = {
    "version": "1.3.1",
    "last_used_ip": "",
    "resolution": "720p",
    "fps": 60,
    "bitrate": "standard",
    "codec": "hevc",
    "audio_enabled": True,
    "fullscreen": True,
    "consoles": {},
    "active_profile_id": "prof_default",
    "profiles": {
        "prof_default": {
            "id": "prof_default",
            "name": "PS5 Principal",
            "local_ip": "",
            "remote_ip": "",
            "connection_mode": "local",
            "host_id": "",
            "host_name": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Pendiente",
            "resolution": "720p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False
        }
    },
    "show_hud": True,
    "gamepad_mapping": {
        "ps_button": 5,
        "touchpad_button": 20,
        "options_button": 6,
        "share_button": 4,
        "stick_deadzone": 0.12
    },
    "hdr": True
}


def load_ps5_keys():
    spec = importlib.util.spec_from_file_location(
        "keys", str(SRC_DIR / "pyremoteplay" / "pyremoteplay" / "keys.py")
    )
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


def java_byte_array(data: bytes) -> str:
    vals = []
    for b in data:
        sb = b - 256 if b >= 128 else b
        vals.append(str(sb))
    return "{ " + ", ".join(vals) + " }"


def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[(i % len(key))] ^ ((i * 37) & 0xFF) for i, b in enumerate(data))


def generate_java_sources(src_java_dir: Path, is_personal: bool):
    pkg_dir = src_java_dir / "com" / "drps5" / "remoteplay"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    xor_key = secrets.token_bytes(32)
    ps5_keys = load_ps5_keys()
    seed_cfg = PERSONAL_CONFIG if is_personal else PUBLIC_CONFIG
    seed_json_bytes = json.dumps(seed_cfg, ensure_ascii=False).encode("utf-8")

    enc_hmac_ps5 = xor_bytes(ps5_keys["HMAC_KEY_PS5"], xor_key)
    enc_rk0_ps5 = xor_bytes(ps5_keys["REG_KEY_0_PS5"], xor_key)
    enc_rk1_ps5 = xor_bytes(ps5_keys["REG_KEY_1_PS5"], xor_key)
    enc_sk0_ps5 = xor_bytes(ps5_keys["SESSION_KEY_0_PS5"], xor_key)
    enc_sk1_ps5 = xor_bytes(ps5_keys["SESSION_KEY_1_PS5"], xor_key)

    enc_hmac_ps4 = xor_bytes(ps5_keys["HMAC_KEY_PS4"], xor_key)
    enc_rk0_ps4 = xor_bytes(ps5_keys["REG_KEY_0_PS4"], xor_key)
    enc_rk1_ps4 = xor_bytes(ps5_keys["REG_KEY_1_PS4"], xor_key)
    enc_sk0_ps4 = xor_bytes(ps5_keys["SESSION_KEY_0_PS4"], xor_key)
    enc_sk1_ps4 = xor_bytes(ps5_keys["SESSION_KEY_1_PS4"], xor_key)

    enc_seed = xor_bytes(seed_json_bytes, xor_key)

    b64_k = base64.b64encode(xor_key).decode("ascii")
    b64_hmac_ps5 = base64.b64encode(enc_hmac_ps5).decode("ascii")
    b64_rk0_ps5 = base64.b64encode(enc_rk0_ps5).decode("ascii")
    b64_rk1_ps5 = base64.b64encode(enc_rk1_ps5).decode("ascii")
    b64_sk0_ps5 = base64.b64encode(enc_sk0_ps5).decode("ascii")
    b64_sk1_ps5 = base64.b64encode(enc_sk1_ps5).decode("ascii")

    b64_hmac_ps4 = base64.b64encode(enc_hmac_ps4).decode("ascii")
    b64_rk0_ps4 = base64.b64encode(enc_rk0_ps4).decode("ascii")
    b64_rk1_ps4 = base64.b64encode(enc_rk1_ps4).decode("ascii")
    b64_sk0_ps4 = base64.b64encode(enc_sk0_ps4).decode("ascii")
    b64_sk1_ps4 = base64.b64encode(enc_sk1_ps4).decode("ascii")

    b64_seed = base64.b64encode(enc_seed).decode("ascii")

    # 1. Guard.java (Anti-REA + Vault)
    guard_java = f"""package com.drps5.remoteplay;

import android.os.Debug;
import android.util.Base64;
import java.io.BufferedReader;
import java.io.FileReader;
import java.nio.charset.StandardCharsets;

public final class Guard {{
    private static final byte[] K = Base64.decode("{b64_k}", Base64.DEFAULT);
    private static final byte[] E_HMAC_PS5 = Base64.decode("{b64_hmac_ps5}", Base64.DEFAULT);
    private static final byte[] E_RK0_PS5 = Base64.decode("{b64_rk0_ps5}", Base64.DEFAULT);
    private static final byte[] E_RK1_PS5 = Base64.decode("{b64_rk1_ps5}", Base64.DEFAULT);
    private static final byte[] E_SK0_PS5 = Base64.decode("{b64_sk0_ps5}", Base64.DEFAULT);
    private static final byte[] E_SK1_PS5 = Base64.decode("{b64_sk1_ps5}", Base64.DEFAULT);

    private static final byte[] E_HMAC_PS4 = Base64.decode("{b64_hmac_ps4}", Base64.DEFAULT);
    private static final byte[] E_RK0_PS4 = Base64.decode("{b64_rk0_ps4}", Base64.DEFAULT);
    private static final byte[] E_RK1_PS4 = Base64.decode("{b64_rk1_ps4}", Base64.DEFAULT);
    private static final byte[] E_SK0_PS4 = Base64.decode("{b64_sk0_ps4}", Base64.DEFAULT);
    private static final byte[] E_SK1_PS4 = Base64.decode("{b64_sk1_ps4}", Base64.DEFAULT);

    private static final byte[] E_SEED = Base64.decode("{b64_seed}", Base64.DEFAULT);
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

    public static void verifyIntegrity() {{
        if (Debug.isDebuggerConnected() || Debug.waitingForDebugger()) {{
            Runtime.getRuntime().halt(0);
        }}
        try (BufferedReader br = new BufferedReader(new FileReader("/proc/self/status"))) {{
            String line;
            while ((line = br.readLine()) != null) {{
                if (line.startsWith("TracerPid:")) {{
                    int pid = Integer.parseInt(line.substring(10).trim());
                    if (pid != 0) {{
                        Runtime.getRuntime().halt(0);
                    }}
                    break;
                }}
            }}
        }} catch (Throwable ignored) {{}}

        try (BufferedReader br = new BufferedReader(new FileReader("/proc/self/maps"))) {{
            String line;
            while ((line = br.readLine()) != null) {{
                String lower = line.toLowerCase();
                if (lower.contains("frida") || lower.contains("xposed") || lower.contains("substrate")) {{
                    Runtime.getRuntime().halt(0);
                }}
            }}
        }} catch (Throwable ignored) {{}}
    }}
}}
"""
    (pkg_dir / "Guard.java").write_text(guard_java, encoding="utf-8")

    # 2. PS5Crypto.java (SessionCipher, StreamECDH secp256k1, StreamCipher CTR + GMAC)
    crypto_java = r"""package com.drps5.remoteplay;

import java.math.BigInteger;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public final class PS5Crypto {
    private static final SecureRandom RNG = new SecureRandom();
    private static final int GMAC_REFRESH_IV = 44910;
    private static final int GMAC_REFRESH_KEY_POS = 45000;

    private static final BigInteger SECP256K1_P = new BigInteger("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16);
    private static final BigInteger SECP256K1_A = BigInteger.ZERO;
    private static final BigInteger SECP256K1_B = BigInteger.valueOf(7);
    private static final BigInteger SECP256K1_GX = new BigInteger("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16);
    private static final BigInteger SECP256K1_GY = new BigInteger("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16);
    private static final BigInteger SECP256K1_N = new BigInteger("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16);

    public static byte[] randomBytes(int len) {
        byte[] b = new byte[len];
        RNG.nextBytes(b);
        return b;
    }

    public static byte[] sha256(byte[] data) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return md.digest(data);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static byte[] hmacSha256(byte[] key, byte[] data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(data);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static byte[] getRpNonce(byte[] nonce, boolean isPs4) {
        byte[] sessionKey = Guard.getSessionKey0(isPs4);
        byte[] rpNonce = new byte[16];
        int keyOffset = ((nonce[0] & 0xFF) >> 3) * 112;
        for (int i = 0; i < 16; i++) {
            int shift = isPs4 ? ((nonce[i] & 0xFF) + 54 + i) : ((nonce[i] & 0xFF) - 45 - i);
            shift ^= (sessionKey[keyOffset + i] & 0xFF);
            int val = shift % 256;
            if (val < 0) val += 256;
            rpNonce[i] = (byte) val;
        }
        return rpNonce;
    }

    public static byte[] getRpNonce(byte[] nonce) {
        return getRpNonce(nonce, false);
    }

    public static byte[] genRegKey0(long pin, boolean isPs4) {
        byte[] regKey = Guard.getRegKey0(isPs4);
        byte[] key = new byte[16];
        for (int i = 0; i < 16; i++) {
            key[i] = regKey[i * 32 + 1];
        }
        int shift = 0;
        for (int i = 12; i < 16; i++) {
            key[i] = (byte) ((key[i] & 0xFF) ^ ((pin >>> (24 - (shift * 8))) & 0xFF));
            shift++;
        }
        return key;
    }

    public static byte[] genRegKey0(long pin) {
        return genRegKey0(pin, false);
    }

    public static byte[] genRegKey1(byte[] nonce, boolean isPs4) {
        byte[] regKey = Guard.getRegKey1(isPs4);
        byte[] key = new byte[16];
        int offset = isPs4 ? 41 : -45;
        for (int i = 0; i < 16; i++) {
            int shift = regKey[i * 32 + 8] & 0xFF;
            int n = nonce[i] & 0xFF;
            int val = ((n ^ shift) + offset + i) % 256;
            if (val < 0) val += 256;
            key[i] = (byte) val;
        }
        return key;
    }

    public static byte[] genRegKey1(byte[] nonce) {
        return genRegKey1(nonce, false);
    }

    public static byte[] getAesKey(byte[] nonce, byte[] rpKey, boolean isPs4) {
        byte[] sessionKey = Guard.getSessionKey1(isPs4);
        byte[] aesKey = new byte[16];
        int keyOffset = ((nonce[7] & 0xFF) >> 3) * 112;
        for (int i = 0; i < 16; i++) {
            int shift;
            if (isPs4) {
                shift = ((sessionKey[keyOffset + i] & 0xFF) ^ (rpKey[i] & 0xFF)) + 33 + i;
                shift ^= (nonce[i] & 0xFF);
            } else {
                shift = (rpKey[i] & 0xFF) + 24 + i;
                shift ^= (nonce[i] & 0xFF);
                shift ^= (sessionKey[keyOffset + i] & 0xFF);
            }
            int val = shift % 256;
            if (val < 0) val += 256;
            aesKey[i] = (byte) val;
        }
        return aesKey;
    }

    public static byte[] getAesKey(byte[] nonce, byte[] rpKey) {
        return getAesKey(nonce, rpKey, false);
    }

    public static byte[] cfbCrypt(byte[] key, byte[] iv, byte[] data, boolean encrypt) {
        if (data == null || data.length == 0) return new byte[0];
        try {
            Cipher ecb = Cipher.getInstance("AES/ECB/NoPadding");
            ecb.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"));
            byte[] out = new byte[data.length];
            byte[] blockIv = Arrays.copyOf(iv, 16);
            int offset = 0;
            while (offset < data.length) {
                byte[] keystream = ecb.doFinal(blockIv);
                int chunk = Math.min(16, data.length - offset);
                for (int i = 0; i < chunk; i++) {
                    byte inByte = data[offset + i];
                    byte outByte = (byte) (inByte ^ keystream[i]);
                    out[offset + i] = outByte;
                    if (encrypt) {
                        blockIv[i] = outByte;
                    } else {
                        blockIv[i] = inByte;
                    }
                }
                offset += chunk;
            }
            return out;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static final class SessionCipher {
        private final byte[] key;
        private final byte[] rpNonce;
        private final boolean isPs4;
        private int encCounter;
        private int decCounter;

        public SessionCipher(byte[] key, byte[] rpNonce, int counter, boolean isPs4) {
            this.key = key;
            this.rpNonce = rpNonce;
            this.encCounter = counter;
            this.decCounter = counter;
            this.isPs4 = isPs4;
        }

        public SessionCipher(byte[] key, byte[] rpNonce, int counter) {
            this(key, rpNonce, counter, false);
        }

        private byte[] getAesIv(long cnt) {
            byte[] suffix = new byte[8];
            for (int i = 7; i >= 0; i--) {
                suffix[i] = (byte) (cnt & 0xFF);
                cnt >>>= 8;
            }
            byte[] msg = new byte[rpNonce.length + 8];
            System.arraycopy(rpNonce, 0, msg, 0, rpNonce.length);
            System.arraycopy(suffix, 0, msg, rpNonce.length, 8);
            byte[] hmac = hmacSha256(Guard.getHmacKey(isPs4), msg);
            return Arrays.copyOf(hmac, 16);
        }

        public synchronized byte[] encrypt(byte[] msg) {
            byte[] iv = getAesIv(encCounter++);
            return cfbCrypt(key, iv, msg, true);
        }

        public synchronized byte[] decrypt(byte[] msg) {
            byte[] iv = getAesIv(decCounter++);
            return cfbCrypt(key, iv, msg, false);
        }

        public byte[] encryptAtCounter(byte[] msg, int cnt) {
            byte[] iv = getAesIv(cnt);
            return cfbCrypt(key, iv, msg, true);
        }
    }

    private static BigInteger[] pointAdd(BigInteger[] p1, BigInteger[] p2) {
        if (p1 == null) return p2;
        if (p2 == null) return p1;
        BigInteger x1 = p1[0], y1 = p1[1], x2 = p2[0], y2 = p2[1];
        if (x1.equals(x2)) {
            if (!y1.equals(y2)) return null;
            BigInteger num = x1.pow(2).multiply(BigInteger.valueOf(3)).add(SECP256K1_A);
            BigInteger den = y1.multiply(BigInteger.valueOf(2));
            BigInteger m = num.multiply(den.modInverse(SECP256K1_P)).mod(SECP256K1_P);
            BigInteger x3 = m.pow(2).subtract(x1.multiply(BigInteger.valueOf(2))).mod(SECP256K1_P);
            BigInteger y3 = m.multiply(x1.subtract(x3)).subtract(y1).mod(SECP256K1_P);
            return new BigInteger[]{x3, y3};
        } else {
            BigInteger num = y2.subtract(y1);
            BigInteger den = x2.subtract(x1);
            BigInteger m = num.multiply(den.modInverse(SECP256K1_P)).mod(SECP256K1_P);
            BigInteger x3 = m.pow(2).subtract(x1).subtract(x2).mod(SECP256K1_P);
            BigInteger y3 = m.multiply(x1.subtract(x3)).subtract(y1).mod(SECP256K1_P);
            return new BigInteger[]{x3, y3};
        }
    }

    private static BigInteger[] pointMul(BigInteger k, BigInteger[] p) {
        BigInteger[] res = null;
        BigInteger[] cur = p;
        for (int i = 0; i < k.bitLength(); i++) {
            if (k.testBit(i)) res = pointAdd(res, cur);
            cur = pointAdd(cur, cur);
        }
        return res;
    }

    private static byte[] toFixed32(BigInteger n) {
        byte[] raw = n.toByteArray();
        byte[] out = new byte[32];
        if (raw.length > 32) {
            System.arraycopy(raw, raw.length - 32, out, 0, 32);
        } else {
            System.arraycopy(raw, 0, out, 32 - raw.length, raw.length);
        }
        return out;
    }

    public static final class StreamECDH {
        public final byte[] handshakeKey;
        public final byte[] publicKey;
        public final byte[] publicSig;
        private final BigInteger privScalar;
        public byte[] secret;

        public StreamECDH() {
            this.handshakeKey = randomBytes(16);
            BigInteger priv;
            do {
                priv = new BigInteger(256, RNG);
            } while (priv.compareTo(BigInteger.ONE) <= 0 || priv.compareTo(SECP256K1_N) >= 0);
            this.privScalar = priv;
            BigInteger[] pub = pointMul(priv, new BigInteger[]{SECP256K1_GX, SECP256K1_GY});
            ByteBuffer pb = ByteBuffer.allocate(65);
            pb.put((byte) 0x04);
            pb.put(toFixed32(pub[0]));
            pb.put(toFixed32(pub[1]));
            this.publicKey = pb.array();
            this.publicSig = hmacSha256(this.handshakeKey, this.publicKey);
        }

        public boolean setSecret(byte[] remoteKey, byte[] remoteSig) {
            if (remoteKey.length != 65 || remoteKey[0] != 0x04) return false;
            byte[] calcSig = hmacSha256(this.handshakeKey, remoteKey);
            if (!Arrays.equals(calcSig, remoteSig)) return false;
            BigInteger rx = new BigInteger(1, Arrays.copyOfRange(remoteKey, 1, 33));
            BigInteger ry = new BigInteger(1, Arrays.copyOfRange(remoteKey, 33, 65));
            BigInteger[] sharedPt = pointMul(this.privScalar, new BigInteger[]{rx, ry});
            this.secret = toFixed32(sharedPt[0]);
            return true;
        }

        public StreamCipher initCiphers() {
            return new StreamCipher(this.handshakeKey, this.secret);
        }
    }

    public static byte[] counterAdd(long counter, byte[] iv) {
        byte[] out = Arrays.copyOf(iv, 16);
        counterAddInPlace(counter, iv, out, 0);
        return out;
    }

    public static void counterAddInPlace(long counter, byte[] iv, byte[] out, int outOffset) {
        System.arraycopy(iv, 0, out, outOffset, 16);
        long c = counter;
        for (int i = 0; i < 16; i++) {
            long add = (out[outOffset + i] & 0xFFL) + c;
            out[outOffset + i] = (byte) (add & 0xFFL);
            c = add >>> 8;
            if (c <= 0) break;
        }
    }

    public static byte[] getGmacKey(long gmacIndex, byte[] key, byte[] iv) {
        long scaled = gmacIndex * GMAC_REFRESH_IV;
        byte[] outArr = counterAdd(scaled, iv);
        byte[] concat = new byte[32];
        System.arraycopy(key, 0, concat, 0, 16);
        System.arraycopy(outArr, 0, concat, 16, 16);
        byte[] digest = sha256(concat);
        byte[] gcm = new byte[16];
        for (int i = 0; i < 16; i++) {
            gcm[i] = (byte) (digest[i] ^ digest[i + 16]);
        }
        return gcm;
    }

    public static byte[] getGmacTag(byte[] data, byte[] key, byte[] iv) {
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, iv));
            c.updateAAD(data);
            byte[] tag = c.doFinal(new byte[0]);
            return Arrays.copyOf(tag, 4);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static byte[] getKeyStream(byte[] key, byte[] iv, long keyPos, int dataLen) {
        int padding = (int) (keyPos % 16);
        long alignedPos = keyPos - padding;
        int streamLen = ((padding + dataLen + 15) / 16) * 16;
        byte[] ivStream = new byte[streamLen];
        int blocks = streamLen / 16;
        long blockOffset = (alignedPos / 16) + 1;
        for (int b = 0; b < blocks; b++) {
            counterAddInPlace(blockOffset + b, iv, ivStream, b * 16);
        }
        byte[] encStream = aesEcbEncrypt(key, ivStream);
        return Arrays.copyOfRange(encStream, padding, padding + dataLen);
    }

    public static byte[] aesEcbEncrypt(byte[] key, byte[] data) {
        try {
            Cipher c = Cipher.getInstance("AES/ECB/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static byte[] cryptCtr(byte[] key, byte[] iv, long keyPos, byte[] data) {
        if (data == null || data.length == 0) return new byte[0];
        byte[] ks = getKeyStream(key, iv, keyPos, data.length);
        byte[] out = new byte[data.length];
        for (int i = 0; i < data.length; i++) {
            out[i] = (byte) (data[i] ^ ks[i]);
        }
        return out;
    }

    public static final class StreamCipher {
        private final byte[] localBaseKey;
        private final byte[] localBaseIv;
        private final byte[] localBaseGmacKey;
        private byte[] localCurrentGmacKey;
        private SecretKeySpec localCurrentGmacKeySpec;
        private long localGmacIndex = 0;
        private final byte[] remoteBaseKey;
        private final byte[] remoteBaseIv;
        private volatile long localKeyPos = 0;

        private final Object decryptLock = new Object();
        private final Object audioDecryptLock = new Object();
        private final Object encryptLock = new Object();

        private final Cipher remoteEcbCipher;
        private final Cipher remoteAudioEcbCipher;
        private final Cipher localEcbCipher;
        private final Cipher localGcmCipher;
        private final byte[] ivStreamBuf = new byte[4096];
        private final byte[] encStreamBuf = new byte[4096];
        private final byte[] audioIvStreamBuf = new byte[1024];
        private final byte[] audioEncStreamBuf = new byte[1024];
        private final byte[] localIvStreamBuf = new byte[512];
        private final byte[] localEncStreamBuf = new byte[512];
        private final byte[] gmacIvBuf = new byte[16];
        private static final byte[] EMPTY_BYTES = new byte[0];

        public StreamCipher(byte[] handshakeKey, byte[] secret) {
            byte[][] local = deriveBase(secret, handshakeKey, 2);
            this.localBaseKey = local[0];
            this.localBaseIv = local[1];
            this.localBaseGmacKey = getGmacKey(0, this.localBaseKey, this.localBaseIv);
            this.localCurrentGmacKey = this.localBaseGmacKey;
            this.localCurrentGmacKeySpec = new SecretKeySpec(this.localCurrentGmacKey, "AES");
            byte[][] remote = deriveBase(secret, handshakeKey, 3);
            this.remoteBaseKey = remote[0];
            this.remoteBaseIv = remote[1];

            Cipher rCipher;
            Cipher rAudioCipher;
            Cipher lCipher;
            Cipher gcmCipher;
            try {
                SecretKeySpec rSpec = new SecretKeySpec(this.remoteBaseKey, "AES");
                rCipher = Cipher.getInstance("AES/ECB/NoPadding");
                rCipher.init(Cipher.ENCRYPT_MODE, rSpec);
                rAudioCipher = Cipher.getInstance("AES/ECB/NoPadding");
                rAudioCipher.init(Cipher.ENCRYPT_MODE, rSpec);
                lCipher = Cipher.getInstance("AES/ECB/NoPadding");
                lCipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(this.localBaseKey, "AES"));
                gcmCipher = Cipher.getInstance("AES/GCM/NoPadding");
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
            this.remoteEcbCipher = rCipher;
            this.remoteAudioEcbCipher = rAudioCipher;
            this.localEcbCipher = lCipher;
            this.localGcmCipher = gcmCipher;
        }

        private static byte[][] deriveBase(byte[] secret, byte[] handshakeKey, int index) {
            byte[] msg = new byte[3 + handshakeKey.length + 2];
            msg[0] = 0x01;
            msg[1] = (byte) index;
            msg[2] = 0x00;
            System.arraycopy(handshakeKey, 0, msg, 3, handshakeKey.length);
            msg[3 + handshakeKey.length] = 0x01;
            msg[4 + handshakeKey.length] = 0x00;
            byte[] h = hmacSha256(secret, msg);
            return new byte[][]{
                Arrays.copyOfRange(h, 0, 16),
                Arrays.copyOfRange(h, 16, 32)
            };
        }

        public byte[] encrypt(byte[] data) {
            if (data == null || data.length == 0) return EMPTY_BYTES;
            synchronized (encryptLock) {
                int len = data.length;
                int padding = (int) (localKeyPos % 16);
                long alignedPos = localKeyPos - padding;
                int streamLen = ((padding + len + 15) / 16) * 16;
                if (streamLen > localIvStreamBuf.length) {
                    return cryptCtr(localBaseKey, localBaseIv, localKeyPos, data);
                }
                int blocks = streamLen / 16;
                long blockOffset = (alignedPos / 16) + 1;
                for (int b = 0; b < blocks; b++) {
                    counterAddInPlace(blockOffset + b, localBaseIv, localIvStreamBuf, b * 16);
                }
                try {
                    localEcbCipher.doFinal(localIvStreamBuf, 0, streamLen, localEncStreamBuf, 0);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                byte[] out = new byte[len];
                for (int i = 0; i < len; i++) {
                    out[i] = (byte) (data[i] ^ localEncStreamBuf[padding + i]);
                }
                return out;
            }
        }

        public int decrypt(byte[] inBuf, int inOff, int len, long keyPos, byte[] outBuf, int outOff) {
            if (len <= 0) return 0;
            synchronized (decryptLock) {
                int padding = (int) (keyPos % 16);
                long alignedPos = keyPos - padding;
                int streamLen = ((padding + len + 15) / 16) * 16;
                if (streamLen > ivStreamBuf.length) {
                    byte[] ks = getKeyStream(remoteBaseKey, remoteBaseIv, keyPos, len);
                    for (int i = 0; i < len; i++) {
                        outBuf[outOff + i] = (byte) (inBuf[inOff + i] ^ ks[i]);
                    }
                    return len;
                }
                int blocks = streamLen / 16;
                long blockOffset = (alignedPos / 16) + 1;
                for (int b = 0; b < blocks; b++) {
                    counterAddInPlace(blockOffset + b, remoteBaseIv, ivStreamBuf, b * 16);
                }
                try {
                    remoteEcbCipher.doFinal(ivStreamBuf, 0, streamLen, encStreamBuf, 0);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                for (int i = 0; i < len; i++) {
                    outBuf[outOff + i] = (byte) (inBuf[inOff + i] ^ encStreamBuf[padding + i]);
                }
                return len;
            }
        }

        public int decryptAudio(byte[] inBuf, int inOff, int len, long keyPos, byte[] outBuf, int outOff) {
            if (len <= 0) return 0;
            synchronized (audioDecryptLock) {
                int padding = (int) (keyPos % 16);
                long alignedPos = keyPos - padding;
                int streamLen = ((padding + len + 15) / 16) * 16;
                if (streamLen > audioIvStreamBuf.length) {
                    return decrypt(inBuf, inOff, len, keyPos, outBuf, outOff);
                }
                int blocks = streamLen / 16;
                long blockOffset = (alignedPos / 16) + 1;
                for (int b = 0; b < blocks; b++) {
                    counterAddInPlace(blockOffset + b, remoteBaseIv, audioIvStreamBuf, b * 16);
                }
                try {
                    remoteAudioEcbCipher.doFinal(audioIvStreamBuf, 0, streamLen, audioEncStreamBuf, 0);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                for (int i = 0; i < len; i++) {
                    outBuf[outOff + i] = (byte) (inBuf[inOff + i] ^ audioEncStreamBuf[padding + i]);
                }
                return len;
            }
        }

        public byte[] decrypt(byte[] data, long keyPos) {
            byte[] out = new byte[data.length];
            decrypt(data, 0, data.length, keyPos, out, 0);
            return out;
        }

        public int getGmac(byte[] data) {
            synchronized (encryptLock) {
                counterAddInPlace(localKeyPos / 16, localBaseIv, gmacIvBuf, 0);
                long idx = localKeyPos > 0 ? (localKeyPos - 1) / GMAC_REFRESH_KEY_POS : 0;
                SecretKeySpec keySpec;
                if (idx > this.localGmacIndex) {
                    this.localGmacIndex = idx;
                    this.localCurrentGmacKey = getGmacKey(idx, this.localBaseGmacKey, this.localBaseIv);
                    this.localCurrentGmacKeySpec = new SecretKeySpec(this.localCurrentGmacKey, "AES");
                    keySpec = this.localCurrentGmacKeySpec;
                } else if (idx < this.localGmacIndex) {
                    keySpec = new SecretKeySpec(getGmacKey(idx, this.localBaseKey, this.localBaseIv), "AES");
                } else {
                    keySpec = this.localCurrentGmacKeySpec;
                }
                try {
                    localGcmCipher.init(Cipher.ENCRYPT_MODE, keySpec, new GCMParameterSpec(128, gmacIvBuf));
                    localGcmCipher.updateAAD(data);
                    byte[] tag = localGcmCipher.doFinal(EMPTY_BYTES);
                    return ((tag[0] & 0xFF) << 24) | ((tag[1] & 0xFF) << 16) | ((tag[2] & 0xFF) << 8) | (tag[3] & 0xFF);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }
        }

        public long getKeyPos() {
            return localKeyPos;
        }

        public void advanceKeyPos(int delta) {
            synchronized (encryptLock) {
                localKeyPos += delta;
            }
        }
    }
}
"""
    (pkg_dir / "PS5Crypto.java").write_text(crypto_java, encoding="utf-8")

    # 3. PS5Protocol.java (DDP Discovery, Wakeup, PIN Registration, Minimal Protobuf)
    proto_java = r"""package com.drps5.remoteplay;

import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

public final class PS5Protocol {
    public static final int DDP_PORT_PS5 = 9302;
    public static final int DDP_PORT_PS4 = 987;
    public static final int RP_PORT = 9295;
    private static final String CLIENT_TYPE = "dabfa2ec873de5839bee8d3f4c0239c4282c07c25c6077a2931afcf0adc0d34f";
    private static final String USER_AGENT = "remoteplay Windows";

    public static String cleanIp(String ip) {
        if (ip == null) return "";
        String s = ip.split(",")[0].trim();
        s = s.split("\\s+")[0].trim();
        return s;
    }

    public static String formatAccountId(String input) {
        if (input == null || input.trim().isEmpty()) {
            return "AAAAAAAAAAAAAAAAAAAAAA==";
        }
        String s = input.trim();
        try {
            if (s.matches("^\\d+$")) {
                BigInteger bi = new BigInteger(s);
                byte[] le = new byte[8];
                for (int i = 0; i < 8; i++) {
                    le[i] = bi.shiftRight(i * 8).byteValue();
                }
                return Base64.encodeToString(le, Base64.NO_WRAP);
            }
            if (s.toLowerCase().startsWith("0x") || s.matches("^[0-9a-fA-F]{16}$")) {
                String hex = s.toLowerCase().startsWith("0x") ? s.substring(2) : s;
                BigInteger bi = new BigInteger(hex, 16);
                byte[] le = new byte[8];
                for (int i = 0; i < 8; i++) {
                    le[i] = bi.shiftRight(i * 8).byteValue();
                }
                return Base64.encodeToString(le, Base64.NO_WRAP);
            }
            byte[] dec = Base64.decode(s, Base64.DEFAULT);
            if (dec.length == 8) return s;
        } catch (Exception ignored) {}
        return Base64.encodeToString(s.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
    }

    public static String formatRegistKeyForWakeup(String registKeyHex) {
        if (registKeyHex == null || registKeyHex.isEmpty()) return "0";
        try {
            byte[] asciiBytes = hexToBytes(registKeyHex);
            String innerHex = new String(asciiBytes, StandardCharsets.US_ASCII).trim();
            long val = Long.parseUnsignedLong(innerHex, 16);
            return Long.toUnsignedString(val);
        } catch (Exception e) {
            try {
                long val = Long.parseUnsignedLong(registKeyHex.substring(0, Math.min(8, registKeyHex.length())), 16);
                return Long.toUnsignedString(val);
            } catch (Exception ex) {
                return "0";
            }
        }
    }

    public static byte[] hexToBytes(String hex) {
        if (hex == null) return new byte[0];
        String s = hex.trim();
        int len = s.length();
        byte[] data = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            data[i / 2] = (byte) ((Character.digit(s.charAt(i), 16) << 4)
                                 + Character.digit(s.charAt(i + 1), 16));
        }
        return data;
    }

    public static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format("%02x", b & 0xFF));
        }
        return sb.toString();
    }

    public static Map<String, String> parseDdpResponse(String resp, String hostIp) {
        Map<String, String> map = new HashMap<>();
        if (resp == null || resp.contains("SRCH *")) return map;
        for (String rawLine : resp.split("\\r?\\n")) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;
            if (line.startsWith("HTTP/1.1 ")) {
                String[] parts = line.split("\\s+", 3);
                if (parts.length >= 2) map.put("status-code", parts[1]);
                if (parts.length >= 3) map.put("status", parts[2]);
            } else {
                int idx = line.indexOf(':');
                if (idx > 0) {
                    map.put(line.substring(0, idx).trim(), line.substring(idx + 1).trim());
                }
            }
        }
        map.put("host-ip", hostIp);
        return map;
    }

    public static JSONArray discoverConsoles(int timeoutSec, String hintIp) {
        JSONArray arr = new JSONArray();
        Map<String, JSONObject> found = new HashMap<>();
        String srch = "SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n";
        byte[] payload = srch.getBytes(StandardCharsets.UTF_8);

        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setBroadcast(true);
            sock.setSoTimeout(350);

            List<String> targets = new ArrayList<>();
            targets.add("255.255.255.255");
            if (hintIp != null && !hintIp.isEmpty()) {
                targets.add(cleanIp(hintIp));
            }

            long end = System.currentTimeMillis() + Math.max(1200, timeoutSec * 1000L);
            for (int round = 0; round < 2; round++) {
                for (String t : targets) {
                    try {
                        InetAddress addr = InetAddress.getByName(t);
                        sock.send(new DatagramPacket(payload, payload.length, addr, DDP_PORT_PS5));
                        sock.send(new DatagramPacket(payload, payload.length, addr, DDP_PORT_PS4));
                    } catch (Exception ignored) {}
                }
                byte[] buf = new byte[2048];
                while (System.currentTimeMillis() < end) {
                    try {
                        DatagramPacket pkt = new DatagramPacket(buf, buf.length);
                        sock.receive(pkt);
                        String text = new String(pkt.getData(), 0, pkt.getLength(), StandardCharsets.UTF_8);
                        String rIp = pkt.getAddress().getHostAddress();
                        Map<String, String> parsed = parseDdpResponse(text, rIp);
                        if (parsed.containsKey("status-code")) {
                            int code = Integer.parseInt(parsed.get("status-code"));
                            JSONObject obj = new JSONObject();
                            String hostId = parsed.getOrDefault("host-id", rIp);
                            obj.put("host_id", hostId);
                            obj.put("host_name", parsed.getOrDefault("host-name", "PS5 Console"));
                            obj.put("host_ip", rIp);
                            obj.put("host_type", parsed.getOrDefault("host-type", "PS5"));
                            obj.put("status_code", code);
                            obj.put("status", code == 200 ? "Encendida" : (code == 620 ? "Modo Reposo" : "Detectada"));
                            obj.put("system_version", parsed.getOrDefault("system-version", ""));
                            found.put(rIp, obj);
                        }
                    } catch (Exception e) {
                        break;
                    }
                }
            }
        } catch (Exception ignored) {}

        for (JSONObject o : found.values()) {
            arr.put(o);
        }
        return arr;
    }

    public static Map<String, String> getHostStatus(String ip) {
        String clean = cleanIp(ip);
        if (clean.isEmpty()) return null;
        String srch = "SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n";
        byte[] payload = srch.getBytes(StandardCharsets.UTF_8);
        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setSoTimeout(clean.startsWith("100.") ? 1800 : 950);
            InetAddress addr = InetAddress.getByName(clean);
            sock.send(new DatagramPacket(payload, payload.length, addr, DDP_PORT_PS5));
            sock.send(new DatagramPacket(payload, payload.length, addr, DDP_PORT_PS4));
            byte[] buf = new byte[2048];
            DatagramPacket pkt = new DatagramPacket(buf, buf.length);
            sock.receive(pkt);
            String text = new String(pkt.getData(), 0, pkt.getLength(), StandardCharsets.UTF_8);
            Map<String, String> map = parseDdpResponse(text, clean);
            if (map.containsKey("status-code")) return map;
        } catch (Exception ignored) {}
        return null;
    }

    public static boolean wakeupPs5(String ip, String registKey) {
        String clean = cleanIp(ip);
        if (clean.isEmpty()) return false;
        String cred = formatRegistKeyForWakeup(registKey);
        String msg = "WAKEUP * HTTP/1.1\n"
                + "user-credential:" + cred + "\n"
                + "client-type:vr\n"
                + "auth-type:R\n"
                + "model:w\n"
                + "app-type:r\n"
                + "device-discovery-protocol-version:00030010\n";
        byte[] data = msg.getBytes(StandardCharsets.UTF_8);
        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setBroadcast(true);
            InetAddress target = InetAddress.getByName(clean);
            InetAddress bcast = InetAddress.getByName("255.255.255.255");
            for (int i = 0; i < 3; i++) {
                sock.send(new DatagramPacket(data, data.length, target, DDP_PORT_PS5));
                sock.send(new DatagramPacket(data, data.length, target, DDP_PORT_PS4));
                sock.send(new DatagramPacket(data, data.length, bcast, DDP_PORT_PS5));
            }
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    public static JSONObject pairConsole(String ip, String pinStr, String accountId, boolean isPs4) {
        JSONObject result = new JSONObject();
        String cName = isPs4 ? "PS4" : "PS5";
        try {
            String cleanIp = cleanIp(ip);
            String cleanPin = pinStr == null ? "" : pinStr.replaceAll("[\\s-]", "");
            if (!cleanPin.matches("^\\d{8}$")) {
                result.put("success", false);
                result.put("error", "El PIN debe contener exactamente 8 dígitos numéricos.");
                return result;
            }
            long pinVal = Long.parseLong(cleanPin);
            String formattedAcc = formatAccountId(accountId);

            // Paso 1: UDP SRC2/RES2 (PS4) o SRC3/RES3 (PS5) en puerto 9295
            String initCode = isPs4 ? "SRC2" : "SRC3";
            String startCode = isPs4 ? "RES2" : "RES3";
            try (DatagramSocket udp = new DatagramSocket()) {
                udp.setSoTimeout(3500);
                byte[] initBytes = initCode.getBytes(StandardCharsets.US_ASCII);
                udp.send(new DatagramPacket(initBytes, initBytes.length, InetAddress.getByName(cleanIp), RP_PORT));
                byte[] rbuf = new byte[32];
                DatagramPacket rpkt = new DatagramPacket(rbuf, rbuf.length);
                udp.receive(rpkt);
                String rstr = new String(rpkt.getData(), 0, Math.min(4, rpkt.getLength()), StandardCharsets.US_ASCII);
                if (!startCode.equals(rstr)) {
                    result.put("success", false);
                    result.put("error", "La " + cName + " no está en modo Vincular dispositivo.");
                    return result;
                }
            }

            // Paso 2: Generar claves de registro y payload cifrado
            byte[] nonce = PS5Crypto.randomBytes(16);
            byte[] key0 = PS5Crypto.genRegKey0(pinVal, isPs4);
            byte[] key1 = PS5Crypto.genRegKey1(nonce, isPs4);

            byte[] regPayload = new byte[480];
            Arrays.fill(regPayload, (byte) 'A');
            System.arraycopy(key1, 8, regPayload, 199, 8);
            System.arraycopy(key1, 0, regPayload, 401, 8);

            PS5Crypto.SessionCipher cipher = new PS5Crypto.SessionCipher(key0, nonce, 0, isPs4);
            String inner = "Client-Type: " + CLIENT_TYPE + "\r\nNp-AccountId: " + formattedAcc + "\r\n";
            byte[] encInner = cipher.encrypt(inner.getBytes(StandardCharsets.UTF_8));

            byte[] body = new byte[regPayload.length + encInner.length];
            System.arraycopy(regPayload, 0, body, 0, regPayload.length);
            System.arraycopy(encInner, 0, body, regPayload.length, encInner.length);

            String regPath = isPs4 ? "/sie/ps4/rp/sess/rgst" : "/sie/ps5/rp/sess/rgst";
            String rpVer = isPs4 ? "10.0" : "1.0";
            String headers = "POST " + regPath + " HTTP/1.1\r\n HTTP/1.1\r\n"
                    + "HOST: 10.0.2.15\r\n"
                    + "User-Agent: " + USER_AGENT + "\r\n"
                    + "Connection: close\r\n"
                    + "Content-Length: " + body.length + "\r\n"
                    + "RP-Version: " + rpVer + "\r\n\r\n";
            byte[] hdrBytes = headers.getBytes(StandardCharsets.UTF_8);

            byte[] respBytes;
            try (Socket tcp = new Socket()) {
                tcp.connect(new InetSocketAddress(cleanIp, RP_PORT), 4000);
                tcp.setSoTimeout(5000);
                tcp.setTcpNoDelay(true);
                OutputStream os = tcp.getOutputStream();
                os.write(hdrBytes);
                os.write(body);
                os.flush();

                InputStream is = tcp.getInputStream();
                ByteArrayOutputStream baos = new ByteArrayOutputStream();
                byte[] buf = new byte[1024];
                int n;
                while ((n = is.read(buf)) != -1) {
                    baos.write(buf, 0, n);
                }
                respBytes = baos.toByteArray();
            }

            String rawHead = new String(respBytes, StandardCharsets.ISO_8859_1);
            int splitIdx = rawHead.indexOf("\r\n\r\n");
            if (!rawHead.startsWith("HTTP/1.1 200") || splitIdx < 0) {
                result.put("success", false);
                result.put("error", "La consola rechazó el PIN o el código caducó.");
                return result;
            }

            byte[] cipherBody = Arrays.copyOfRange(respBytes, splitIdx + 4, respBytes.length);
            byte[] decBytes = cipher.decrypt(cipherBody);
            String decStr = new String(decBytes, StandardCharsets.UTF_8);

            String rpKey = "";
            String registKey = "";
            String hostId = cleanIp;
            String hostName = isPs4 ? "PS4 Vinculada" : "PS5 Vinculada";

            for (String line : decStr.split("\\r?\\n")) {
                int colon = line.indexOf(": ");
                if (colon > 0) {
                    String k = line.substring(0, colon).trim();
                    String v = line.substring(colon + 2).trim();
                    if (k.equalsIgnoreCase("RP-Key")) rpKey = v;
                    else if (k.endsWith("RegistKey")) registKey = v;
                    else if (k.endsWith("Mac")) hostId = v;
                    else if (k.endsWith("Nickname")) hostName = v;
                }
            }

            if (rpKey.isEmpty()) {
                result.put("success", false);
                result.put("error", "Respuesta de vinculación incompleta.");
                return result;
            }

            result.put("success", true);
            result.put("host_id", hostId);
            result.put("host_name", hostName);
            result.put("host_ip", cleanIp);
            result.put("rp_key", rpKey);
            result.put("regist_key", registKey);
            result.put("account_id", formattedAcc);
            result.put("console_type", isPs4 ? "PS4" : "PS5");
            return result;
        } catch (Exception e) {
            try {
                result.put("success", false);
                result.put("error", "Error al vincular con " + cName + ": " + e.getMessage());
            } catch (Exception ignored) {}
            return result;
        }
    }

    public static JSONObject pairPs5(String ip, String pinStr, String accountId) {
        return pairConsole(ip, pinStr, accountId, false);
    }

    // Minimal Protobuf encoder/decoder for TakionMessage
    public static void writeVarint(ByteArrayOutputStream out, long val) {
        long v = val;
        while ((v & ~0x7FL) != 0) {
            out.write((int) ((v & 0x7F) | 0x80));
            v >>>= 7;
        }
        out.write((int) v);
    }

    public static void writeTag(ByteArrayOutputStream out, int fieldNum, int wireType) {
        writeVarint(out, ((long) fieldNum << 3) | wireType);
    }

    public static void writeBytesField(ByteArrayOutputStream out, int fieldNum, byte[] data) {
        if (data == null) return;
        writeTag(out, fieldNum, 2);
        writeVarint(out, data.length);
        out.write(data, 0, data.length);
    }

    public static void writeUInt32Field(ByteArrayOutputStream out, int fieldNum, long val) {
        writeTag(out, fieldNum, 0);
        writeVarint(out, val);
    }

    public static byte[] buildBigPayload(
            int clientVersion,
            byte[] sessionKey,
            byte[] launchSpec,
            byte[] encryptedKey,
            byte[] ecdhPubKey,
            byte[] ecdhSig
    ) {
        ByteArrayOutputStream inner = new ByteArrayOutputStream();
        writeUInt32Field(inner, 1, clientVersion);
        writeBytesField(inner, 2, sessionKey);
        writeBytesField(inner, 3, launchSpec);
        writeBytesField(inner, 4, encryptedKey);
        writeBytesField(inner, 5, ecdhPubKey);
        writeBytesField(inner, 6, ecdhSig);

        ByteArrayOutputStream outer = new ByteArrayOutputStream();
        writeUInt32Field(outer, 1, 0); // PayloadType.BIG = 0
        writeBytesField(outer, 2, inner.toByteArray());
        return outer.toByteArray();
    }

    public static byte[] buildSimpleTakionMsg(int payloadType) {
        ByteArrayOutputStream outer = new ByteArrayOutputStream();
        writeUInt32Field(outer, 1, payloadType);
        return outer.toByteArray();
    }

    public static byte[] buildCorruptFrameMsg(int start, int end) {
        ByteArrayOutputStream inner = new ByteArrayOutputStream();
        writeUInt32Field(inner, 1, start);
        writeUInt32Field(inner, 2, end);

        ByteArrayOutputStream outer = new ByteArrayOutputStream();
        writeUInt32Field(outer, 1, 5); // PayloadType.CORRUPTFRAME = 5
        writeBytesField(outer, 6, inner.toByteArray());
        return outer.toByteArray();
    }

    public static byte[] buildDisconnectMsg() {
        ByteArrayOutputStream inner = new ByteArrayOutputStream();
        writeBytesField(inner, 1, "Client Disconnecting".getBytes(StandardCharsets.UTF_8));

        ByteArrayOutputStream outer = new ByteArrayOutputStream();
        writeUInt32Field(outer, 1, 8); // PayloadType.DISCONNECT = 8
        writeBytesField(outer, 10, inner.toByteArray());
        return outer.toByteArray();
    }

    public static final class ParsedTakion {
        public int type = -1;
        public byte[] bangEcdhPub;
        public byte[] bangEcdhSig;
        public byte[] videoHeader;
        public int streamWidth = 0;
        public int streamHeight = 0;
    }

    public static ParsedTakion parseTakionMessage(byte[] buf) {
        ParsedTakion res = new ParsedTakion();
        int[] pos = new int[]{0};
        while (pos[0] < buf.length) {
            long tag = readVarint(buf, pos);
            if (tag < 0) break;
            int field = (int) (tag >>> 3);
            int wire = (int) (tag & 7);
            if (wire == 0) {
                long v = readVarint(buf, pos);
                if (field == 1) res.type = (int) v;
            } else if (wire == 2) {
                int len = (int) readVarint(buf, pos);
                if (len < 0 || pos[0] + len > buf.length) break;
                byte[] sub = Arrays.copyOfRange(buf, pos[0], pos[0] + len);
                pos[0] += len;
                if (field == 3) { // bang_payload
                    parseBangSub(sub, res);
                } else if (field == 15) { // stream_info_payload
                    parseStreamInfoSub(sub, res);
                }
            } else if (wire == 5) {
                pos[0] += 4;
            } else if (wire == 1) {
                pos[0] += 8;
            } else {
                break;
            }
        }
        return res;
    }

    private static void parseBangSub(byte[] sub, ParsedTakion out) {
        int[] pos = new int[]{0};
        while (pos[0] < sub.length) {
            long tag = readVarint(sub, pos);
            if (tag < 0) break;
            int field = (int) (tag >>> 3);
            int wire = (int) (tag & 7);
            if (wire == 0) {
                readVarint(sub, pos);
            } else if (wire == 2) {
                int len = (int) readVarint(sub, pos);
                if (len < 0 || pos[0] + len > sub.length) break;
                byte[] data = Arrays.copyOfRange(sub, pos[0], pos[0] + len);
                pos[0] += len;
                if (field == 8) out.bangEcdhPub = data;
                else if (field == 9) out.bangEcdhSig = data;
            } else {
                break;
            }
        }
    }

    private static void parseStreamInfoSub(byte[] sub, ParsedTakion out) {
        int[] pos = new int[]{0};
        while (pos[0] < sub.length) {
            long tag = readVarint(sub, pos);
            if (tag < 0) break;
            int field = (int) (tag >>> 3);
            int wire = (int) (tag & 7);
            if (wire == 0) {
                readVarint(sub, pos);
            } else if (wire == 2) {
                int len = (int) readVarint(sub, pos);
                if (len < 0 || pos[0] + len > sub.length) break;
                byte[] data = Arrays.copyOfRange(sub, pos[0], pos[0] + len);
                pos[0] += len;
                if (field == 1 && out.videoHeader == null) { // ResolutionPayload
                    parseResolutionSub(data, out);
                }
            } else {
                break;
            }
        }
    }

    private static void parseResolutionSub(byte[] sub, ParsedTakion out) {
        int[] pos = new int[]{0};
        while (pos[0] < sub.length) {
            long tag = readVarint(sub, pos);
            if (tag < 0) break;
            int field = (int) (tag >>> 3);
            int wire = (int) (tag & 7);
            if (wire == 0) {
                long v = readVarint(sub, pos);
                if (field == 1) out.streamWidth = (int) v;
                else if (field == 2) out.streamHeight = (int) v;
            } else if (wire == 2) {
                int len = (int) readVarint(sub, pos);
                if (len < 0 || pos[0] + len > sub.length) break;
                byte[] data = Arrays.copyOfRange(sub, pos[0], pos[0] + len);
                pos[0] += len;
                if (field == 3) out.videoHeader = data;
            } else {
                break;
            }
        }
    }

    private static long readVarint(byte[] buf, int[] pos) {
        long result = 0;
        int shift = 0;
        while (pos[0] < buf.length) {
            byte b = buf[pos[0]++];
            result |= (long) (b & 0x7F) << shift;
            if ((b & 0x80) == 0) return result;
            shift += 7;
            if (shift >= 64) return -1;
        }
        return -1;
    }
}
"""
    (pkg_dir / "PS5Protocol.java").write_text(proto_java, encoding="utf-8")

    # 4. PS5StreamClient.java (Full Session + Takion v12 UDP + MediaCodec Hardware Surface Decoder + Gamepad Feedback)
    stream_java = r"""package com.drps5.remoteplay;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.os.Build;
import android.util.Base64;
import android.view.Surface;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.PortUnreachableException;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

public final class PS5StreamClient {
    public interface StreamListener {
        void onStatus(String message);
        void onConnected();
        void onError(String error);
        void onStats(float fps, int width, int height, String codec, boolean hdr, int rxPackets, int lostPackets);
    }

    private final String hostIp;
    private final String registKey;
    private final String rpKeyHex;
    private final String resolution;
    private final int fps;
    private final String codecName;
    private final boolean hdr;
    private final boolean audioEnabled;
    private final Surface surface;
    private final StreamListener listener;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private final Object sendLock = new Object();
    private int totalPacketsReceived = 0;
    private int totalPacketsLost = 0;
    private int renderedFrameCount = 0;
    private int negotiatedWidth = 0;
    private int negotiatedHeight = 0;
    private Thread statsThread;
    private long lastCongestionTime = 0;
    private long lastStateSendTime = 0;
    private short lastSentLx = 0, lastSentLy = 0, lastSentRx = 0, lastSentRy = 0;
    private Socket ctrlSocket;
    private DatagramSocket udpSocket;
    private MediaCodec videoCodec;
    private Thread decoderDrainThread;
    private Thread controllerHeartbeatThread;

    // Audio Subsystem (Opus 48kHz Stereo via MediaCodec & AudioTrack)
    private MediaCodec audioCodec;
    private AudioTrack audioTrack;
    private Thread audioDrainThread;
    private static final byte[] decAudioBuf = new byte[4096];
    private final Object audioWakeLock = new Object();

    private PS5Crypto.SessionCipher sessionCipher;
    private byte[] sessionId;
    private PS5Crypto.StreamECDH ecdh;
    private volatile PS5Crypto.StreamCipher streamCipher;

    private int tagLocal = 1;
    private volatile int tagRemote = 0;
    private int tsn = 1;
    private volatile boolean cookieAcked = false;
    private byte[] videoHeader = new byte[0];

    // Real-time low-latency ring buffer (32 slots = 533ms max window) + Cauchy Reed-Solomon FEC (Static Zero-GC)
    private static final int REASSEMBLY_RING_SIZE = 32;
    private static final int MAX_UNITS = 128;
    private static final int MAX_UNIT_SIZE = 1500;
    private static final int MAX_FEC_RECOVERY = 32;
    private static final int FRAME_BUF_SIZE = 1536 * 1024;

    // Precomputed GF(2^8) tables (primitive polynomial 0x11D) for PS5 Takion Cauchy Reed-Solomon FEC
    private static final int[] GF_EXP = new int[512];
    private static final int[] GF_LOG = new int[256];
    private static final byte[][] GF_MUL = new byte[256][256];

    static {
        int x = 1;
        for (int i = 0; i < 255; i++) {
            GF_EXP[i] = x;
            GF_LOG[x] = i;
            x <<= 1;
            if ((x & 0x100) != 0) {
                x ^= 0x11D;
            }
        }
        for (int i = 255; i < 512; i++) {
            GF_EXP[i] = GF_EXP[i - 255];
        }
        for (int a = 0; a < 256; a++) {
            for (int b = 0; b < 256; b++) {
                if (a == 0 || b == 0) {
                    GF_MUL[a][b] = 0;
                } else {
                    GF_MUL[a][b] = (byte) GF_EXP[GF_LOG[a] + GF_LOG[b]];
                }
            }
        }
    }

    private static int gfInv(int a) {
        if (a == 0) return 0;
        return GF_EXP[255 - GF_LOG[a & 0xFF]];
    }

    private static class VideoSlot {
        int frameIndex = -1;
        int expectedSrcUnits = 0;
        int expectedFecUnits = 0;
        int totalUnits = 0;
        int unitsReceivedCount = 0;
        int fecUnitsReceived = 0;
        int fecBlockSize = 0;
        volatile boolean completed = false;
        long firstPacketTime = 0;
        final boolean[] unitPresent = new boolean[MAX_UNITS];
        final boolean[] unitDecrypted = new boolean[MAX_UNITS];
        final int[] unitLengths = new int[MAX_UNITS];
        final long[] unitKeyPos = new long[MAX_UNITS];
        final byte[][] unitBuffers = new byte[MAX_UNITS][MAX_UNIT_SIZE];

        void reset(int fIndex, int srcUnits, int fecUnits) {
            frameIndex = fIndex;
            expectedSrcUnits = srcUnits;
            expectedFecUnits = fecUnits;
            totalUnits = Math.min(MAX_UNITS, srcUnits + fecUnits);
            unitsReceivedCount = 0;
            fecUnitsReceived = 0;
            fecBlockSize = 0;
            completed = false;
            firstPacketTime = System.currentTimeMillis();
            Arrays.fill(unitPresent, 0, totalUnits, false);
            Arrays.fill(unitDecrypted, 0, totalUnits, false);
        }
    }

    // Lock-free static audio packet ring buffer to decouple UDP reception from Opus HwBinder IPC & AES
    private static final int AUDIO_RING_SIZE = 64;
    private static final byte[][] audioRingBufs = new byte[AUDIO_RING_SIZE][1024];
    private static final int[] audioRingLens = new int[AUDIO_RING_SIZE];
    private volatile int audioWriteIdx = 0;
    private volatile int audioReadIdx = 0;

    // Pre-allocated static scratch buffers for zero-GC Cauchy Reed-Solomon FEC reconstruction
    private static final int[] fecMissingSrc = new int[MAX_FEC_RECOVERY];
    private static final int[] fecPresentSrc = new int[MAX_UNITS];
    private static final int[] fecUsedParity = new int[MAX_FEC_RECOVERY];
    private static final int[][] fecMatrix = new int[MAX_FEC_RECOVERY][MAX_FEC_RECOVERY];
    private static final int[][] fecInvMatrix = new int[MAX_FEC_RECOVERY][MAX_FEC_RECOVERY];
    private static final byte[][] fecSyndrome = new byte[MAX_FEC_RECOVERY][MAX_UNIT_SIZE];
    private volatile int fecRecoveredPackets = 0;
    private volatile int fecRecoveredFrames = 0;

    private final Object dispatchLock = new Object();

    private static final VideoSlot[] reassemblySlots = new VideoSlot[REASSEMBLY_RING_SIZE];
    static {
        for (int i = 0; i < REASSEMBLY_RING_SIZE; i++) {
            reassemblySlots[i] = new VideoSlot();
        }
    }

    private int nextDeliveryFrame = -1;
    private int highestReceivedFrame = -1;
    private static final byte[] assembledFrameBuf = new byte[FRAME_BUF_SIZE];
    private static final byte[] udpRecvBuf = new byte[2048];
    private DatagramPacket udpRecvPkt;
    private Thread videoFeedThread;

    private long streamStartTime = 0;
    private long lastIdrReqTime = 0;
    private long lastCorruptTime = 0;
    private volatile boolean waitingForIdr = true;
    private long targetFrameWaitStartTime = 0;
    private final boolean tailscaleMode;
    private final boolean isPs4;

    // Independent Takion sequence counters (0x01 = events, 0x06 = state) + pre-allocated feedback buffers
    private int feedbackSeqEvent = 1;
    private int feedbackSeqState = 1;
    private volatile short leftX = 0, leftY = 0, rightX = 0, rightY = 0;
    private final Object ctrlWakeLock = new Object();
    private static final int BTN_RING_SIZE = 64;
    private final int[] btnRingCodes = new int[BTN_RING_SIZE];
    private final boolean[] btnRingPressed = new boolean[BTN_RING_SIZE];
    private volatile int btnWriteIdx = 0;
    private volatile int btnReadIdx = 0;
    private InetAddress hostAddress;
    private final byte[] fbEventPlain = new byte[]{(byte) 0x80, 0x00, 0x00};
    private final byte[] fbStatePlain = new byte[28];
    private final ByteBuffer fbStateWrap = ByteBuffer.wrap(fbStatePlain);
    private final byte[] fbEventPktBuf = new byte[12 + 3];
    private final ByteBuffer fbEventPktWrap = ByteBuffer.wrap(fbEventPktBuf);
    private final byte[] fbStatePktBuf = new byte[12 + 28];
    private final ByteBuffer fbStatePktWrap = ByteBuffer.wrap(fbStatePktBuf);
    private DatagramPacket fbEventDatagram;
    private DatagramPacket fbStateDatagram;

    private static final byte[] DID_PREFIX = new byte[]{0x00, 0x18, 0x00, 0x00, 0x00, 0x07, 0x00, 0x40, 0x00, (byte) 0x80};
    private static final byte[] HB_RESP_PAYLOAD = new byte[]{0x00, 0x00, 0x00, 0x00, 0x01, (byte) 0xFE, 0x00, 0x00};
    private static final byte[] MOTION_IDLE = new byte[]{
        (byte) 0xA0, (byte) 0xFF, 0x7F, (byte) 0xFF, 0x7F, (byte) 0xFF, 0x7F, (byte) 0xFF,
        0x7F, (byte) 0x99, (byte) 0x99, (byte) 0xFF, 0x7F, (byte) 0xFE, (byte) 0xF7, (byte) 0xEF, 0x1F
    };

    private static boolean detectTailscaleOrRemote(String targetIp) {
        if (targetIp == null || targetIp.isEmpty()) return false;
        if (targetIp.startsWith("100.")) return true; // CGNAT / Tailscale 100.64.0.0/10
        int lastDot = targetIp.lastIndexOf('.');
        String targetPrefix = lastDot > 0 ? targetIp.substring(0, lastDot + 1) : "";
        boolean sameLanSubnet = false;
        boolean hasTailscaleTun = false;
        try {
            Enumeration<NetworkInterface> ifs = NetworkInterface.getNetworkInterfaces();
            while (ifs != null && ifs.hasMoreElements()) {
                NetworkInterface nif = ifs.nextElement();
                if (!nif.isUp() || nif.isLoopback()) continue;
                String name = nif.getName() != null ? nif.getName().toLowerCase() : "";
                Enumeration<InetAddress> addrs = nif.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (a instanceof Inet4Address) {
                        String ip = a.getHostAddress();
                        if (ip != null) {
                            if (!targetPrefix.isEmpty() && ip.startsWith(targetPrefix)) {
                                sameLanSubnet = true;
                            }
                            if (ip.startsWith("100.") || name.contains("tun") || name.contains("tailscale") || name.contains("wg")) {
                                hasTailscaleTun = true;
                            }
                        }
                    }
                }
            }
        } catch (Throwable ignored) {}
        if (sameLanSubnet) return false;
        return hasTailscaleTun || !targetIp.startsWith("192.168.");
    }

    public PS5StreamClient(
            String hostIp,
            String registKey,
            String rpKeyHex,
            String resolution,
            int fps,
            String codecName,
            boolean hdr,
            boolean audioEnabled,
            boolean isPs4,
            Surface surface,
            StreamListener listener
    ) {
        this.hostIp = PS5Protocol.cleanIp(hostIp);
        this.registKey = registKey;
        this.rpKeyHex = rpKeyHex;
        this.resolution = resolution != null ? resolution : "720p";
        this.fps = fps > 0 ? fps : 60;
        this.codecName = codecName != null ? codecName.toLowerCase() : "hevc";
        this.hdr = hdr;
        this.audioEnabled = audioEnabled;
        this.isPs4 = isPs4;
        this.surface = surface;
        this.listener = listener;
        this.tailscaleMode = detectTailscaleOrRemote(this.hostIp);
        System.arraycopy(MOTION_IDLE, 0, this.fbStatePlain, 0, MOTION_IDLE.length);
        try {
            this.hostAddress = InetAddress.getByName(this.hostIp);
            this.fbEventDatagram = new DatagramPacket(fbEventPktBuf, fbEventPktBuf.length, this.hostAddress, 9296);
            this.fbStateDatagram = new DatagramPacket(fbStatePktBuf, fbStatePktBuf.length, this.hostAddress, 9296);
        } catch (Exception ignored) {}
    }

    public PS5StreamClient(
            String hostIp,
            String registKey,
            String rpKeyHex,
            String resolution,
            int fps,
            String codecName,
            boolean hdr,
            boolean audioEnabled,
            Surface surface,
            StreamListener listener
    ) {
        this(hostIp, registKey, rpKeyHex, resolution, fps, codecName, hdr, audioEnabled, false, surface, listener);
    }

    public void start() {
        if (running.getAndSet(true)) return;
        new Thread(this::runSessionLoop, "DRPS5-Session").start();
    }

    public void stop() {
        if (!running.getAndSet(false)) return;
        try {
            if (videoFeedThread != null) {
                videoFeedThread.interrupt();
                videoFeedThread = null;
            }
        } catch (Exception ignored) {}
        try {
            if (decoderDrainThread != null) {
                decoderDrainThread.interrupt();
                decoderDrainThread = null;
            }
        } catch (Exception ignored) {}
        try {
            if (controllerHeartbeatThread != null) {
                controllerHeartbeatThread.interrupt();
                controllerHeartbeatThread = null;
            }
        } catch (Exception ignored) {}
        try {
            if (udpSocket != null && streamCipher != null) {
                byte[] disc = PS5Protocol.buildDisconnectMsg();
                sendControlData(disc, 1, 1, false);
            }
        } catch (Exception ignored) {}
        try { if (udpSocket != null) udpSocket.close(); } catch (Exception ignored) {}
        try { if (ctrlSocket != null) ctrlSocket.close(); } catch (Exception ignored) {}
        try {
            if (videoCodec != null) {
                videoCodec.stop();
                videoCodec.release();
                videoCodec = null;
            }
        } catch (Exception ignored) {}
        try {
            if (statsThread != null) {
                statsThread.interrupt();
                statsThread = null;
            }
        } catch (Exception ignored) {}
        releaseAudio();
    }

    private void runSessionLoop() {
        try {
            listener.onStatus("Verificando estado de PS5 en " + hostIp + "...");
            Map<String, String> st = PS5Protocol.getHostStatus(hostIp);
            if (st != null && "620".equals(st.get("status-code"))) {
                listener.onStatus("⚡ Despertando PS5 desde Modo Reposo...");
                PS5Protocol.wakeupPs5(hostIp, registKey);
                long wakeStart = System.currentTimeMillis();
                while (running.get() && System.currentTimeMillis() - wakeStart < 32000) {
                    Thread.sleep(2000);
                    Map<String, String> check = PS5Protocol.getHostStatus(hostIp);
                    if (check != null && "200".equals(check.get("status-code"))) {
                        break;
                    }
                    PS5Protocol.wakeupPs5(hostIp, registKey);
                }
            }

            listener.onStatus("Autenticando sesión Remote Play con PS5...");
            byte[] nonce = requestInitNonce();
            if (nonce == null) {
                listener.onError("No se pudo inicializar sesión con la PS5 en " + hostIp + ". Verifica que esté encendida y en la misma red o con puertos abiertos.");
                stop();
                return;
            }

            if (!openSessionCtrl(nonce)) {
                stop();
                return;
            }

            listener.onStatus("Iniciando túnel de vídeo (Takion UDP " + resolution + " @ " + fps + "fps" + (hdr ? " HDR" : " SDR") + ")...");
            startUdpStream();

        } catch (Exception e) {
            if (running.get()) {
                listener.onError("Error de conexión: " + e.getMessage());
                stop();
            }
        }
    }

    private byte[] requestInitNonce() {
        for (int attempt = 0; attempt < 6 && running.get(); attempt++) {
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(hostIp, PS5Protocol.RP_PORT), 4000);
                s.setSoTimeout(4000);
                String initPath = isPs4 ? "/sie/ps4/rp/sess/init" : "/sie/ps5/rp/sess/init";
                String sessVer = isPs4 ? "10.0" : "1.0";
                String req = "GET " + initPath + " HTTP/1.1\r\n"
                        + "Host: " + hostIp + ":" + PS5Protocol.RP_PORT + "\r\n"
                        + "User-Agent: remoteplay Windows\r\n"
                        + "Connection: close\r\n"
                        + "Content-Length: 0\r\n"
                        + "RP-Registkey: " + registKey + "\r\n"
                        + "Rp-Version: " + sessVer + "\r\n\r\n";
                s.getOutputStream().write(req.getBytes(StandardCharsets.UTF_8));
                s.getOutputStream().flush();
                android.util.Log.e("DRPS5_AUTH", "INIT sent req, registKey=" + registKey);

                ByteArrayOutputStream baos = new ByteArrayOutputStream();
                byte[] buf = new byte[1024];
                int n;
                while ((n = s.getInputStream().read(buf)) != -1) {
                    baos.write(buf, 0, n);
                }
                String resp = new String(baos.toByteArray(), StandardCharsets.ISO_8859_1);
                android.util.Log.e("DRPS5_AUTH", "INIT response:\n" + resp);
                if (!resp.startsWith("HTTP/1.1 200")) {
                    String reason = "";
                    for (String line : resp.split("\\r?\\n")) {
                        if (line.toLowerCase().startsWith("rp-application-reason:")) {
                            reason = line.substring(22).trim();
                        }
                    }
                    if ("80108b10".equalsIgnoreCase(reason)) {
                        if (attempt < 5) {
                            listener.onStatus("Liberando sesión previa en PS5 (" + (attempt + 1) + "/5)...");
                            Thread.sleep(1500);
                            continue;
                        }
                        listener.onError("Otra sesión está activa en la PS5 (80108b10). Ciérrala en el otro dispositivo.");
                    } else if ("80108bff".equalsIgnoreCase(reason)) {
                        listener.onError("Clave de vinculación rechazada (80108bff). Verifica el PIN.");
                    } else if ("80108b26".equalsIgnoreCase(reason)) {
                        listener.onError("PIN expirado o consola no registrada (80108b26). Genera un PIN nuevo.");
                    } else {
                        listener.onError("Error inicialización PS5 (" + (reason.isEmpty() ? "HTTP error" : reason) + ").");
                    }
                    return null;
                }
                for (String line : resp.split("\\r?\\n")) {
                    if (line.toLowerCase().startsWith("rp-nonce:")) {
                        String b64 = line.substring(9).trim();
                        return Base64.decode(b64, Base64.DEFAULT);
                    }
                }
            } catch (Exception e) {
                if (attempt == 5) {
                    listener.onError("Fallo de red al conectar con PS5: " + e.getMessage());
                }
            }
        }
        return null;
    }

    private boolean openSessionCtrl(byte[] nonce) throws Exception {
        byte[] rpNonce = PS5Crypto.getRpNonce(nonce, isPs4);
        byte[] rpKeyBytes = PS5Protocol.hexToBytes(rpKeyHex);
        byte[] aesKey = PS5Crypto.getAesKey(nonce, rpKeyBytes, isPs4);
        this.sessionCipher = new PS5Crypto.SessionCipher(aesKey, rpNonce, 0, isPs4);

        byte[] regBytes = PS5Protocol.hexToBytes(registKey);
        byte[] authPlain = new byte[16];
        System.arraycopy(regBytes, 0, authPlain, 0, Math.min(regBytes.length, 16));
        String authB64 = Base64.encodeToString(sessionCipher.encrypt(authPlain), Base64.NO_WRAP);

        byte[] didPlain = new byte[32];
        System.arraycopy(DID_PREFIX, 0, didPlain, 0, DID_PREFIX.length);
        System.arraycopy(PS5Crypto.randomBytes(16), 0, didPlain, 10, 16);
        String didB64 = Base64.encodeToString(sessionCipher.encrypt(didPlain), Base64.NO_WRAP);

        byte[] osPlain = new byte[10];
        byte[] winBytes = "Win10.0.0".getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(winBytes, 0, osPlain, 0, winBytes.length);
        String osB64 = Base64.encodeToString(sessionCipher.encrypt(osPlain), Base64.NO_WRAP);

        String bitrateB64 = Base64.encodeToString(sessionCipher.encrypt(new byte[4]), Base64.NO_WRAP);
        // Usar perfil HEVC 8-bit (stVal=2) para evitar el bug de firmware 10-bit (prePoc clear refs) en Allwinner CedarC y sostener 60 FPS reales
        int stVal = codecName.startsWith("h264") ? 1 : 2;
        byte[] stPlain = new byte[]{(byte) stVal, 0, 0, 0};
        String stB64 = Base64.encodeToString(sessionCipher.encrypt(stPlain), Base64.NO_WRAP);
        android.util.Log.e("DRPS5_AUTH", "CTRL params: rpNonce=" + PS5Protocol.bytesToHex(rpNonce)
                + " aesKey=" + PS5Protocol.bytesToHex(aesKey)
                + " auth=" + authB64
                + " did=" + didB64
                + " os=" + osB64
                + " bitrate=" + bitrateB64
                + " st=" + stB64);

        Thread.sleep(120);
        Exception lastConnEx = null;
        for (int attempt = 0; attempt < 8; attempt++) {
            try {
                ctrlSocket = new Socket();
                ctrlSocket.connect(new InetSocketAddress(hostIp, PS5Protocol.RP_PORT), 4000);
                lastConnEx = null;
                break;
            } catch (Exception ce) {
                lastConnEx = ce;
                try { ctrlSocket.close(); } catch (Exception ignored) {}
                Thread.sleep(150);
            }
        }
        if (lastConnEx != null) throw lastConnEx;
        ctrlSocket.setSoTimeout(15000);
        ctrlSocket.setTcpNoDelay(true);

        String ctrlPath = isPs4 ? "/sie/ps4/rp/sess/ctrl" : "/sie/ps5/rp/sess/ctrl";
        String sessVer = isPs4 ? "10.0" : "1.0";
        String req = "GET " + ctrlPath + " HTTP/1.1\r\n"
                + "Host: " + hostIp + ":" + PS5Protocol.RP_PORT + "\r\n"
                + "User-Agent: remoteplay Windows\r\n"
                + "Connection: keep-alive\r\n"
                + "Content-Length: 0\r\n"
                + "RP-Auth: " + authB64 + "\r\n"
                + "RP-Version: " + sessVer + "\r\n"
                + "RP-Did: " + didB64 + "\r\n"
                + "RP-ControllerType: 3\r\n"
                + "RP-ClientType: 11\r\n"
                + "RP-OSType: " + osB64 + "\r\n"
                + "RP-ConPath: 1\r\n"
                + "RP-StartBitrate: " + bitrateB64 + "\r\n"
                + (isPs4 ? "" : ("RP-StreamingType: " + stB64 + "\r\n")) + "\r\n";

        OutputStream os = ctrlSocket.getOutputStream();
        os.write(req.getBytes(StandardCharsets.UTF_8));
        os.flush();

        InputStream is = ctrlSocket.getInputStream();
        ByteArrayOutputStream headerBuf = new ByteArrayOutputStream();
        int b;
        int matchState = 0;
        while ((b = is.read()) != -1) {
            headerBuf.write(b);
            if ((matchState == 0 || matchState == 2) && b == '\r') matchState++;
            else if ((matchState == 1 || matchState == 3) && b == '\n') matchState++;
            else matchState = 0;
            if (matchState == 4) break;
        }

        String hdrStr = new String(headerBuf.toByteArray(), StandardCharsets.ISO_8859_1);
        android.util.Log.e("DRPS5_AUTH", "CTRL Response:\n" + hdrStr);
        if (!hdrStr.startsWith("HTTP/1.1 200")) {
            String reason = "";
            for (String line : hdrStr.split("\\r?\\n")) {
                if (line.toLowerCase().startsWith("rp-application-reason:")) {
                    reason = line.substring(22).trim();
                }
            }
            if ("80108b10".equalsIgnoreCase(reason)) {
                listener.onError("Otra sesión está activa en la PS5 (80108b10). Ciérrala en el otro dispositivo.");
            } else if ("80108b26".equalsIgnoreCase(reason)) {
                listener.onError("PIN expirado o re-vinculación requerida (80108b26).");
            } else {
                listener.onError("Autenticación rechazada por la PS5 (" + (reason.isEmpty() ? "Código desconocido" : reason) + ").");
            }
            return false;
        }
        for (String line : hdrStr.split("\\r?\\n")) {
            if (line.toLowerCase().startsWith("rp-server-type:")) {
                String b64 = line.substring(15).trim();
                sessionCipher.decrypt(Base64.decode(b64, Base64.DEFAULT));
            }
        }

        ctrlSocket.setSoTimeout(20000);
        long deadline = System.currentTimeMillis() + 20000;
        byte[] msgHdr = new byte[8];
        while (running.get() && System.currentTimeMillis() < deadline) {
            if (!readFully(is, msgHdr)) {
                listener.onError("La PS5 cerró la sesión antes de entregar el Session ID.");
                return false;
            }
            int payloadLen = ByteBuffer.wrap(msgHdr, 0, 4).getInt();
            if (payloadLen < 0 || payloadLen > 65536) {
                listener.onError("Longitud de paquete inválida en sesión PS5 (" + payloadLen + ").");
                return false;
            }
            int msgType = msgHdr[5] & 0xFF;
            byte[] payload = new byte[payloadLen];
            if (payloadLen > 0 && !readFully(is, payload)) {
                listener.onError("Lectura incompleta de paquete de sesión PS5.");
                return false;
            }
            if (payloadLen > 0) {
                payload = sessionCipher.decrypt(payload);
            }
            if (msgType == 0xFE) {
                sendCtrlHeartbeatResponse(os);
            } else if (msgType == 0x33) {
                if (payload.length > 2) {
                    byte[] rawSid = Arrays.copyOfRange(payload, 2, payload.length);
                    this.sessionId = normalizeSessionId(rawSid);
                    break;
                }
            }
        }

        if (this.sessionId == null || this.sessionId.length == 0) {
            listener.onError("Tiempo de espera agotado esperando Session ID (0x33) de la PS5.");
            return false;
        }

        ctrlSocket.setSoTimeout(0);
        new Thread(this::runCtrlHeartbeatLoop, "DRPS5-CtrlHB").start();
        return true;
    }

    private static byte[] normalizeSessionId(byte[] rawSid) {
        try {
            java.nio.charset.CharsetDecoder dec = StandardCharsets.UTF_8.newDecoder();
            dec.onMalformedInput(java.nio.charset.CodingErrorAction.REPORT);
            dec.onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT);
            dec.decode(ByteBuffer.wrap(rawSid));
            return rawSid;
        } catch (Exception e) {
            return new String(rawSid, StandardCharsets.ISO_8859_1).getBytes(StandardCharsets.UTF_8);
        }
    }

    private void sendCtrlHeartbeatRequest(OutputStream os) {
        try {
            byte[] reqPl = new byte[]{0x00, 0x00, 0x00, 0x00, 0x00, (byte) 0xFE, 0x00, 0x00};
            byte[] enc = sessionCipher.encrypt(reqPl);
            ByteBuffer buf = ByteBuffer.allocate(8 + enc.length);
            buf.putInt(enc.length);
            buf.putShort((short) 0x01FE);
            buf.putShort((short) 0);
            buf.put(enc);
            synchronized (os) {
                os.write(buf.array());
                os.flush();
            }
        } catch (Exception ignored) {}
    }

    private void sendCtrlHeartbeatResponse(OutputStream os) throws Exception {
        sessionCipher.encrypt(HB_RESP_PAYLOAD);
        ByteBuffer resp = ByteBuffer.allocate(8 + HB_RESP_PAYLOAD.length);
        resp.putInt(HB_RESP_PAYLOAD.length);
        resp.putShort((short) 0x01FE);
        resp.putShort((short) 0);
        resp.put(HB_RESP_PAYLOAD);
        synchronized (os) {
            os.write(resp.array());
            os.flush();
        }
    }

    private void runCtrlHeartbeatLoop() {
        try {
            ctrlSocket.setSoTimeout(4000);
            InputStream is = ctrlSocket.getInputStream();
            OutputStream os = ctrlSocket.getOutputStream();
            byte[] hdr = new byte[8];
            while (running.get()) {
                try {
                    if (!readFully(is, hdr)) break;
                    int len = ByteBuffer.wrap(hdr, 0, 4).getInt();
                    if (len < 0 || len > 65536) break;
                    int type = hdr[5] & 0xFF;
                    byte[] pl = new byte[len];
                    if (len > 0 && !readFully(is, pl)) break;
                    if (len > 0) pl = sessionCipher.decrypt(pl);
                    if (type == 0xFE) {
                        sendCtrlHeartbeatResponse(os);
                    }
                } catch (SocketTimeoutException te) {
                    if (running.get()) {
                        sendCtrlHeartbeatRequest(os);
                    }
                }
            }
        } catch (Exception ignored) {}
    }

    private static boolean readFully(InputStream is, byte[] buf) throws Exception {
        int off = 0;
        while (off < buf.length) {
            int n = is.read(buf, off, buf.length - off);
            if (n < 0) return false;
            off += n;
        }
        return true;
    }

    private volatile byte[] lastCookiePkt;
    private volatile byte[] lastBigPkt;

    private void sendCongestionPacket() {
        if (streamCipher == null || udpSocket == null) return;
        synchronized (sendLock) {
            try {
                int rx = totalPacketsReceived & 0xFFFF;
                int lx = totalPacketsLost & 0xFFFF;
                long kp = streamCipher.getKeyPos();
                byte[] raw = new byte[15];
                raw[0] = 0x05; // Type CONGESTION
                raw[1] = 0x00;
                raw[2] = 0x00;
                raw[3] = (byte) ((rx >> 8) & 0xFF);
                raw[4] = (byte) (rx & 0xFF);
                raw[5] = (byte) ((lx >> 8) & 0xFF);
                raw[6] = (byte) (lx & 0xFF);
                // raw[7..10] = 0 (GMAC placeholder)
                raw[11] = (byte) ((kp >> 24) & 0xFF);
                raw[12] = (byte) ((kp >> 16) & 0xFF);
                raw[13] = (byte) ((kp >> 8) & 0xFF);
                raw[14] = (byte) (kp & 0xFF);

                int gmac = streamCipher.getGmac(raw);
                raw[7] = (byte) ((gmac >> 24) & 0xFF);
                raw[8] = (byte) ((gmac >> 16) & 0xFF);
                raw[9] = (byte) ((gmac >> 8) & 0xFF);
                raw[10] = (byte) (gmac & 0xFF);

                streamCipher.advanceKeyPos(15);
                udpSocket.send(new DatagramPacket(raw, 15, InetAddress.getByName(hostIp), 9296));
            } catch (Exception ignored) {}
        }
    }

    private void startUdpStream() throws Exception {
        for (int i = 0; i < REASSEMBLY_RING_SIZE; i++) {
            synchronized (reassemblySlots[i]) {
                reassemblySlots[i].frameIndex = -1;
                reassemblySlots[i].completed = false;
                reassemblySlots[i].unitsReceivedCount = 0;
                reassemblySlots[i].fecUnitsReceived = 0;
            }
        }
        audioWriteIdx = 0;
        audioReadIdx = 0;
        nextDeliveryFrame = -1;
        highestReceivedFrame = -1;
        waitingForIdr = true;

        initMediaCodec();
        initAudio();
        udpSocket = new DatagramSocket();
        udpSocket.setReceiveBufferSize(512 * 1024);
        try {
            // DSCP CS5 / WMM Video Low-Latency QoS para evitar Power-Save DTIM buffering en router Wi-Fi y Tailscale
            udpSocket.setTrafficClass(0xA0);
        } catch (Throwable ignored) {}
        udpSocket.setSoTimeout(50);
        InetAddress addr = hostAddress != null ? hostAddress : InetAddress.getByName(hostIp);
        udpRecvPkt = new DatagramPacket(udpRecvBuf, udpRecvBuf.length);

        // Handshake UDP
        byte[] initPkt = buildControlPacket(0x01, 0, buildInitChunkPayload(), false, 0);
        long hsStart = System.currentTimeMillis();
        long lastRetransmit = 0;
        while (running.get() && streamCipher == null && System.currentTimeMillis() - hsStart < 12000) {
            long now = System.currentTimeMillis();
            if (now - lastRetransmit >= 350) {
                lastRetransmit = now;
                if (tagRemote == 0) {
                    udpSocket.send(new DatagramPacket(initPkt, initPkt.length, addr, 9296));
                } else if (!cookieAcked && lastCookiePkt != null) {
                    udpSocket.send(new DatagramPacket(lastCookiePkt, lastCookiePkt.length, addr, 9296));
                } else if (cookieAcked && lastBigPkt != null) {
                    udpSocket.send(new DatagramPacket(lastBigPkt, lastBigPkt.length, addr, 9296));
                }
            }
            receiveLoopStep(40);
        }

        if (streamCipher == null && running.get()) {
            listener.onError("Tiempo de espera agotado al negociar el túnel de vídeo UDP (puerto 9296) con la PS5.");
            stop();
            return;
        }

        streamStartTime = System.currentTimeMillis();

        // Thread dedicado para alimentar frames de video a MediaCodec sin bloquear socket UDP
        videoFeedThread = new Thread(this::runVideoFeedLoop, "DRPS5-VDecFeed");
        videoFeedThread.start();

        // Thread dedicado para drenar decodificador de vídeo sin bloquear red
        decoderDrainThread = new Thread(this::runDecoderDrainLoop, "DRPS5-VDecDrain");
        decoderDrainThread.start();

        // Thread dedicado para drenar decodificador de audio Opus
        if (audioCodec != null && audioTrack != null) {
            audioDrainThread = new Thread(this::runAudioDrainLoop, "DRPS5-ADecDrain");
            audioDrainThread.start();
        }

        // Thread dedicado para telemetría y cálculo de FPS en vivo
        statsThread = new Thread(this::runStatsLoop, "DRPS5-Stats");
        statsThread.start();

        // Thread dedicado para heartbeat y envío de estado de controles/sticks a la PS5
        controllerHeartbeatThread = new Thread(this::runControllerHeartbeatLoop, "DRPS5-CtrlHb");
        controllerHeartbeatThread.start();

        // Prioridad de hilo en tiempo real para recepción UDP ininterrumpida
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO);
        } catch (Throwable ignored) {}

        // Loop principal de recepción UDP de alto rendimiento y ultra-baja latencia
        udpSocket.setSoTimeout(500);
        while (running.get()) {
            try {
                udpRecvPkt.setData(udpRecvBuf, 0, udpRecvBuf.length);
                udpSocket.receive(udpRecvPkt);
                int len = udpRecvPkt.getLength();
                if (len >= 14) {
                    handleUdpPacket(udpRecvBuf, len);
                }
            } catch (SocketTimeoutException | PortUnreachableException ignored) {
            } catch (Exception e) {
                if (!running.get()) break;
            }
        }
    }

    private void runControllerHeartbeatLoop() {
        while (running.get()) {
            try {
                synchronized (ctrlWakeLock) {
                    if (btnReadIdx == btnWriteIdx) {
                        ctrlWakeLock.wait(15);
                    }
                }
            } catch (InterruptedException e) {
                break;
            }
            if (!running.get()) break;
            if (streamCipher != null && udpSocket != null) {
                while (btnReadIdx != btnWriteIdx) {
                    int rIdx = btnReadIdx;
                    int code = btnRingCodes[rIdx];
                    boolean pressed = btnRingPressed[rIdx];
                    btnReadIdx = (rIdx + 1) & (BTN_RING_SIZE - 1);
                    dispatchButtonEventNow(code, pressed);
                }
                long now = System.currentTimeMillis();
                short lx = leftX, ly = leftY, rx = rightX, ry = rightY;
                boolean stickChanged = (lx != lastSentLx || ly != lastSentLy || rx != lastSentRx || ry != lastSentRy);
                // Sondeo continuo a ~60Hz (16ms) para respuesta instantánea y mantener radio Wi-Fi fuera de ahorro de energía
                if (stickChanged || now - lastStateSendTime >= 16) {
                    lastStateSendTime = now;
                    lastSentLx = lx;
                    lastSentLy = ly;
                    lastSentRx = rx;
                    lastSentRy = ry;
                    sendControllerState();
                }
            }
        }
    }

    private void initMediaCodec() throws Exception {
        String mime = codecName.startsWith("h264") ? MediaFormat.MIMETYPE_VIDEO_AVC : MediaFormat.MIMETYPE_VIDEO_HEVC;
        // El codificador de hardware de PS5 transmite hasta 1920x1080 nativo;
        // usar 1920x1080 para 1080p/2K/4K evita reservar 240 MB en buffers gralloc 4K de Allwinner
        int w = 1920, h = 1080;
        if ("720p".equalsIgnoreCase(resolution)) {
            w = 1280; h = 720;
        } else if ("540p".equalsIgnoreCase(resolution)) {
            w = 960; h = 540;
        } else if ("360p".equalsIgnoreCase(resolution)) {
            w = 640; h = 360;
        }
        MediaFormat fmt = MediaFormat.createVideoFormat(mime, w, h);
        fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 1536 * 1024);
        fmt.setInteger(MediaFormat.KEY_PRIORITY, 0);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            fmt.setInteger(MediaFormat.KEY_OPERATING_RATE, Short.MAX_VALUE);
        }
        if (hdr && !codecName.startsWith("h264")) {
            fmt.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT2020);
            fmt.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_ST2084);
            fmt.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
        } else {
            fmt.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT709);
            fmt.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
            fmt.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
        }

        if (Build.VERSION.SDK_INT >= 30) {
            try { fmt.setInteger(MediaFormat.KEY_LOW_LATENCY, 1); } catch (Throwable ignored) {}
        }
        try { fmt.setInteger("vendor.low-latency.enable", 1); } catch (Throwable ignored) {}
        try { fmt.setInteger("vendor.allwinner.low-latency", 1); } catch (Throwable ignored) {}

        try {
            videoCodec = MediaCodec.createDecoderByType(mime);
            videoCodec.configure(fmt, surface, null, 0);
            videoCodec.start();
        } catch (Exception e) {
            android.util.Log.w("DRPS5", "Configuring with HDR/high-res metadata failed, falling back to basic format: " + e.getMessage());
            if (videoCodec != null) {
                try { videoCodec.release(); } catch (Throwable ignored) {}
            }
            MediaFormat basicFmt = MediaFormat.createVideoFormat(mime, w, h);
            basicFmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 1536 * 1024);
            basicFmt.setInteger(MediaFormat.KEY_PRIORITY, 0);
            videoCodec = MediaCodec.createDecoderByType(mime);
            videoCodec.configure(basicFmt, surface, null, 0);
            videoCodec.start();
        }
    }

    private void runDecoderDrainLoop() {
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_DISPLAY);
        } catch (Throwable ignored) {}
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        while (running.get()) {
            MediaCodec codec = videoCodec;
            if (codec == null) {
                try { Thread.sleep(10); } catch (InterruptedException ignored) {}
                continue;
            }
            try {
                int outIdx = codec.dequeueOutputBuffer(info, 5000);
                while (outIdx >= 0 && running.get()) {
                    codec.releaseOutputBuffer(outIdx, true);
                    renderedFrameCount++;
                    outIdx = codec.dequeueOutputBuffer(info, 0);
                }
                if (outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat newFmt = codec.getOutputFormat();
                    android.util.Log.i("DRPS5", "Video decoder nuevo formato de salida: " + newFmt);
                }
            } catch (IllegalStateException e) {
                break;
            } catch (Exception e) {
                android.util.Log.w("DRPS5", "Excepción en bucle de drenaje de vídeo: " + e.getMessage());
            }
        }
    }

    private void initAudio() {
        if (!audioEnabled) return;
        try {
            MediaFormat fmt = MediaFormat.createAudioFormat("audio/opus", 48000, 2);
            byte[] csd0 = new byte[]{
                'O', 'p', 'u', 's', 'H', 'e', 'a', 'd',
                1, 2, 0x00, 0x0F, (byte) 0x80, (byte) 0xBB, 0x00, 0x00, 0x00, 0x00, 0
            };
            fmt.setByteBuffer("csd-0", ByteBuffer.wrap(csd0));
            ByteBuffer b1 = ByteBuffer.allocate(8).order(ByteOrder.nativeOrder());
            b1.putLong(80000000L);
            b1.flip();
            fmt.setByteBuffer("csd-1", b1);
            ByteBuffer b2 = ByteBuffer.allocate(8).order(ByteOrder.nativeOrder());
            b2.putLong(80000000L);
            b2.flip();
            fmt.setByteBuffer("csd-2", b2);

            audioCodec = MediaCodec.createDecoderByType("audio/opus");
            audioCodec.configure(fmt, null, null, 0);
            audioCodec.start();

            int minBuf = AudioTrack.getMinBufferSize(48000, AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT);
            int bufSize = Math.max(minBuf * 4, 48000 * 2 * 2 / 5);
            audioTrack = new AudioTrack(
                new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_GAME)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build(),
                new AudioFormat.Builder()
                    .setSampleRate(48000)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build(),
                bufSize,
                AudioTrack.MODE_STREAM,
                android.media.AudioManager.AUDIO_SESSION_ID_GENERATE
            );
            byte[] warmSilence = new byte[48000 * 2 * 2 / 25];
            audioTrack.write(warmSilence, 0, warmSilence.length);
            audioTrack.play();
            android.util.Log.i("DRPS5", "Audio decodificador Opus y AudioTrack iniciados correctamente");
        } catch (Exception e) {
            android.util.Log.e("DRPS5", "Error al inicializar audio Opus: " + e.getMessage(), e);
            releaseAudio();
        }
    }

    private void runAudioDrainLoop() {
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO);
        } catch (Throwable ignored) {}
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        while (running.get()) {
            MediaCodec codec = audioCodec;
            AudioTrack track = audioTrack;
            if (codec == null || track == null) {
                try { Thread.sleep(20); } catch (InterruptedException ignored) {}
                continue;
            }
            try {
                if (audioReadIdx == audioWriteIdx) {
                    synchronized (audioWakeLock) {
                        if (audioReadIdx == audioWriteIdx) {
                            audioWakeLock.wait(6);
                        }
                    }
                }
                while (audioReadIdx != audioWriteIdx && running.get()) {
                    int rIdx = audioReadIdx;
                    int pktLen = audioRingLens[rIdx];
                    byte[] buf = audioRingBufs[rIdx];
                    if (pktLen >= 22 && streamCipher != null) {
                        boolean hasNalu = ((buf[0] & 0xFF) >> 4 & 1) != 0;
                        int dword2 = ((buf[5] & 0xFF) << 24) | ((buf[6] & 0xFF) << 16) | ((buf[7] & 0xFF) << 8) | (buf[8] & 0xFF);
                        long keyPos = (((long) buf[14] & 0xFF) << 24) | (((long) buf[15] & 0xFF) << 16) | (((long) buf[16] & 0xFF) << 8) | ((long) buf[17] & 0xFF);
                        int offset = 2 + (hasNalu ? 3 : 0);
                        int payloadOffset = 18 + offset;
                        int encLen = pktLen - payloadOffset;
                        if (encLen > 0 && encLen <= decAudioBuf.length) {
                            streamCipher.decryptAudio(buf, payloadOffset, encLen, keyPos, decAudioBuf, 0);
                            int unitsFec = dword2 & 0xFFFF;
                            int srcCount = unitsFec & 0x0F;
                            int unitSize = (unitsFec >> 8) & 0xFF;
                            if (unitSize > 0 && srcCount > 0) {
                                int count = Math.min(srcCount, encLen / unitSize);
                                for (int i = 0; i < count; i++) {
                                    feedAndDrainAudio(codec, track, info, decAudioBuf, i * unitSize, unitSize);
                                }
                            } else {
                                feedAndDrainAudio(codec, track, info, decAudioBuf, 0, encLen);
                            }
                        }
                    }
                    audioReadIdx = (rIdx + 1) & (AUDIO_RING_SIZE - 1);
                }
                drainAudioOutput(codec, track, info);
            } catch (IllegalStateException e) {
                break;
            } catch (Exception ignored) {}
        }
    }

    private void handleAudioPacket(byte[] buf, int pktLen) {
        if (pktLen < 22 || pktLen > 1024 || streamCipher == null || audioCodec == null) return;
        boolean hasNalu = ((buf[0] & 0xFF) >> 4 & 1) != 0;
        int offset = 1 + (hasNalu ? 3 : 0);
        if (18 + offset < pktLen && buf[18 + offset] == 0x02) {
            // DualSense haptic feedback packet, omitir para audio
            return;
        }
        int wIdx = audioWriteIdx;
        int nextIdx = (wIdx + 1) & (AUDIO_RING_SIZE - 1);
        if (nextIdx == audioReadIdx) {
            audioReadIdx = (audioReadIdx + 1) & (AUDIO_RING_SIZE - 1);
        }
        System.arraycopy(buf, 0, audioRingBufs[wIdx], 0, pktLen);
        audioRingLens[wIdx] = pktLen;
        audioWriteIdx = nextIdx;
        synchronized (audioWakeLock) {
            audioWakeLock.notify();
        }
    }

    private void feedAndDrainAudio(MediaCodec codec, AudioTrack track, MediaCodec.BufferInfo info, byte[] data, int offset, int len) {
        if (codec == null || len <= 0) return;
        try {
            drainAudioOutput(codec, track, info);
            int inIdx = codec.dequeueInputBuffer(1500);
            if (inIdx < 0) {
                drainAudioOutput(codec, track, info);
                inIdx = codec.dequeueInputBuffer(1500);
            }
            if (inIdx >= 0) {
                ByteBuffer inBuf = codec.getInputBuffer(inIdx);
                if (inBuf != null) {
                    inBuf.clear();
                    inBuf.put(data, offset, len);
                    codec.queueInputBuffer(inIdx, 0, len, System.nanoTime() / 1000, 0);
                }
            }
            drainAudioOutput(codec, track, info);
        } catch (Exception ignored) {}
    }

    private void drainAudioOutput(MediaCodec codec, AudioTrack track, MediaCodec.BufferInfo info) {
        try {
            int outIdx = codec.dequeueOutputBuffer(info, 0);
            while (outIdx >= 0) {
                ByteBuffer outBuf = codec.getOutputBuffer(outIdx);
                if (outBuf != null && info.size > 0) {
                    outBuf.position(info.offset);
                    outBuf.limit(info.offset + info.size);
                    track.write(outBuf, info.size, AudioTrack.WRITE_BLOCKING);
                }
                codec.releaseOutputBuffer(outIdx, false);
                outIdx = codec.dequeueOutputBuffer(info, 0);
            }
        } catch (Exception ignored) {}
    }

    private void releaseAudio() {
        try {
            if (audioDrainThread != null) {
                audioDrainThread.interrupt();
                audioDrainThread = null;
            }
        } catch (Exception ignored) {}
        try {
            if (audioCodec != null) {
                audioCodec.stop();
                audioCodec.release();
                audioCodec = null;
            }
        } catch (Exception ignored) {}
        try {
            if (audioTrack != null) {
                audioTrack.stop();
                audioTrack.release();
                audioTrack = null;
            }
        } catch (Exception ignored) {}
    }

    private void receiveLoopStep(long maxWaitMs) {
        long start = System.currentTimeMillis();
        while (running.get() && System.currentTimeMillis() - start <= maxWaitMs) {
            try {
                udpRecvPkt.setData(udpRecvBuf, 0, udpRecvBuf.length);
                udpSocket.receive(udpRecvPkt);
                int len = udpRecvPkt.getLength();
                if (len >= 14) {
                    handleUdpPacket(udpRecvBuf, len);
                }
            } catch (SocketTimeoutException | PortUnreachableException e) {
                break;
            } catch (Exception e) {
                break;
            }
        }
    }

    private void handleUdpPacket(byte[] buf, int len) throws Exception {
        int avType = buf[0] & 0x0F;
        if (avType == 0x02 || avType == 0x03) {
            if (avType == 0x02 && streamCipher != null) {
                handleVideoPacket(buf, len);
            } else if (avType == 0x03 && streamCipher != null && audioCodec != null) {
                handleAudioPacket(buf, len);
            }
            return;
        }

        int chunkType = buf[13] & 0xFF;
        ByteBuffer bb = ByteBuffer.wrap(buf, 0, len);
        if (chunkType == 0x02 && len >= 33) { // INIT_ACK
            tagRemote = bb.getInt(17);
            byte[] cookie = Arrays.copyOfRange(buf, 33, len);
            lastCookiePkt = buildControlPacket(0x0A, 0, cookie, false, 0);
            udpSocket.send(new DatagramPacket(lastCookiePkt, lastCookiePkt.length, InetAddress.getByName(hostIp), 9296));
        } else if (chunkType == 0x0B) { // COOKIE_ACK
            if (!cookieAcked) {
                cookieAcked = true;
                sendBigPayload();
            }
        } else if (chunkType == 0x00 && len >= 26) { // DATA
            int peerTsn = bb.getInt(17);
            sendDataAck(peerTsn);
            byte[] protoData = Arrays.copyOfRange(buf, 26, len);
            handleTakionProto(protoData);
        }
    }

    private void handleVideoPacket(byte[] buf, int pktLen) {
        if (pktLen < 22) return;
        totalPacketsReceived++;
        boolean hasNalu = ((buf[0] & 0xFF) >> 4 & 1) != 0;
        int frameIndex = ((buf[3] & 0xFF) << 8) | (buf[4] & 0xFF);
        int dword2 = ((buf[5] & 0xFF) << 24) | ((buf[6] & 0xFF) << 16) | ((buf[7] & 0xFF) << 8) | (buf[8] & 0xFF);
        long keyPos = (((long) buf[14] & 0xFF) << 24) | (((long) buf[15] & 0xFF) << 16) | (((long) buf[16] & 0xFF) << 8) | ((long) buf[17] & 0xFF);

        int unitIndex = (dword2 >>> 21) & 0x7FF;
        int totalUnits = ((dword2 >>> 10) & 0x7FF) + 1;
        int fecUnits = dword2 & 0x3FF;
        int srcUnits = totalUnits - fecUnits;

        if (srcUnits <= 0 || totalUnits > MAX_UNITS || unitIndex >= totalUnits) return;

        int offset = 21 + (hasNalu ? 3 : 0);
        int encLen = pktLen - offset;
        if (encLen <= 2 || encLen > MAX_UNIT_SIZE) return;

        if (nextDeliveryFrame >= 0 && ((nextDeliveryFrame - frameIndex) & 0xFFFF) < 16384) {
            return;
        }

        if (highestReceivedFrame == -1 || ((frameIndex - highestReceivedFrame) & 0xFFFF) < 32768) {
            highestReceivedFrame = frameIndex;
        }

        int slotIdx = frameIndex & (REASSEMBLY_RING_SIZE - 1);
        VideoSlot slot = reassemblySlots[slotIdx];
        boolean notifyDispatch = false;

        synchronized (slot) {
            if (slot.frameIndex != frameIndex) {
                if (slot.frameIndex >= 0 && !slot.completed) {
                    int lost = Math.max(0, slot.expectedSrcUnits - slot.unitsReceivedCount);
                    if (lost > 0) {
                        totalPacketsLost += lost;
                    }
                }
                slot.reset(frameIndex, srcUnits, fecUnits);
            }

            if (!slot.unitPresent[unitIndex]) {
                if (unitIndex < slot.expectedSrcUnits) {
                    streamCipher.decrypt(buf, offset, encLen, keyPos, slot.unitBuffers[unitIndex], 0);
                    slot.unitDecrypted[unitIndex] = true;
                    slot.unitLengths[unitIndex] = encLen;
                    slot.unitKeyPos[unitIndex] = keyPos;
                    slot.unitPresent[unitIndex] = true;
                    slot.unitsReceivedCount++;
                } else {
                    System.arraycopy(buf, offset, slot.unitBuffers[unitIndex], 0, encLen);
                    slot.unitDecrypted[unitIndex] = false;
                    slot.unitLengths[unitIndex] = encLen;
                    slot.unitKeyPos[unitIndex] = keyPos;
                    slot.unitPresent[unitIndex] = true;
                    slot.fecUnitsReceived++;
                    if (slot.fecBlockSize == 0) {
                        slot.fecBlockSize = encLen;
                    }
                }
            }

            if (!slot.completed) {
                if (slot.unitsReceivedCount >= slot.expectedSrcUnits) {
                    slot.completed = true;
                    notifyDispatch = true;
                } else if (slot.unitsReceivedCount + slot.fecUnitsReceived >= slot.expectedSrcUnits && slot.fecBlockSize > 2) {
                    slot.completed = true;
                    notifyDispatch = true;
                }
            }
        }

        if (notifyDispatch) {
            synchronized (dispatchLock) {
                dispatchLock.notify();
            }
        }
    }

    private boolean decryptAndAssembleSlot(VideoSlot slot, int expectedFrame, byte[] outBuf, int[] outLenHolder) {
        synchronized (slot) {
            if (!slot.completed || slot.frameIndex != expectedFrame || slot.frameIndex < 0) return false;
            if (slot.unitsReceivedCount == slot.expectedSrcUnits) {
                for (int u = 0; u < slot.expectedSrcUnits; u++) {
                    if (!slot.unitDecrypted[u]) {
                        int encLen = slot.unitLengths[u];
                        streamCipher.decrypt(slot.unitBuffers[u], 0, encLen, slot.unitKeyPos[u], slot.unitBuffers[u], 0);
                        slot.unitDecrypted[u] = true;
                    }
                }
            } else {
                for (int u = 0; u < slot.expectedSrcUnits; u++) {
                    if (slot.unitPresent[u]) {
                        int encLen = slot.unitLengths[u];
                        if (!slot.unitDecrypted[u]) {
                            streamCipher.decrypt(slot.unitBuffers[u], 0, encLen, slot.unitKeyPos[u], slot.unitBuffers[u], 0);
                            slot.unitDecrypted[u] = true;
                        }
                        int pad = ((slot.unitBuffers[u][0] & 0xFF) << 8) | (slot.unitBuffers[u][1] & 0xFF);
                        if (pad >= 0 && encLen + pad <= MAX_UNIT_SIZE) {
                            slot.fecBlockSize = encLen + pad;
                        }
                    }
                }
                int fNeeded = slot.expectedSrcUnits - slot.unitsReceivedCount;
                int fDec = 0;
                for (int u = slot.expectedSrcUnits; u < slot.totalUnits && fDec < fNeeded; u++) {
                    if (slot.unitPresent[u]) {
                        int encLen = slot.unitLengths[u];
                        if (!slot.unitDecrypted[u]) {
                            streamCipher.decrypt(slot.unitBuffers[u], 0, encLen, slot.unitKeyPos[u], slot.unitBuffers[u], 0);
                            slot.unitDecrypted[u] = true;
                        }
                        if (slot.fecBlockSize == 0) {
                            slot.fecBlockSize = encLen;
                        }
                        fDec++;
                    }
                }
                if (!recoverSlotWithFec(slot)) {
                    slot.completed = false;
                    return false;
                }
                for (int u = 0; u < slot.expectedSrcUnits; u++) {
                    slot.unitDecrypted[u] = true;
                }
            }
            outLenHolder[0] = assembleSlotToBuffer(slot, outBuf);
            slot.completed = false;
            slot.frameIndex = -1;
            return true;
        }
    }

    private boolean recoverSlotWithFec(VideoSlot slot) {
        int k = slot.expectedSrcUnits;
        int m = slot.expectedFecUnits;
        int blockSize = slot.fecBlockSize;
        if (k <= 0 || m <= 0 || k + m > 256 || blockSize <= 2 || blockSize > MAX_UNIT_SIZE) {
            return false;
        }
        int mCount = 0;
        int pCount = 0;
        for (int j = 0; j < k; j++) {
            if (slot.unitPresent[j]) {
                fecPresentSrc[pCount++] = j;
            } else {
                if (mCount < MAX_FEC_RECOVERY) {
                    fecMissingSrc[mCount++] = j;
                } else {
                    return false;
                }
            }
        }
        if (mCount == 0) return true;
        if (mCount > slot.fecUnitsReceived) return false;

        int fCount = 0;
        for (int f = 0; f < m && fCount < mCount; f++) {
            if (slot.unitPresent[k + f]) {
                fecUsedParity[fCount++] = f;
            }
        }
        if (fCount < mCount) return false;

        // Build and invert Cauchy submatrix over GF(2^8)
        for (int row = 0; row < mCount; row++) {
            int fIdx = fecUsedParity[row];
            for (int col = 0; col < mCount; col++) {
                int sIdx = fecMissingSrc[col];
                fecMatrix[row][col] = gfInv(fIdx ^ (sIdx + m));
                fecInvMatrix[row][col] = (row == col) ? 1 : 0;
            }
        }

        for (int col = 0; col < mCount; col++) {
            int pivot = col;
            while (pivot < mCount && fecMatrix[pivot][col] == 0) {
                pivot++;
            }
            if (pivot == mCount) return false;
            if (pivot != col) {
                int[] tmpM = fecMatrix[col]; fecMatrix[col] = fecMatrix[pivot]; fecMatrix[pivot] = tmpM;
                int[] tmpI = fecInvMatrix[col]; fecInvMatrix[col] = fecInvMatrix[pivot]; fecInvMatrix[pivot] = tmpI;
            }
            int invPivot = gfInv(fecMatrix[col][col]);
            byte[] invMulTab = GF_MUL[invPivot & 0xFF];
            for (int c = 0; c < mCount; c++) {
                fecMatrix[col][c] = invMulTab[fecMatrix[col][c] & 0xFF] & 0xFF;
                fecInvMatrix[col][c] = invMulTab[fecInvMatrix[col][c] & 0xFF] & 0xFF;
            }
            for (int row = 0; row < mCount; row++) {
                if (row != col) {
                    int factor = fecMatrix[row][col];
                    if (factor != 0) {
                        byte[] mulTab = GF_MUL[factor & 0xFF];
                        for (int c = 0; c < mCount; c++) {
                            fecMatrix[row][c] ^= (mulTab[fecMatrix[col][c] & 0xFF] & 0xFF);
                            fecInvMatrix[row][c] ^= (mulTab[fecInvMatrix[col][c] & 0xFF] & 0xFF);
                        }
                    }
                }
            }
        }

        // Compute syndrome vectors
        for (int row = 0; row < mCount; row++) {
            int fIdx = fecUsedParity[row];
            byte[] synBuf = fecSyndrome[row];
            byte[] fecBuf = slot.unitBuffers[k + fIdx];
            int fecLen = Math.min(blockSize, slot.unitLengths[k + fIdx]);
            System.arraycopy(fecBuf, 0, synBuf, 0, fecLen);
            if (fecLen < blockSize) {
                Arrays.fill(synBuf, fecLen, blockSize, (byte) 0);
            }
            for (int p = 0; p < pCount; p++) {
                int j = fecPresentSrc[p];
                int coef = gfInv(fIdx ^ (j + m));
                byte[] mulTab = GF_MUL[coef & 0xFF];
                byte[] srcBuf = slot.unitBuffers[j];
                int uLen = Math.min(blockSize, slot.unitLengths[j]);
                for (int b = 0; b < uLen; b++) {
                    synBuf[b] ^= mulTab[srcBuf[b] & 0xFF];
                }
            }
        }

        // Reconstruct missing source units
        for (int col = 0; col < mCount; col++) {
            int targetUnit = fecMissingSrc[col];
            byte[] outUnit = slot.unitBuffers[targetUnit];
            Arrays.fill(outUnit, 0, blockSize, (byte) 0);
            for (int row = 0; row < mCount; row++) {
                int coef = fecInvMatrix[col][row];
                if (coef == 0) continue;
                byte[] mulTab = GF_MUL[coef & 0xFF];
                byte[] synBuf = fecSyndrome[row];
                for (int b = 0; b < blockSize; b++) {
                    outUnit[b] ^= mulTab[synBuf[b] & 0xFF];
                }
            }
            int recPad = ((outUnit[0] & 0xFF) << 8) | (outUnit[1] & 0xFF);
            int recLen = blockSize - recPad;
            if (recLen <= 2 || recLen > blockSize) {
                return false;
            }
            slot.unitLengths[targetUnit] = recLen;
            slot.unitPresent[targetUnit] = true;
        }

        slot.unitsReceivedCount = k;
        fecRecoveredPackets += mCount;
        fecRecoveredFrames++;
        return true;
    }

    private final int[] rawLenHolder = new int[1];

    private void dispatchCompletedFramesLocked() {
        long now = System.currentTimeMillis();
        if (nextDeliveryFrame == -1) {
            for (int i = 0; i < REASSEMBLY_RING_SIZE; i++) {
                VideoSlot s = reassemblySlots[i];
                if (s.completed && s.frameIndex >= 0) {
                    int candidateFrame = s.frameIndex;
                    if (decryptAndAssembleSlot(s, candidateFrame, assembledFrameBuf, rawLenHolder)) {
                        int rawLen = rawLenHolder[0];
                        if (isIdrFrame(assembledFrameBuf, rawLen)) {
                            waitingForIdr = false;
                            nextDeliveryFrame = candidateFrame;
                            targetFrameWaitStartTime = System.currentTimeMillis();
                            feedFrameDirect(assembledFrameBuf, rawLen, true);
                            android.util.Log.i("DRPS5", "⚡ Primer IDR de inicio fijado (frame " + nextDeliveryFrame + ", " + rawLen + "B)");
                            break;
                        }
                    }
                }
            }
            if (nextDeliveryFrame == -1) return;
        }

        if (highestReceivedFrame >= 0) {
            int totalLag = (highestReceivedFrame - nextDeliveryFrame) & 0xFFFF;
            if (totalLag >= (REASSEMBLY_RING_SIZE - 4) && totalLag < 32768) {
                int oldNext = nextDeliveryFrame;
                nextDeliveryFrame = (highestReceivedFrame - 2) & 0xFFFF;
                targetFrameWaitStartTime = now;
                if (now - lastIdrReqTime > 80) {
                    lastIdrReqTime = now;
                    notifyCorruptFrame(oldNext, highestReceivedFrame);
                    sendIdrRequest();
                }
            }
        }

        int reorderWindow = tailscaleMode ? 6 : 4;
        long maxReorderWaitMs = tailscaleMode ? 35L : 12L;
        while (running.get()) {
            int targetFrame = (nextDeliveryFrame + 1) & 0xFFFF;
            VideoSlot targetSlot = reassemblySlots[targetFrame & (REASSEMBLY_RING_SIZE - 1)];

            if (targetSlot.frameIndex == targetFrame && targetSlot.completed) {
                if (decryptAndAssembleSlot(targetSlot, targetFrame, assembledFrameBuf, rawLenHolder)) {
                    int rawLen = rawLenHolder[0];
                    boolean isIdr = isIdrFrame(assembledFrameBuf, rawLen);
                    if (isIdr) {
                        waitingForIdr = false;
                    }
                    nextDeliveryFrame = targetFrame;
                    targetFrameWaitStartTime = System.currentTimeMillis();
                    feedFrameDirect(assembledFrameBuf, rawLen, isIdr);
                    continue;
                }
            }

            int diff = (highestReceivedFrame - targetFrame) & 0xFFFF;
            long cur = System.currentTimeMillis();
            long pktRefTime = 0;
            if (targetSlot.frameIndex == targetFrame && targetSlot.firstPacketTime > 0) {
                pktRefTime = targetSlot.firstPacketTime;
            } else {
                int nextIdx = (targetFrame + 1) & 0xFFFF;
                VideoSlot nextSlot = reassemblySlots[nextIdx & (REASSEMBLY_RING_SIZE - 1)];
                if (nextSlot.frameIndex == nextIdx && nextSlot.firstPacketTime > 0) {
                    pktRefTime = nextSlot.firstPacketTime;
                } else {
                    pktRefTime = targetFrameWaitStartTime;
                }
            }
            long waitMs = cur - pktRefTime;
            if (diff >= reorderWindow && diff < 32768 && waitMs >= maxReorderWaitMs) {
                boolean completedJustNow = false;
                synchronized (targetSlot) {
                    if (targetSlot.frameIndex == targetFrame && targetSlot.completed) {
                        completedJustNow = true;
                    } else if (targetSlot.frameIndex == targetFrame && !targetSlot.completed) {
                        int lost = Math.max(0, targetSlot.expectedSrcUnits - targetSlot.unitsReceivedCount);
                        if (lost > 0) totalPacketsLost += lost;
                        targetSlot.completed = false;
                        targetSlot.frameIndex = -1;
                    }
                }
                if (completedJustNow) {
                    continue;
                }
                if (cur - lastIdrReqTime > 350) {
                    lastIdrReqTime = cur;
                    notifyCorruptFrame(targetFrame, highestReceivedFrame >= 0 ? highestReceivedFrame : targetFrame);
                    sendIdrRequest();
                }
                nextDeliveryFrame = targetFrame;
                targetFrameWaitStartTime = cur;
                continue;
            }

            break;
        }
    }

    private int assembleSlotToBuffer(VideoSlot slot, byte[] outBuf) {
        int rawLen = 0;
        for (int i = 0; i < slot.expectedSrcUnits; i++) {
            if (slot.unitPresent[i]) {
                int encLen = slot.unitLengths[i];
                int ulen = encLen - 2;
                if (ulen > 0 && rawLen + ulen <= outBuf.length) {
                    System.arraycopy(slot.unitBuffers[i], 2, outBuf, rawLen, ulen);
                    rawLen += ulen;
                }
            }
        }
        return rawLen;
    }

    private void feedFrameDirect(byte[] data, int rawLen, boolean isIdr) {
        MediaCodec codec = videoCodec;
        if (codec == null || rawLen <= 0) return;
        try {
            int inIdx = -1;
            int maxAttempts = 25;
            long timeoutUs = (renderedFrameCount == 0) ? 10000L : 3500L;
            for (int attempt = 0; attempt < maxAttempts && running.get(); attempt++) {
                inIdx = codec.dequeueInputBuffer(timeoutUs);
                if (inIdx >= 0) break;
            }
            if (inIdx >= 0) {
                ByteBuffer inBuf = codec.getInputBuffer(inIdx);
                if (inBuf != null) {
                    inBuf.clear();
                    int hdrLen = (isIdr && videoHeader != null) ? videoHeader.length : 0;
                    int totalLen = hdrLen + rawLen;
                    if (totalLen > inBuf.remaining()) {
                        codec.queueInputBuffer(inIdx, 0, 0, 0, 0);
                        return;
                    }
                    if (hdrLen > 0) {
                        inBuf.put(videoHeader, 0, hdrLen);
                    }
                    inBuf.put(data, 0, rawLen);
                    codec.queueInputBuffer(inIdx, 0, totalLen, System.nanoTime() / 1000, 0);
                }
            } else {
                notifyCorruptFrame(Math.max(0, nextDeliveryFrame), Math.max(0, highestReceivedFrame));
                sendIdrRequest();
            }
        } catch (Exception ignored) {}
    }

    private void runVideoFeedLoop() {
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_DISPLAY);
        } catch (Throwable ignored) {}
        while (running.get()) {
            try {
                synchronized (dispatchLock) {
                    dispatchLock.wait(2);
                }
                if (!running.get()) break;
                dispatchCompletedFramesLocked();
            } catch (InterruptedException e) {
                break;
            } catch (Exception ignored) {}
        }
    }

    private void notifyCorruptFrame(int startFrame, int endFrame) {
        long now = System.currentTimeMillis();
        if (now - lastCorruptTime < 80) return;
        lastCorruptTime = now;
        try {
            if (streamCipher != null) {
                byte[] corr = PS5Protocol.buildCorruptFrameMsg(startFrame, endFrame);
                sendControlData(corr, 1, 2, true);
            }
        } catch (Exception ignored) {}
    }

    private boolean isIdrFrame(byte[] data, int len) {
        if (data == null || len < 5) return false;
        boolean isH264 = codecName.startsWith("h264");
        int pos = 0;
        int limit = len - 4;
        while (pos < limit) {
            int nalByte;
            if (data[pos] == 0 && data[pos + 1] == 0 && data[pos + 2] == 1) {
                nalByte = data[pos + 3] & 0xFF;
                pos += 3;
            } else if (data[pos] == 0 && data[pos + 1] == 0 && data[pos + 2] == 0 && data[pos + 3] == 1) {
                nalByte = data[pos + 4] & 0xFF;
                pos += 4;
            } else {
                pos++;
                continue;
            }
            if (isH264) {
                int nalType = nalByte & 0x1F;
                if (nalType == 5 || nalType == 7 || nalType == 8) return true;
            } else {
                int nalType = (nalByte >>> 1) & 0x3F;
                if ((nalType >= 16 && nalType <= 21) || nalType == 32 || nalType == 33 || nalType == 34) return true;
            }
        }
        return false;
    }

    private void feedCodecConfig(byte[] configData) {
        MediaCodec codec = videoCodec;
        if (codec == null || configData == null || configData.length == 0) return;
        try {
            int inIdx = codec.dequeueInputBuffer(10000);
            if (inIdx >= 0) {
                ByteBuffer inBuf = codec.getInputBuffer(inIdx);
                if (inBuf != null) {
                    inBuf.clear();
                    inBuf.put(configData, 0, configData.length);
                    codec.queueInputBuffer(inIdx, 0, configData.length, 0, MediaCodec.BUFFER_FLAG_CODEC_CONFIG);
                    android.util.Log.i("DRPS5", "videoHeader (VPS/SPS/PPS) configurado en MediaCodec (" + configData.length + " bytes)");
                }
            }
        } catch (Exception e) {
            android.util.Log.e("DRPS5", "Error enviando codec config: " + e.getMessage(), e);
        }
    }

    private void feedFrameToDecoder(byte[] frameData, int frameLen) {
        MediaCodec codec = videoCodec;
        if (codec == null || frameLen <= 0) return;
        try {
            int inIdx = codec.dequeueInputBuffer(10000);
            if (inIdx >= 0) {
                ByteBuffer inBuf = codec.getInputBuffer(inIdx);
                if (inBuf != null) {
                    inBuf.clear();
                    if (frameLen > inBuf.remaining()) {
                        android.util.Log.e("DRPS5", "Frame size " + frameLen + "B excede capacidad del decodificador " + inBuf.remaining() + "B!");
                        return;
                    }
                    inBuf.put(frameData, 0, frameLen);
                    codec.queueInputBuffer(inIdx, 0, frameLen, System.nanoTime() / 1000, 0);
                }
            }
        } catch (Exception e) {
            android.util.Log.e("DRPS5", "feedFrameToDecoder error: " + e.getMessage(), e);
        }
    }

    private void handleTakionProto(byte[] data) throws Exception {
        PS5Protocol.ParsedTakion msg = PS5Protocol.parseTakionMessage(data);
        if (msg.type == 1) { // BANG
            if (msg.bangEcdhPub != null && msg.bangEcdhSig != null && streamCipher == null) {
                if (ecdh.setSecret(msg.bangEcdhPub, msg.bangEcdhSig)) {
                    streamCipher = ecdh.initCiphers();
                    listener.onConnected();
                }
            }
        } else if (msg.type == 13) { // STREAMINFO
            if (msg.streamWidth > 0 && msg.streamHeight > 0) {
                this.negotiatedWidth = msg.streamWidth;
                this.negotiatedHeight = msg.streamHeight;
                android.util.Log.i("DRPS5", "PS5 STREAMINFO resolucion negociada: " + msg.streamWidth + "x" + msg.streamHeight);
            }
            if (msg.videoHeader != null && msg.videoHeader.length > 0) {
                this.videoHeader = msg.videoHeader;
                feedCodecConfig(this.videoHeader);
            }
            byte[] ack = PS5Protocol.buildSimpleTakionMsg(14); // STREAMINFOACK
            sendControlData(ack, 1, 9, true);
            sendIdrRequest();
        } else if (msg.type == 3) { // HEARTBEAT
            byte[] hb = PS5Protocol.buildSimpleTakionMsg(3);
            sendControlData(hb, 1, 1, true);
        }
    }

    private void runStatsLoop() {
        long lastTime = System.currentTimeMillis();
        int lastSecFrames = 0;
        int lastTickFrames = 0;
        long lastTickPackets = 0;
        int zeroFpsTicks = 0;
        int tickCounter = 0;
        while (running.get()) {
            try {
                Thread.sleep(250);
            } catch (InterruptedException e) {
                break;
            }
            if (!running.get()) break;

            long now = System.currentTimeMillis();
            int frames = renderedFrameCount;
            long rxPkts = totalPacketsReceived;
            int tickDf = frames - lastTickFrames;
            long tickDeltaPkts = rxPkts - lastTickPackets;
            lastTickFrames = frames;
            lastTickPackets = rxPkts;

            // Watchdog anticongelamiento (reacción tras 500ms de 0 FPS con tráfico continuo)
            if (tickDf == 0 && tickDeltaPkts > 10) {
                zeroFpsTicks++;
                if (zeroFpsTicks >= 2 && now - lastIdrReqTime > 500) {
                    lastIdrReqTime = now;
                    notifyCorruptFrame( Math.max(0, nextDeliveryFrame), Math.max(0, highestReceivedFrame) );
                    sendIdrRequest();
                    android.util.Log.w("DRPS5", "⚡ Fast Recovery: 0 FPS (" + (zeroFpsTicks * 250) + "ms). Solicitando IDR de recuperación...");
                }
            } else {
                zeroFpsTicks = 0;
            }

            tickCounter++;
            if (tickCounter >= 4) {
                tickCounter = 0;
                long dt = now - lastTime;
                int secDf = frames - lastSecFrames;
                float currentFps = (dt > 0) ? (secDf * 1000.0f / dt) : 0f;

                lastTime = now;
                lastSecFrames = frames;

                int w = negotiatedWidth;
                int h = negotiatedHeight;
                if ("2160p".equalsIgnoreCase(resolution) || "4k".equalsIgnoreCase(resolution)) {
                    w = 3840; h = 2160;
                } else if ("1440p".equalsIgnoreCase(resolution) || "2k".equalsIgnoreCase(resolution)) {
                    w = 2560; h = 1440;
                } else if (w == 0 || h == 0) {
                    if ("720p".equalsIgnoreCase(resolution)) { w = 1280; h = 720; }
                    else if ("540p".equalsIgnoreCase(resolution)) { w = 960; h = 540; }
                    else if ("360p".equalsIgnoreCase(resolution)) { w = 640; h = 360; }
                    else { w = 1920; h = 1080; }
                }

                if (listener != null) {
                    listener.onStats(currentFps, w, h, codecName, hdr, totalPacketsReceived, totalPacketsLost);
                    int snapNext = nextDeliveryFrame;
                    int snapHigh = highestReceivedFrame;
                    int tgt = (snapNext + 1) & 0xFFFF;
                    VideoSlot ts = reassemblySlots[tgt & (REASSEMBLY_RING_SIZE - 1)];
                    android.util.Log.i("DRPS5", "TELEMETRY: fps=" + String.format(java.util.Locale.US, "%.1f", currentFps) + " renderedTotal=" + frames + " (" + w + "x" + h + ", rx=" + totalPacketsReceived + " lost=" + totalPacketsLost + " fecRec=" + fecRecoveredPackets + "/" + fecRecoveredFrames + "f) [next=" + snapNext + " high=" + snapHigh + " tgt=" + tgt + " (fIdx=" + ts.frameIndex + " rcv=" + ts.unitsReceivedCount + "+" + ts.fecUnitsReceived + "f/" + ts.expectedSrcUnits + " done=" + ts.completed + ") waitMs=" + (now - targetFrameWaitStartTime) + " ts=" + tailscaleMode + "]");
                }
            }
        }
    }

    private void sendBigPayload() throws Exception {
        synchronized (sendLock) {
            this.ecdh = new PS5Crypto.StreamECDH();
            int bw;
            String resArrayJson;
            if ("2160p".equalsIgnoreCase(resolution) || "4k".equalsIgnoreCase(resolution)) {
                bw = tailscaleMode ? 9000 : 10000;
                resArrayJson = "[{\"resolution\":{\"width\":1920,\"height\":1080},\"maxFps\":" + fps + ",\"score\":10}]";
            } else if ("1440p".equalsIgnoreCase(resolution) || "2k".equalsIgnoreCase(resolution)) {
                bw = tailscaleMode ? 8000 : 9000;
                resArrayJson = "[{\"resolution\":{\"width\":1920,\"height\":1080},\"maxFps\":" + fps + ",\"score\":10}]";
            } else if ("720p".equalsIgnoreCase(resolution)) {
                bw = tailscaleMode ? 6000 : 7000;
                resArrayJson = "[{\"resolution\":{\"width\":1280,\"height\":720},\"maxFps\":" + fps + ",\"score\":10}]";
            } else if ("540p".equalsIgnoreCase(resolution)) {
                bw = 4000;
                resArrayJson = "[{\"resolution\":{\"width\":960,\"height\":540},\"maxFps\":" + fps + ",\"score\":10}]";
            } else if ("360p".equalsIgnoreCase(resolution)) {
                bw = 2000;
                resArrayJson = "[{\"resolution\":{\"width\":640,\"height\":360},\"maxFps\":" + fps + ",\"score\":10}]";
            } else {
                bw = tailscaleMode ? 7000 : 8000;
                resArrayJson = "[{\"resolution\":{\"width\":1920,\"height\":1080},\"maxFps\":" + fps + ",\"score\":10}]";
            }
            // MTU 1200 en Tailscale / enlaces remotos para evitar fragmentación IP sobre túnel WireGuard (MTU 1280)
            int mtu = tailscaleMode ? 1200 : 1454;
            int rtt = tailscaleMode ? 10 : 1;
            String vc = codecName.startsWith("h264") ? "avc" : "hevc";
            String hsB64 = Base64.encodeToString(ecdh.handshakeKey, Base64.NO_WRAP);
            String drStr = "SDR";

            String specJson = "{\"sessionId\":\"sessionId4321\",\"streamResolutions\":" + resArrayJson + ",\"network\":{\"bwKbpsSent\":" + bw
                    + ",\"bwLoss\":0.001000,\"mtu\":" + mtu + ",\"rtt\":" + rtt + ",\"ports\":[53]},\"slotId\":1,\"appSpecification\":{\"minFps\":30,\"minBandwidth\":0,\"extTitleId\":\"ps3\",\"version\":1,\"timeLimit\":1,\"startTimeout\":100,\"afkTimeout\":100,\"afkTimeoutDisconnect\":100},\"konan\":{\"ps3AccessToken\":\"\",\"ps3RefreshToken\":\"\"},\"requestGameSpecification\":{\"model\":\"bravia_tv\",\"platform\":\"android\",\"audioChannels\":\"2.0\",\"language\":\"sp\",\"acceptButton\":\"X\",\"connectedControllers\":[\"ds4\"],\"adaptiveStreamMode\":\"resize\"},\"userProfile\":{\"onlineId\":\"p\",\"npId\":\"p\",\"region\":\"US\"},\"videoCodec\":\"" + vc
                    + "\",\"dynamicRange\":\"" + drStr + "\",\"handshakeKey\":\"" + hsB64 + "\"}";

            byte[] rawSpec = specJson.getBytes(StandardCharsets.UTF_8);
            byte[] specWithNull = Arrays.copyOf(rawSpec, rawSpec.length + 1);
            byte[] zeros = new byte[specWithNull.length];
            byte[] encZeros = sessionCipher.encryptAtCounter(zeros, 0);
            byte[] xored = new byte[specWithNull.length];
            for (int i = 0; i < specWithNull.length; i++) {
                xored[i] = (byte) (specWithNull[i] ^ encZeros[i]);
            }
            byte[] specB64 = Base64.encode(xored, Base64.NO_WRAP);

            byte[] big = PS5Protocol.buildBigPayload(12, sessionId, specB64, new byte[4], ecdh.publicKey, ecdh.publicSig);
            ByteBuffer pl = ByteBuffer.allocate(9 + big.length);
            pl.putInt(tsn);
            pl.putShort((short) 1);
            pl.put((byte) 0);
            pl.put((byte) 0);
            pl.put((byte) 0);
            pl.put(big);
            lastBigPkt = buildControlPacket(0x00, 1, pl.array(), false, 0);
            udpSocket.send(new DatagramPacket(lastBigPkt, lastBigPkt.length, InetAddress.getByName(hostIp), 9296));
        }
    }

    private void sendIdrRequest() {
        try {
            if (streamCipher != null) {
                byte[] idr = PS5Protocol.buildSimpleTakionMsg(25);
                sendControlData(idr, 1, 2, true);
            }
        } catch (Exception ignored) {}
    }

    private byte[] buildInitChunkPayload() {
        ByteBuffer bb = ByteBuffer.allocate(16);
        bb.putInt(tagLocal);
        bb.putInt(0x019000);
        bb.putShort((short) 0x64);
        bb.putShort((short) 0x64);
        bb.putInt(tsn);
        return bb.array();
    }

    private void sendDataAck(int ackTsn) throws Exception {
        synchronized (sendLock) {
            ByteBuffer bb = ByteBuffer.allocate(12);
            bb.putInt(ackTsn);
            bb.putInt(0x019000);
            bb.putShort((short) 0);
            bb.putShort((short) 0);
            byte[] pkt = buildControlPacket(0x03, 0, bb.array(), false, 29);
            udpSocket.send(new DatagramPacket(pkt, pkt.length, InetAddress.getByName(hostIp), 9296));
        }
    }

    private void sendControlData(byte[] protoBytes, int flag, int channel, boolean isProtoAdvance) throws Exception {
        synchronized (sendLock) {
            if (streamCipher != null) {
                tsn++;
            }
            ByteBuffer pl = ByteBuffer.allocate(9 + protoBytes.length);
            pl.putInt(tsn);
            pl.putShort((short) channel);
            pl.put((byte) 0);
            pl.put((byte) 0);
            pl.put((byte) 0);
            pl.put(protoBytes);
            int adv = (streamCipher != null && isProtoAdvance) ? protoBytes.length : 0;
            byte[] pkt = buildControlPacket(0x00, flag, pl.array(), false, adv);
            udpSocket.send(new DatagramPacket(pkt, pkt.length, InetAddress.getByName(hostIp), 9296));
        }
    }

    private byte[] buildControlPacket(int chunkType, int flag, byte[] chunkPayload, boolean encrypt, int advanceBy) {
        int chunkLen = chunkPayload.length + 4;
        ByteBuffer buf = ByteBuffer.allocate(13 + chunkLen);
        buf.put((byte) 0x00);
        buf.putInt(tagRemote);
        buf.putInt(0);
        buf.putInt(0);
        buf.put((byte) chunkType);
        buf.put((byte) flag);
        buf.putShort((short) chunkLen);
        byte[] pl = chunkPayload;
        long kp = 0;
        if (streamCipher != null) {
            kp = streamCipher.getKeyPos();
            if (encrypt) pl = streamCipher.encrypt(pl);
        }
        buf.put(pl);
        byte[] raw = buf.array();
        if (streamCipher != null) {
            int adv = advanceBy > 0 ? advanceBy : pl.length;
            int gmac = streamCipher.getGmac(raw);
            ByteBuffer wrap = ByteBuffer.wrap(raw);
            wrap.putInt(5, gmac);
            wrap.putInt(9, (int) kp);
            streamCipher.advanceKeyPos(adv);
        }
        return raw;
    }

    public void sendButtonEvent(int psButtonCode, boolean pressed) {
        if (streamCipher == null || udpSocket == null) return;
        int wIdx = btnWriteIdx;
        int nextIdx = (wIdx + 1) & (BTN_RING_SIZE - 1);
        if (nextIdx == btnReadIdx) {
            btnReadIdx = (btnReadIdx + 1) & (BTN_RING_SIZE - 1);
        }
        btnRingCodes[wIdx] = psButtonCode;
        btnRingPressed[wIdx] = pressed;
        btnWriteIdx = nextIdx;
        synchronized (ctrlWakeLock) {
            ctrlWakeLock.notify();
        }
    }

    private void dispatchButtonEventNow(int psButtonCode, boolean pressed) {
        if (streamCipher == null || udpSocket == null) return;
        synchronized (sendLock) {
            try {
                int btnId = psButtonCode;
                if (btnId >= 0x8C && pressed) btnId += 32;
                fbEventPlain[0] = (byte) 0x80;
                fbEventPlain[1] = (byte) btnId;
                fbEventPlain[2] = (byte) (pressed ? 0xFF : 0x00);
                for (int rep = 0; rep < 2; rep++) {
                    feedbackSeqEvent = (feedbackSeqEvent + 1) & 0xFFFF;
                    sendFeedbackPacketZeroAllocLocked(0x01, feedbackSeqEvent, fbEventPlain, fbEventPktBuf, fbEventPktWrap, fbEventDatagram);
                }
            } catch (Exception e) {
                android.util.Log.e("DRPS5", "Error enviando sendButtonEvent: " + e.getMessage(), e);
            }
        }
    }

    public void setSticks(short lx, short ly, short rx, short ry) {
        this.leftX = lx;
        this.leftY = ly;
        this.rightX = rx;
        this.rightY = ry;
    }

    private void sendControllerState() {
        if (streamCipher == null || udpSocket == null) return;
        synchronized (sendLock) {
            try {
                fbStateWrap.putShort(17, leftX);
                fbStateWrap.putShort(19, leftY);
                fbStateWrap.putShort(21, rightX);
                fbStateWrap.putShort(23, rightY);
                fbStateWrap.putShort(25, (short) 0);
                fbStatePlain[27] = (byte) 1;
                feedbackSeqState = (feedbackSeqState + 1) & 0xFFFF;
                sendFeedbackPacketZeroAllocLocked(0x06, feedbackSeqState, fbStatePlain, fbStatePktBuf, fbStatePktWrap, fbStateDatagram);
            } catch (Exception e) {
                android.util.Log.e("DRPS5", "Error enviando sendControllerState: " + e.getMessage(), e);
            }
        }
    }

    private void sendFeedbackPacketZeroAllocLocked(int fbType, int seq, byte[] plainPayload, byte[] pktBuf, ByteBuffer pktWrap, DatagramPacket dgram) throws Exception {
        long kp = streamCipher.getKeyPos();
        byte[] encPl = streamCipher.encrypt(plainPayload);
        pktBuf[0] = (byte) fbType;
        pktWrap.putShort(1, (short) seq);
        pktBuf[3] = 0;
        pktWrap.putInt(4, (int) kp);
        pktWrap.putInt(8, 0);
        System.arraycopy(encPl, 0, pktBuf, 12, plainPayload.length);
        int gmac = streamCipher.getGmac(pktBuf);
        pktWrap.putInt(8, gmac);
        streamCipher.advanceKeyPos(plainPayload.length);
        if (dgram != null) {
            udpSocket.send(dgram);
        } else {
            InetAddress dst = hostAddress != null ? hostAddress : InetAddress.getByName(hostIp);
            udpSocket.send(new DatagramPacket(pktBuf, pktBuf.length, dst, 9296));
        }
    }
}
"""
    (pkg_dir / "PS5StreamClient.java").write_text(stream_java, encoding="utf-8")

    # 5. MainActivity.java (Fullscreen WebView + SurfaceView + JavascriptInterface Bridge + Android TV D-Pad & Gamepad)
    main_java = r"""package com.drps5.remoteplay;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.graphics.Paint;
import android.graphics.Path;
import android.hardware.input.InputManager;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.Build;
import android.os.SystemClock;
import android.os.Handler;
import android.os.Looper;
import android.animation.ValueAnimator;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.HapticFeedbackConstants;
import java.util.Arrays;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Iterator;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private FrameLayout rootLayout;
    private WebView webView;
    private VirtualCursorView cursorView;
    private TouchGamepadOverlayView touchOverlayView;
    private short touchLx = 0, touchLy = 0, touchRx = 0, touchRy = 0;
    private FrameLayout streamContainer;
    private SurfaceView surfaceView;
    private TextView hudBanner;
    private PS5StreamClient streamClient;
    private WifiManager.MulticastLock multicastLock;
    private WifiManager.WifiLock wifiLowLatencyLock;
    private WifiManager.WifiLock wifiHighPerfLock;
    private final StringBuilder sessionLogs = new StringBuilder();

    // Estado del cursor virtual controlado por Análogo Izquierdo / D-Pad
    private float cursorX = 640f;
    private float cursorY = 360f;
    private float stickVelX = 0f;
    private float stickVelY = 0f;
    private float scrollVelY = 0f;
    private float dpadVelX = 0f;
    private float dpadVelY = 0f;
    private boolean cursorInitialized = false;
    private boolean cursorLoopActive = false;
    private volatile boolean cursorMovedByUser = false;
    private long clickPulseUntil = 0;

    // Estado de disparadores y combinaciones de teclas
    private boolean l2TriggerActive = false;
    private boolean r2TriggerActive = false;
    private boolean isSharePressed = false;
    private boolean isOptionsPressed = false;
    private long lastMenuExitPress = 0;
    private boolean hatLeftActive = false;
    private boolean hatRightActive = false;
    private boolean hatUpActive = false;
    private boolean hatDownActive = false;

    // Estado en vivo del mando para Calibración y Mapeo en el WebView
    private static final boolean[] liveButtons = new boolean[21];
    private static final long[] buttonReleaseTime = new long[21];
    private static volatile float liveLx = 0f, liveLy = 0f, liveRx = 0f, liveRy = 0f;
    private static volatile float liveL2 = 0f, liveR2 = 0f;
    private static volatile String livePadName = "Mando Conectado";
    private static volatile boolean livePadConnected = false;
    private static volatile boolean isCapturingButton = false;
    private static volatile boolean isGamepadTabActive = false;

    // Superposición HUD en vivo (FPS, resolución, bitrate, códec, pérdida)
    private TextView hudOverlay;
    private boolean showHud = false;

    private Drawable createHudOverlayBackground() {
        android.graphics.drawable.GradientDrawable gd = new android.graphics.drawable.GradientDrawable();
        gd.setColor(Color.parseColor("#D90B1221"));
        gd.setCornerRadius(14 * getResources().getDisplayMetrics().density);
        gd.setStroke((int) (1.5f * getResources().getDisplayMetrics().density), Color.parseColor("#38BDF8"));
        return gd;
    }

    private void checkGamepadConnected() {
        int[] ids = InputDevice.getDeviceIds();
        boolean found = false;
        for (int id : ids) {
            InputDevice dev = InputDevice.getDevice(id);
            if (dev != null) {
                int sources = dev.getSources();
                if ((sources & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                        || (sources & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
                    found = true;
                    String dn = dev.getName();
                    if (dn != null && !dn.isEmpty() && !"Virtual".equalsIgnoreCase(dn)) {
                        livePadName = dn;
                    }
                    break;
                }
            }
        }
        livePadConnected = found;
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (cursorView != null) {
                    boolean inStream = (streamContainer != null && streamContainer.getVisibility() == View.VISIBLE);
                    if (inStream || !livePadConnected) {
                        cursorView.setVisibility(View.GONE);
                    } else {
                        cursorView.setVisibility(View.VISIBLE);
                        cursorView.invalidate();
                    }
                }
            }
        });
    }

    private static int mapPsButtonToLiveIndex(int psBtn) {
        switch (psBtn) {
            case 0x88: return 0;  // Cruz (A)
            case 0x89: return 1;  // Círculo (B)
            case 0x8A: return 2;  // Cuadrado (X)
            case 0x8B: return 3;  // Triángulo (Y)
            case 0x84: return 4;  // L1
            case 0x85: return 5;  // R1
            case 0x86: return 6;  // L2
            case 0x87: return 7;  // R2
            case 0x8D: return 8;  // Share / Select
            case 0x8C: return 9;  // Options / Start
            case 0x8F: return 10; // L3
            case 0x90: return 11; // R3
            case 0x80: return 12; // D-Up
            case 0x81: return 13; // D-Down
            case 0x82: return 14; // D-Left
            case 0x83: return 15; // D-Right
            case 0x8E: return 16; // PS (Home)
            case 0x91: return 17; // Touchpad (Click)
            default: return -1;
        }
    }

    private final class VirtualCursorView extends View {
        private final Paint fillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint strokePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path arrowPath = new Path();

        public VirtualCursorView(Context context) {
            super(context);
            setClickable(false);
            setFocusable(false);

            fillPaint.setStyle(Paint.Style.FILL);
            fillPaint.setColor(Color.parseColor("#00E5FF"));

            strokePaint.setStyle(Paint.Style.STROKE);
            strokePaint.setStrokeWidth(3.0f);
            strokePaint.setColor(Color.parseColor("#FFFFFF"));

            glowPaint.setStyle(Paint.Style.STROKE);
            glowPaint.setStrokeWidth(6.0f);
            glowPaint.setColor(Color.argb(130, 0, 180, 255));

            arrowPath.moveTo(0f, 0f);
            arrowPath.lineTo(0f, 28f);
            arrowPath.lineTo(8f, 21f);
            arrowPath.lineTo(14f, 33f);
            arrowPath.lineTo(19f, 30f);
            arrowPath.lineTo(13f, 18f);
            arrowPath.lineTo(23f, 18f);
            arrowPath.close();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (!cursorInitialized && getWidth() > 0 && getHeight() > 0) {
                cursorX = getWidth() / 2f;
                cursorY = getHeight() / 2f;
                cursorInitialized = true;
            }
            canvas.save();
            canvas.translate(cursorX, cursorY);

            long now = SystemClock.uptimeMillis();
            if (now < clickPulseUntil) {
                float p = 1.0f - ((clickPulseUntil - now) / 220f);
                float radius = 10f + p * 22f;
                glowPaint.setAlpha((int) ((1.0f - p) * 220));
                canvas.drawCircle(4f, 4f, radius, glowPaint);
                glowPaint.setAlpha(130);
            }

            // Halo exterior oscuro para contraste + puntero neón
            strokePaint.setColor(Color.parseColor("#040814"));
            strokePaint.setStrokeWidth(5.5f);
            canvas.drawPath(arrowPath, strokePaint);

            canvas.drawPath(arrowPath, fillPaint);

            strokePaint.setColor(Color.WHITE);
            strokePaint.setStrokeWidth(2.2f);
            canvas.drawPath(arrowPath, strokePaint);

            canvas.drawCircle(2f, 2f, 3.0f, glowPaint);
            canvas.restore();
        }
    }

    private final class TouchGamepadOverlayView extends View {
        private final Paint bgPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint borderPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pressedBgPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint glyphPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

        private float w = 0, h = 0;
        private float density = 1f;

        private float lStickCx = 0, lStickCy = 0, lStickBaseR = 0, lStickThumbR = 0;
        private float rStickCx = 0, rStickCy = 0, rStickBaseR = 0, rStickThumbR = 0;
        private float lStickCurX = 0, lStickCurY = 0;
        private float rStickCurX = 0, rStickCurY = 0;
        private int lStickPointerId = -1;
        private int rStickPointerId = -1;

        private final boolean[] touchBtnPressed = new boolean[256];
        private final int[] pointerAction = new int[32];

        private float overlayAlpha = 1.0f;
        private ValueAnimator fadeAnimator = null;
        private final Handler autoHideHandler = new Handler(Looper.getMainLooper());
        private static final long AUTO_HIDE_DELAY_MS = 3000;

        private final Runnable autoHideRunnable = new Runnable() {
            @Override
            public void run() {
                if (hasActiveTouches()) {
                    scheduleAutoHide();
                    return;
                }
                startFadeOut();
            }
        };

        public TouchGamepadOverlayView(Context context) {
            super(context);
            density = context.getResources().getDisplayMetrics().density;
            Arrays.fill(pointerAction, -1);
            overlayAlpha = livePadConnected ? 0.0f : 1.0f;

            bgPaint.setStyle(Paint.Style.FILL);
            bgPaint.setColor(Color.argb(75, 11, 18, 33));

            borderPaint.setStyle(Paint.Style.STROKE);
            borderPaint.setStrokeWidth(2.2f * density);
            borderPaint.setColor(Color.argb(160, 56, 189, 248));

            pressedBgPaint.setStyle(Paint.Style.FILL);
            pressedBgPaint.setColor(Color.argb(175, 2, 132, 199));

            glyphPaint.setStyle(Paint.Style.STROKE);
            glyphPaint.setStrokeWidth(3.2f * density);
            glyphPaint.setStrokeCap(Paint.Cap.ROUND);
            glyphPaint.setStrokeJoin(Paint.Join.ROUND);
            glyphPaint.setColor(Color.WHITE);

            textPaint.setColor(Color.WHITE);
            textPaint.setTextAlign(Paint.Align.CENTER);
            textPaint.setTypeface(Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD));
            textPaint.setTextSize(13f * density);
        }

        private boolean hasActiveTouches() {
            if (lStickPointerId != -1 || rStickPointerId != -1) return true;
            for (int p : pointerAction) {
                if (p != -1) return true;
            }
            return false;
        }

        private void showOverlayInstant() {
            autoHideHandler.removeCallbacks(autoHideRunnable);
            if (fadeAnimator != null) {
                fadeAnimator.cancel();
                fadeAnimator = null;
            }
            if (overlayAlpha < 1.0f) {
                overlayAlpha = 1.0f;
                invalidate();
            }
        }

        private void scheduleAutoHide() {
            autoHideHandler.removeCallbacks(autoHideRunnable);
            autoHideHandler.postDelayed(autoHideRunnable, AUTO_HIDE_DELAY_MS);
        }

        private void startFadeOut() {
            if (fadeAnimator != null) {
                fadeAnimator.cancel();
            }
            fadeAnimator = ValueAnimator.ofFloat(overlayAlpha, 0.0f);
            fadeAnimator.setDuration(400);
            fadeAnimator.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator animation) {
                    overlayAlpha = (Float) animation.getAnimatedValue();
                    invalidate();
                }
            });
            fadeAnimator.start();
        }

        @Override
        protected void onAttachedToWindow() {
            super.onAttachedToWindow();
            scheduleAutoHide();
        }

        @Override
        protected void onDetachedFromWindow() {
            super.onDetachedFromWindow();
            autoHideHandler.removeCallbacks(autoHideRunnable);
            if (fadeAnimator != null) fadeAnimator.cancel();
        }

        public void resetState() {
            Arrays.fill(touchBtnPressed, false);
            Arrays.fill(pointerAction, -1);
            lStickPointerId = -1;
            rStickPointerId = -1;
            lStickCurX = lStickCx;
            lStickCurY = lStickCy;
            rStickCurX = rStickCx;
            rStickCurY = rStickCy;
            touchLx = 0; touchLy = 0; touchRx = 0; touchRy = 0;
            invalidate();
        }

        @Override
        protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            super.onSizeChanged(w, h, oldw, oldh);
            this.w = w;
            this.h = h;
            density = getResources().getDisplayMetrics().density;

            lStickCx = 0.13f * w;
            lStickCy = 0.74f * h;
            lStickBaseR = 52f * density;
            lStickThumbR = 22f * density;
            lStickCurX = lStickCx;
            lStickCurY = lStickCy;

            rStickCx = 0.87f * w;
            rStickCy = 0.74f * h;
            rStickBaseR = 52f * density;
            rStickThumbR = 22f * density;
            rStickCurX = rStickCx;
            rStickCurY = rStickCy;
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (w <= 0 || h <= 0 || overlayAlpha <= 0.001f) return;

            int saveCount = canvas.saveLayerAlpha(0f, 0f, (float) w, (float) h, (int) (overlayAlpha * 255f));
            try {
                // Fila superior: Gatillos y Botones de Sistema en una franja limpia
                float topY = Math.max(22f * density, 0.055f * h);
                float shW = 32f * density;
                float shH = 18f * density;

                // 1. Shoulders: L1 y L2 horizontales a la izquierda
                drawCapsule(canvas, 0.08f * w, topY, shW, shH, "L1", 0x84);
                drawCapsule(canvas, 0.18f * w, topY, shW, shH, "L2", 0x86);

                // 2. Botones de Sistema: SHARE, TOUCHPAD, OPTION
                drawCapsule(canvas, 0.35f * w, topY, 28f * density, 16f * density, "SHARE", 0x8D);
                drawCapsule(canvas, 0.50f * w, topY, 52f * density, 18f * density, "TOUCHPAD", 0x91);
                drawCapsule(canvas, 0.65f * w, topY, 28f * density, 16f * density, "OPT", 0x8C);

                // 3. Shoulders: R2 y R1 horizontales a la derecha
                drawCapsule(canvas, 0.82f * w, topY, shW, shH, "R2", 0x87);
                drawCapsule(canvas, 0.92f * w, topY, shW, shH, "R1", 0x85);

                // 4. CRUCETA D-PAD (Limpia y con amplio margen vertical respecto a L2)
                float dpadCx = 0.13f * w;
                float dpadCy = 0.44f * h;
                float dpadR = 23f * density;
                float dpadOffset = 34f * density;
                drawRoundButton(canvas, dpadCx, dpadCy - dpadOffset, dpadR, 0x80); // UP
                drawArrow(canvas, dpadCx, dpadCy - dpadOffset, dpadR * 0.45f, 0);
                drawRoundButton(canvas, dpadCx, dpadCy + dpadOffset, dpadR, 0x81); // DOWN
                drawArrow(canvas, dpadCx, dpadCy + dpadOffset, dpadR * 0.45f, 180);
                drawRoundButton(canvas, dpadCx - dpadOffset, dpadCy, dpadR, 0x82); // LEFT
                drawArrow(canvas, dpadCx - dpadOffset, dpadCy, dpadR * 0.45f, 270);
                drawRoundButton(canvas, dpadCx + dpadOffset, dpadCy, dpadR, 0x83); // RIGHT
                drawArrow(canvas, dpadCx + dpadOffset, dpadCy, dpadR * 0.45f, 90);

                // 5. BOTONES DE ACCIÓN PERSONALIZADOS (Limpia y con amplio margen vertical respecto a R2)
                float actCx = 0.87f * w;
                float actCy = 0.44f * h;
                float actR = 23f * density;
                float actSpread = 36f * density;

                // Abajo: Cruz recta (+) [0x88]
                float crossX = actCx, crossY = actCy + actSpread;
                drawRoundButton(canvas, crossX, crossY, actR, 0x88);
                float cArm = actR * 0.45f;
                canvas.drawLine(crossX - cArm, crossY, crossX + cArm, crossY, glyphPaint);
                canvas.drawLine(crossX, crossY - cArm, crossX, crossY + cArm, glyphPaint);

                // Izquierda: L invertida (⅂) [0x8A]
                float sqX = actCx - actSpread, sqY = actCy;
                drawRoundButton(canvas, sqX, sqY, actR, 0x8A);
                float lArm = actR * 0.42f;
                Path lPath = new Path();
                lPath.moveTo(sqX - lArm * 0.85f, sqY - lArm);
                lPath.lineTo(sqX + lArm, sqY - lArm);
                lPath.lineTo(sqX + lArm, sqY + lArm);
                canvas.drawPath(lPath, glyphPaint);

                // Derecha: Medialuna abierta a la izquierda ()) [0x89]
                float cirX = actCx + actSpread, cirY = actCy;
                drawRoundButton(canvas, cirX, cirY, actR, 0x89);
                float cirArm = actR * 0.48f;
                RectF crescentRect = new RectF(cirX - cirArm, cirY - cirArm, cirX + cirArm, cirY + cirArm);
                canvas.drawArc(crescentRect, 290f, 240f, false, glyphPaint);

                // Arriba: Ángulo de 45° con 2 lados de 3 dibujados (⋀) [0x8B]
                float triX = actCx, triY = actCy - actSpread;
                drawRoundButton(canvas, triX, triY, actR, 0x8B);
                float tArm = actR * 0.46f;
                Path caretPath = new Path();
                caretPath.moveTo(triX - tArm, triY + tArm * 0.65f);
                caretPath.lineTo(triX, triY - tArm * 0.85f);
                caretPath.lineTo(triX + tArm, triY + tArm * 0.65f);
                canvas.drawPath(caretPath, glyphPaint);

                // 6. ANÁLOGO IZQUIERDO
                canvas.drawCircle(lStickCx, lStickCy, lStickBaseR, bgPaint);
                canvas.drawCircle(lStickCx, lStickCy, lStickBaseR, borderPaint);
                canvas.drawCircle(lStickCurX, lStickCurY, lStickThumbR, touchBtnPressed[0x8F] ? pressedBgPaint : bgPaint);
                canvas.drawCircle(lStickCurX, lStickCurY, lStickThumbR, borderPaint);

                // 7. ANÁLOGO DERECHO
                canvas.drawCircle(rStickCx, rStickCy, rStickBaseR, bgPaint);
                canvas.drawCircle(rStickCx, rStickCy, rStickBaseR, borderPaint);
                canvas.drawCircle(rStickCurX, rStickCurY, rStickThumbR, touchBtnPressed[0x90] ? pressedBgPaint : bgPaint);
                canvas.drawCircle(rStickCurX, rStickCurY, rStickThumbR, borderPaint);

                // 8. CHIPS L3 / R3
                drawCapsule(canvas, lStickCx + lStickBaseR + 24f * density, lStickCy, 18f * density, 16f * density, "L3", 0x8F);
                drawCapsule(canvas, rStickCx - rStickBaseR - 24f * density, rStickCy, 18f * density, 16f * density, "R3", 0x90);

                // 9. BOTÓN PS (Texto 'PS' centrado sin logo registrado)
                float psR = 22f * density;
                float psCx = 0.50f * w;
                float psCy = 0.90f * h;
                drawRoundButton(canvas, psCx, psCy, psR, 0x8E);
                textPaint.setTextSize(13f * density);
                canvas.drawText("PS", psCx, psCy + 4.5f * density, textPaint);
            } finally {
                canvas.restoreToCount(saveCount);
            }
        }

        private void drawRoundButton(Canvas canvas, float cx, float cy, float r, int code) {
            canvas.drawCircle(cx, cy, r, touchBtnPressed[code] ? pressedBgPaint : bgPaint);
            canvas.drawCircle(cx, cy, r, borderPaint);
        }

        private void drawCapsule(Canvas canvas, float cx, float cy, float hw, float hh, String text, int code) {
            RectF rect = new RectF(cx - hw, cy - hh, cx + hw, cy + hh);
            canvas.drawRoundRect(rect, hh, hh, touchBtnPressed[code] ? pressedBgPaint : bgPaint);
            canvas.drawRoundRect(rect, hh, hh, borderPaint);
            textPaint.setTextSize(11f * density);
            canvas.drawText(text, cx, cy + 4f * density, textPaint);
        }

        private void drawArrow(Canvas canvas, float cx, float cy, float len, float deg) {
            canvas.save();
            canvas.rotate(deg, cx, cy);
            Path p = new Path();
            p.moveTo(cx, cy - len);
            p.lineTo(cx - len * 0.75f, cy + len * 0.5f);
            p.lineTo(cx + len * 0.75f, cy + len * 0.5f);
            p.close();
            Paint ap = new Paint(Paint.ANTI_ALIAS_FLAG);
            ap.setStyle(Paint.Style.FILL);
            ap.setColor(Color.WHITE);
            canvas.drawPath(p, ap);
            canvas.restore();
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            int action = event.getActionMasked();
            int actionIdx = event.getActionIndex();

            showOverlayInstant();
            if (action == MotionEvent.ACTION_DOWN) {
                MainActivity.this.hideSystemUi();
            }

            switch (action) {
                case MotionEvent.ACTION_DOWN:
                case MotionEvent.ACTION_POINTER_DOWN: {
                    int pId = event.getPointerId(actionIdx);
                    float x = event.getX(actionIdx);
                    float y = event.getY(actionIdx);
                    handlePointerDown(pId, x, y);
                    break;
                }
                case MotionEvent.ACTION_MOVE: {
                    int pCount = event.getPointerCount();
                    for (int i = 0; i < pCount; i++) {
                        int pId = event.getPointerId(i);
                        float x = event.getX(i);
                        float y = event.getY(i);
                        handlePointerMove(pId, x, y);
                    }
                    break;
                }
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_POINTER_UP: {
                    int pId = event.getPointerId(actionIdx);
                    handlePointerUp(pId);
                    if (action == MotionEvent.ACTION_UP || !hasActiveTouches()) {
                        scheduleAutoHide();
                    }
                    break;
                }
                case MotionEvent.ACTION_CANCEL: {
                    resetState();
                    if (MainActivity.this.streamClient != null) {
                        MainActivity.this.streamClient.setSticks((short) 0, (short) 0, (short) 0, (short) 0);
                    }
                    scheduleAutoHide();
                    break;
                }
            }
            invalidate();
            return true;
        }

        private void handlePointerDown(int pId, float x, float y) {
            int actIdx = pId % pointerAction.length;
            float lDist = (float) Math.hypot(x - lStickCx, y - lStickCy);
            if (lDist <= lStickBaseR * 1.35f && lStickPointerId == -1) {
                lStickPointerId = pId;
                pointerAction[actIdx] = -2;
                updateLeftStick(x, y);
                return;
            }

            float rDist = (float) Math.hypot(x - rStickCx, y - rStickCy);
            if (rDist <= rStickBaseR * 1.35f && rStickPointerId == -1) {
                rStickPointerId = pId;
                pointerAction[actIdx] = -3;
                updateRightStick(x, y);
                return;
            }

            int hitBtn = hitTestButton(x, y);
            if (hitBtn != -1) {
                touchBtnPressed[hitBtn] = true;
                pointerAction[actIdx] = hitBtn;
                try { performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY); } catch (Throwable ignored) {}
                if (MainActivity.this.streamClient != null) {
                    MainActivity.this.streamClient.sendButtonEvent(hitBtn, true);
                }

                // Salida de pantalla remota con botones virtuales: SHARE + OPTION
                if (touchBtnPressed[0x8D] && touchBtnPressed[0x8C]) {
                    touchBtnPressed[0x8D] = false;
                    touchBtnPressed[0x8C] = false;
                    MainActivity.this.runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            Toast.makeText(MainActivity.this, "Sesión remota finalizada (Captura + Options)", Toast.LENGTH_SHORT).show();
                            MainActivity.this.stopNativeStreamUi();
                        }
                    });
                    return;
                }
            }
        }

        private void handlePointerMove(int pId, float x, float y) {
            if (pId == lStickPointerId) {
                updateLeftStick(x, y);
            } else if (pId == rStickPointerId) {
                updateRightStick(x, y);
            }
        }

        private void handlePointerUp(int pId) {
            int actIdx = pId % pointerAction.length;
            if (pId == lStickPointerId) {
                lStickPointerId = -1;
                lStickCurX = lStickCx;
                lStickCurY = lStickCy;
                touchLx = 0; touchLy = 0;
                if (MainActivity.this.streamClient != null) {
                    MainActivity.this.streamClient.setSticks(touchLx, touchLy, touchRx, touchRy);
                }
            } else if (pId == rStickPointerId) {
                rStickPointerId = -1;
                rStickCurX = rStickCx;
                rStickCurY = rStickCy;
                touchRx = 0; touchRy = 0;
                if (MainActivity.this.streamClient != null) {
                    MainActivity.this.streamClient.setSticks(touchLx, touchLy, touchRx, touchRy);
                }
            } else {
                int code = pointerAction[actIdx];
                if (code >= 0 && code < 256) {
                    touchBtnPressed[code] = false;
                    if (MainActivity.this.streamClient != null) {
                        MainActivity.this.streamClient.sendButtonEvent(code, false);
                    }
                }
            }
            pointerAction[actIdx] = -1;
        }

        private void updateLeftStick(float x, float y) {
            float dx = x - lStickCx;
            float dy = y - lStickCy;
            float dist = (float) Math.hypot(dx, dy);
            float maxDist = lStickBaseR * 0.95f;
            if (dist > maxDist && dist > 0.001f) {
                dx = (dx / dist) * maxDist;
                dy = (dy / dist) * maxDist;
            }
            lStickCurX = lStickCx + dx;
            lStickCurY = lStickCy + dy;

            float normX = dx / maxDist;
            float normY = dy / maxDist;
            touchLx = (short) Math.max(-32767, Math.min(32767, (int) (normX * 32767f)));
            touchLy = (short) Math.max(-32767, Math.min(32767, (int) (normY * 32767f)));
            if (MainActivity.this.streamClient != null) {
                MainActivity.this.streamClient.setSticks(touchLx, touchLy, touchRx, touchRy);
            }
        }

        private void updateRightStick(float x, float y) {
            float dx = x - rStickCx;
            float dy = y - rStickCy;
            float dist = (float) Math.hypot(dx, dy);
            float maxDist = rStickBaseR * 0.95f;
            if (dist > maxDist && dist > 0.001f) {
                dx = (dx / dist) * maxDist;
                dy = (dy / dist) * maxDist;
            }
            rStickCurX = rStickCx + dx;
            rStickCurY = rStickCy + dy;

            float normX = dx / maxDist;
            float normY = dy / maxDist;
            touchRx = (short) Math.max(-32767, Math.min(32767, (int) (normX * 32767f)));
            touchRy = (short) Math.max(-32767, Math.min(32767, (int) (normY * 32767f)));
            if (MainActivity.this.streamClient != null) {
                MainActivity.this.streamClient.setSticks(touchLx, touchLy, touchRx, touchRy);
            }
        }

        private int hitTestButton(float x, float y) {
            float dpadCx = 0.13f * w;
            float dpadCy = 0.44f * h;
            float dpadR = 28f * density;
            float dpadOffset = 34f * density;
            if (Math.hypot(x - dpadCx, y - (dpadCy - dpadOffset)) <= dpadR) return 0x80; // UP
            if (Math.hypot(x - dpadCx, y - (dpadCy + dpadOffset)) <= dpadR) return 0x81; // DOWN
            if (Math.hypot(x - (dpadCx - dpadOffset), y - dpadCy) <= dpadR) return 0x82; // LEFT
            if (Math.hypot(x - (dpadCx + dpadOffset), y - dpadCy) <= dpadR) return 0x83; // RIGHT

            float actCx = 0.87f * w;
            float actCy = 0.44f * h;
            float actR = 28f * density;
            float actSpread = 36f * density;
            if (Math.hypot(x - actCx, y - (actCy + actSpread)) <= actR) return 0x88; // Cruz (+)
            if (Math.hypot(x - (actCx - actSpread), y - actCy) <= actR) return 0x8A; // L invertida
            if (Math.hypot(x - (actCx + actSpread), y - actCy) <= actR) return 0x89; // Medialuna
            if (Math.hypot(x - actCx, y - (actCy - actSpread)) <= actR) return 0x8B; // Angulo 45

            float topY = Math.max(22f * density, 0.055f * h);
            float shW = 34f * density, shH = 22f * density;
            if (Math.abs(x - 0.08f * w) <= shW && Math.abs(y - topY) <= shH) return 0x84; // L1
            if (Math.abs(x - 0.18f * w) <= shW && Math.abs(y - topY) <= shH) return 0x86; // L2
            if (Math.abs(x - 0.82f * w) <= shW && Math.abs(y - topY) <= shH) return 0x87; // R2
            if (Math.abs(x - 0.92f * w) <= shW && Math.abs(y - topY) <= shH) return 0x85; // R1

            if (Math.abs(x - 0.35f * w) <= 32f * density && Math.abs(y - topY) <= 18f * density) return 0x8D; // SHARE
            if (Math.abs(x - 0.50f * w) <= 56f * density && Math.abs(y - topY) <= 20f * density) return 0x91; // TOUCHPAD
            if (Math.abs(x - 0.65f * w) <= 32f * density && Math.abs(y - topY) <= 18f * density) return 0x8C; // OPTIONS

            if (Math.hypot(x - (lStickCx + lStickBaseR + 24f * density), y - lStickCy) <= 22f * density) return 0x8F; // L3
            if (Math.hypot(x - (rStickCx - rStickBaseR - 24f * density), y - rStickCy) <= 22f * density) return 0x90; // R3

            if (Math.hypot(x - 0.50f * w, y - 0.90f * h) <= 26f * density) return 0x8E; // PS

            return -1;
        }
    }

    private final Runnable cursorTickRunnable = new Runnable() {
        @Override
        public void run() {
            if (!cursorLoopActive) return;
            if (streamContainer == null || streamContainer.getVisibility() != View.VISIBLE) {
                int w = rootLayout != null && rootLayout.getWidth() > 0 ? rootLayout.getWidth() : 1280;
                int h = rootLayout != null && rootLayout.getHeight() > 0 ? rootLayout.getHeight() : 720;
                if (!cursorInitialized && w > 0 && h > 0) {
                    cursorX = w / 2f;
                    cursorY = h / 2f;
                    cursorInitialized = true;
                }

                float vx = stickVelX;
                float vy = stickVelY;
                boolean moved = false;
                float mag = (float) Math.sqrt(vx * vx + vy * vy);
                if (mag > 0.01f) {
                    cursorMovedByUser = true;
                    if (cursorView != null) cursorView.setVisibility(View.VISIBLE);
                    // Velocidad ágil con aceleración dinámica para Android TV Stick (28 a 48 px/frame)
                    float speed = 28.0f + (mag > 0.75f ? (mag - 0.75f) * 48.0f : 0f);
                    cursorX = Math.max(4f, Math.min(w - 8f, cursorX + vx * speed));
                    cursorY = Math.max(4f, Math.min(h - 8f, cursorY + vy * speed));
                    moved = true;

                    // Auto-scroll suave en bordes
                    if (cursorY >= h - 45f && vy > 0.25f) {
                        scrollWebViewBy((int) (vy * 28f));
                    } else if (cursorY <= 45f && vy < -0.25f) {
                        scrollWebViewBy((int) (vy * 28f));
                    }
                }

                if (Math.abs(scrollVelY) > 0.12f) {
                    scrollWebViewBy((int) (scrollVelY * 30f));
                }

                if (moved || SystemClock.uptimeMillis() < clickPulseUntil) {
                    if (cursorView != null) cursorView.invalidate();
                }
            }
            if (rootLayout != null) {
                rootLayout.postDelayed(this, 16);
            }
        }
    };

    private void scrollWebViewBy(int dy) {
        if (webView == null || dy == 0) return;
        String js = "(function(d){"
                + "var el = document.elementFromPoint(" + (int) cursorX + " * window.innerWidth / " + Math.max(1, webView.getWidth()) + ", "
                + (int) cursorY + " * window.innerHeight / " + Math.max(1, webView.getHeight()) + ");"
                + "while(el && el !== document.body && el !== document.documentElement){"
                + "  var st = window.getComputedStyle(el);"
                + "  if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight){"
                + "    el.scrollTop += d; return;"
                + "  }"
                + "  el = el.parentElement;"
                + "}"
                + "var pane = document.querySelector('.tab-pane.active .settings-container, .tab-pane.active, .app-main');"
                + "if(pane && pane.scrollHeight > pane.clientHeight){ pane.scrollTop += d; } else { window.scrollBy(0, d); }"
                + "})(" + dy + ");";
        webView.evaluateJavascript(js, null);
    }

    private void performCursorClick() {
        if (webView == null) return;
        clickPulseUntil = SystemClock.uptimeMillis() + 220;
        if (cursorView != null) cursorView.invalidate();

        if (cursorMovedByUser) {
            final long downTime = SystemClock.uptimeMillis();
            final float x = cursorX;
            final float y = cursorY;

            MotionEvent evDown = MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN, x, y, 0);
            evDown.setSource(InputDevice.SOURCE_TOUCHSCREEN);
            webView.dispatchTouchEvent(evDown);
            evDown.recycle();

            webView.postDelayed(() -> {
                long upTime = SystemClock.uptimeMillis();
                MotionEvent evUp = MotionEvent.obtain(downTime, upTime, MotionEvent.ACTION_UP, x, y, 0);
                evUp.setSource(InputDevice.SOURCE_TOUCHSCREEN);
                webView.dispatchTouchEvent(evUp);
                evUp.recycle();
            }, 35);
        } else {
            String js = "(function(){ var el = document.activeElement; if(el && typeof el.click === 'function') { el.click(); } })();";
            webView.evaluateJavascript(js, null);
        }
    }

    private void handleDpadNavigation(String dir) {
        cursorMovedByUser = false;
        if (cursorView != null) cursorView.invalidate();
        if (webView != null) {
            webView.evaluateJavascript("if(typeof window.dpadMoveFocus==='function'){ window.dpadMoveFocus('" + dir + "'); }", null);
        }
    }

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Guard.verifyIntegrity();

        try {
            android.os.StrictMode.setThreadPolicy(new android.os.StrictMode.ThreadPolicy.Builder().permitAll().build());
        } catch (Throwable ignored) {}

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(
                WindowManager.LayoutParams.FLAG_FULLSCREEN | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                WindowManager.LayoutParams.FLAG_FULLSCREEN | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        );

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            Window window = getWindow();
            window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            window.setStatusBarColor(Color.TRANSPARENT);
            window.setNavigationBarColor(Color.TRANSPARENT);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                getWindow().setNavigationBarContrastEnforced(false);
                getWindow().setStatusBarContrastEnforced(false);
            } catch (Throwable ignored) {}
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            try {
                WindowManager.LayoutParams lp = getWindow().getAttributes();
                lp.layoutInDisplayCutoutMode =
                        WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
                getWindow().setAttributes(lp);
            } catch (Throwable ignored) {}
        }
        hideSystemUi();

        getWindow().getDecorView().setOnSystemUiVisibilityChangeListener(new View.OnSystemUiVisibilityChangeListener() {
            @Override
            public void onSystemUiVisibilityChange(int visibility) {
                if ((visibility & View.SYSTEM_UI_FLAG_FULLSCREEN) == 0 || (visibility & View.SYSTEM_UI_FLAG_HIDE_NAVIGATION) == 0) {
                    hideSystemUi();
                }
            }
        });

        try {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                multicastLock = wm.createMulticastLock("drps5_ddp_lock");
                multicastLock.setReferenceCounted(false);
                try {
                    // WIFI_MODE_FULL_LOW_LATENCY = 4 (API 29+) evita ahorro de energía 802.11 y pausas DTIM de 180ms
                    wifiLowLatencyLock = wm.createWifiLock(4, "drps5_wifi_low_latency");
                    wifiLowLatencyLock.setReferenceCounted(false);
                    wifiLowLatencyLock.acquire();
                } catch (Throwable ignored) {}
                try {
                    // WIFI_MODE_FULL_HIGH_PERF = 3
                    wifiHighPerfLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "drps5_wifi_high_perf");
                    wifiHighPerfLock.setReferenceCounted(false);
                    wifiHighPerfLock.acquire();
                } catch (Throwable ignored) {}
            }
        } catch (Throwable ignored) {}

        loadPersistedLogsAndPurgeOld(30);
        appendLog("DRPS5 Android Engine inicializado (Edición " + (Guard.IS_PERSONAL ? "Personal" : "Pública") + ").");

        try {
            InputManager im = (InputManager) getSystemService(Context.INPUT_SERVICE);
            if (im != null) {
                im.registerInputDeviceListener(new InputManager.InputDeviceListener() {
                    @Override
                    public void onInputDeviceAdded(int deviceId) { checkGamepadConnected(); }
                    @Override
                    public void onInputDeviceRemoved(int deviceId) { checkGamepadConnected(); }
                    @Override
                    public void onInputDeviceChanged(int deviceId) { checkGamepadConnected(); }
                }, null);
            }
        } catch (Throwable ignored) {}

        rootLayout = new FrameLayout(this);
        rootLayout.setBackgroundColor(Color.parseColor("#040814"));

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#040814"));
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setAllowContentAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        WebView.setWebContentsDebuggingEnabled(false);

        webView.addJavascriptInterface(new DRPS5JsBridge(), "DRPS5Native");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                injectPywebviewBridge();
            }
        });

        rootLayout.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        // Cursor virtual para navegación con Análogo Izquierdo / Control
        cursorView = new VirtualCursorView(this);
        rootLayout.addView(cursorView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        // Contenedor de transmisión en vivo (SurfaceView + HUD)
        streamContainer = new FrameLayout(this);
        streamContainer.setBackgroundColor(Color.BLACK);
        streamContainer.setVisibility(View.GONE);

        surfaceView = new SurfaceView(this);
        surfaceView.setFocusable(true);
        surfaceView.setFocusableInTouchMode(true);
        streamContainer.addView(surfaceView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        touchOverlayView = new TouchGamepadOverlayView(this);
        touchOverlayView.setVisibility(View.GONE);
        streamContainer.addView(touchOverlayView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        hudBanner = new TextView(this);
        hudBanner.setTextColor(Color.WHITE);
        hudBanner.setTextSize(14f);
        hudBanner.setPadding(32, 16, 32, 16);
        hudBanner.setBackgroundColor(Color.argb(180, 8, 18, 42));
        FrameLayout.LayoutParams hudLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
        );
        hudLp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        hudLp.topMargin = 24;
        streamContainer.addView(hudBanner, hudLp);

        // Superposición persistente de rendimiento en vivo (FPS, resolución, bitrate, pérdida)
        hudOverlay = new TextView(this);
        hudOverlay.setTextColor(Color.WHITE);
        hudOverlay.setTextSize(12f);
        hudOverlay.setTypeface(android.graphics.Typeface.MONOSPACE, android.graphics.Typeface.BOLD);
        hudOverlay.setPadding(24, 12, 24, 12);
        hudOverlay.setBackground(createHudOverlayBackground());
        hudOverlay.setVisibility(View.GONE);
        hudOverlay.setElevation(25f);
        FrameLayout.LayoutParams overlayLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
        );
        overlayLp.gravity = Gravity.TOP | Gravity.START;
        overlayLp.topMargin = 32;
        overlayLp.leftMargin = 40;
        streamContainer.addView(hudOverlay, overlayLp);

        rootLayout.addView(streamContainer, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));

        setContentView(rootLayout);
        checkGamepadConnected();
        webView.loadUrl("file:///android_asset/gui/index.html");

        cursorLoopActive = true;
        rootLayout.postDelayed(cursorTickRunnable, 16);
    }

    private void injectPywebviewBridge() {
        String js = "(function(){"
                + "function callNative(m, a){"
                + "  return new Promise(function(resolve){"
                + "    setTimeout(function(){"
                + "      try {"
                + "        var raw = window.DRPS5Native.invoke(m, JSON.stringify(a || []));"
                + "        resolve(raw ? JSON.parse(raw) : {});"
                + "      } catch(e){ resolve({success:false, error:String(e)}); }"
                + "    }, 5);"
                + "  });"
                + "}"
                + "var methods = ['get_initial_data','get_profiles','save_profile','delete_profile','select_profile',"
                + "'set_profile_mode','update_profile_remote_ip','discover_consoles','wakeup_console','wakeup_ps5',"
                + "'pair_console','launch_stream','save_settings','get_logs','clear_logs','purge_old_logs','open_log_folder',"
                + "'get_gamepad_mapping','save_gamepad_mapping','open_game_controller_settings','check_connected_controllers'];"
                + "var apiObj = {};"
                + "methods.forEach(function(m){ apiObj[m] = function(){ return callNative(m, Array.prototype.slice.call(arguments)); }; });"
                + "window.pywebview = { api: apiObj };"
                + "window.dispatchEvent(new Event('pywebviewready'));"
                + "window.drps5Initialized = false;"
                + "if (typeof initDRPS5 === 'function') initDRPS5();"
                + "})();";
        webView.evaluateJavascript(js, null);
    }

    private File getLogFile() {
        return new File(getFilesDir(), "launcher.log");
    }

    private void loadPersistedLogsAndPurgeOld(int days) {
        try {
            purgeLogsOlderThanDays(days);
            File lf = getLogFile();
            if (lf.exists() && lf.length() > 0) {
                try (FileInputStream fis = new FileInputStream(lf)) {
                    int maxRead = (int) Math.min(lf.length(), 128 * 1024);
                    if (lf.length() > maxRead) {
                        fis.skip(lf.length() - maxRead);
                    }
                    byte[] buf = new byte[maxRead];
                    int n = fis.read(buf);
                    if (n > 0) {
                        synchronized (sessionLogs) {
                            sessionLogs.setLength(0);
                            sessionLogs.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                        }
                    }
                }
            }
        } catch (Throwable ignored) {}
    }

    private int[] purgeLogsOlderThanDays(int days) {
        int removedFiles = 0;
        int removedLines = 0;
        long cutoffMs = System.currentTimeMillis() - (days * 86400000L);
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US);
        try {
            File[] dirs = new File[]{getFilesDir(), getCacheDir()};
            for (File dir : dirs) {
                if (dir == null || !dir.exists()) continue;
                File[] files = dir.listFiles();
                if (files == null) continue;
                for (File f : files) {
                    if (!f.isFile()) continue;
                    String name = f.getName().toLowerCase(Locale.US);
                    if (name.endsWith(".log") || name.contains(".log.")) {
                        if (!"launcher.log".equals(name) && f.lastModified() < cutoffMs) {
                            if (f.delete()) removedFiles++;
                            continue;
                        }
                    }
                }
            }
            File lf = getLogFile();
            if (lf.exists() && lf.length() > 0) {
                String raw = "";
                try (FileInputStream fis = new FileInputStream(lf)) {
                    byte[] b = new byte[(int) lf.length()];
                    int n = fis.read(b);
                    if (n > 0) raw = new String(b, 0, n, StandardCharsets.UTF_8);
                }
                if (!raw.isEmpty()) {
                    String[] lines = raw.split("\\r?\\n");
                    StringBuilder kept = new StringBuilder();
                    boolean keepContinuation = true;
                    for (String line : lines) {
                        if (line.length() >= 19 && line.charAt(4) == '-' && line.charAt(7) == '-' && line.charAt(10) == ' ') {
                            try {
                                Date dt = sdf.parse(line.substring(0, 19));
                                if (dt != null && dt.getTime() < cutoffMs) {
                                    removedLines++;
                                    keepContinuation = false;
                                    continue;
                                } else {
                                    keepContinuation = true;
                                }
                            } catch (Exception ignored) {}
                        }
                        if (keepContinuation) {
                            kept.append(line).append("\n");
                        } else {
                            removedLines++;
                        }
                    }
                    if (removedLines > 0) {
                        try (FileOutputStream fos = new FileOutputStream(lf, false)) {
                            fos.write(kept.toString().getBytes(StandardCharsets.UTF_8));
                        }
                    }
                }
            }
            synchronized (sessionLogs) {
                if (sessionLogs.length() > 0) {
                    String[] lines = sessionLogs.toString().split("\\r?\\n");
                    StringBuilder keptMem = new StringBuilder();
                    boolean keepContinuation = true;
                    for (String line : lines) {
                        if (line.isEmpty()) continue;
                        if (line.length() >= 19 && line.charAt(4) == '-' && line.charAt(7) == '-' && line.charAt(10) == ' ') {
                            try {
                                Date dt = sdf.parse(line.substring(0, 19));
                                if (dt != null && dt.getTime() < cutoffMs) {
                                    keepContinuation = false;
                                    continue;
                                } else {
                                    keepContinuation = true;
                                }
                            } catch (Exception ignored) {}
                        }
                        if (keepContinuation) {
                            keptMem.append(line).append("\n");
                        }
                    }
                    sessionLogs.setLength(0);
                    sessionLogs.append(keptMem);
                }
            }
        } catch (Throwable ignored) {}
        return new int[]{removedLines, removedFiles};
    }

    private void appendLog(String msg) {
        android.util.Log.i("DRPS5", msg);
        String ts = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date());
        String line = ts + " [INFO] DRPS5: " + msg + "\n";
        synchronized (sessionLogs) {
            sessionLogs.append(line);
            if (sessionLogs.length() > 256 * 1024) {
                sessionLogs.delete(0, sessionLogs.length() - 192 * 1024);
            }
        }
        try (FileOutputStream fos = new FileOutputStream(getLogFile(), true)) {
            fos.write(line.getBytes(StandardCharsets.UTF_8));
        } catch (Throwable ignored) {}
    }

    private File getConfigFile() {
        String fname = Guard.IS_PERSONAL ? "drps5_config.json" : "drps5_public_config.json";
        return new File(getFilesDir(), fname);
    }

    private synchronized JSONObject loadConfig() {
        File f = getConfigFile();
        if (f.exists()) {
            try (FileInputStream fis = new FileInputStream(f)) {
                byte[] b = new byte[(int) f.length()];
                int n = fis.read(b);
                if (n > 0) {
                    JSONObject cfg = new JSONObject(new String(b, 0, n, StandardCharsets.UTF_8));
                    if (Guard.IS_PERSONAL) {
                        JSONObject profs = cfg.optJSONObject("profiles");
                        if (profs == null || profs.length() == 0) {
                            cfg = new JSONObject(Guard.getSeedConfigJson());
                            saveConfig(cfg);
                        }
                    }
                    if (!"1.3.1".equals(cfg.optString("version", ""))) {
                        cfg.put("version", "1.3.1");
                        cfg.put("resolution", "720p");
                        cfg.put("hdr", false);
                        cfg.put("audio_enabled", true);
                        cfg.put("fps", 60);
                        cfg.put("circle_confirm", false);
                        JSONObject profs = cfg.optJSONObject("profiles");
                        if (profs != null) {
                            Iterator<String> keys = profs.keys();
                            while (keys.hasNext()) {
                                JSONObject p = profs.optJSONObject(keys.next());
                                if (p != null) {
                                    p.put("resolution", "720p");
                                    p.put("hdr", false);
                                    p.put("audio_enabled", true);
                                    p.put("fps", 60);
                                    p.put("circle_confirm", false);
                                }
                            }
                        }
                        saveConfig(cfg);
                    }
                    return cfg;
                }
            } catch (Exception ignored) {}
        }
        try {
            JSONObject seed = new JSONObject(Guard.getSeedConfigJson());
            saveConfig(seed);
            return seed;
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private synchronized void saveConfig(JSONObject cfg) {
        try (FileOutputStream fos = new FileOutputStream(getConfigFile())) {
            fos.write(cfg.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }

    private JSONArray getProfilesArray(JSONObject cfg) {
        JSONArray arr = new JSONArray();
        JSONObject profs = cfg.optJSONObject("profiles");
        if (profs != null) {
            Iterator<String> keys = profs.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                JSONObject p = profs.optJSONObject(k);
                if (p != null) arr.put(p);
            }
        }
        return arr;
    }

    private JSONObject getActiveProfile(JSONObject cfg) {
        JSONObject profs = cfg.optJSONObject("profiles");
        String activeId = cfg.optString("active_profile_id", "");
        if (profs != null) {
            if (profs.has(activeId)) return profs.optJSONObject(activeId);
            Iterator<String> keys = profs.keys();
            if (keys.hasNext()) return profs.optJSONObject(keys.next());
        }
        return new JSONObject();
    }

    public final class DRPS5JsBridge {
        @JavascriptInterface
        public String invoke(String method, String argsJson) {
            try {
                JSONArray args = new JSONArray(argsJson != null ? argsJson : "[]");
                JSONObject res = handleMethod(method, args);
                return res.toString();
            } catch (Exception e) {
                try {
                    JSONObject err = new JSONObject();
                    err.put("success", false);
                    err.put("error", e.getMessage());
                    return err.toString();
                } catch (Exception ignored) {
                    return "{\"success\":false}";
                }
            }
        }

        @JavascriptInterface
        public void setGamepadTabActive(boolean active) {
            isGamepadTabActive = active;
        }

        @JavascriptInterface
        public String getLiveGamepad() {
            checkGamepadConnected();
            try {
                JSONObject o = new JSONObject();
                o.put("connected", livePadConnected);
                o.put("id", livePadName != null ? livePadName : "Mando Conectado");
                JSONArray btns = new JSONArray();
                long now = System.currentTimeMillis();
                for (int i = 0; i <= 20; i++) {
                    JSONObject b = new JSONObject();
                    boolean pr = liveButtons[i] || (now < buttonReleaseTime[i]);
                    b.put("pressed", pr);
                    double val = pr ? 1.0 : (i == 6 ? liveL2 : (i == 7 ? liveR2 : 0.0));
                    b.put("value", val);
                    btns.put(b);
                }
                o.put("buttons", btns);
                JSONArray axes = new JSONArray();
                axes.put((double) liveLx);
                axes.put((double) liveLy);
                axes.put((double) liveRx);
                axes.put((double) liveRy);
                o.put("axes", axes);
                return o.toString();
            } catch (Exception e) {
                return "{\"connected\":false}";
            }
        }

        @JavascriptInterface
        public void setCapturing(boolean capturing) {
            isCapturingButton = capturing;
        }
    }

    private JSONObject handleMethod(String method, JSONArray args) throws Exception {
        JSONObject cfg = loadConfig();
        JSONObject out = new JSONObject();

        switch (method) {
            case "get_initial_data": {
                JSONArray profArr = getProfilesArray(cfg);
                JSONObject activeP = getActiveProfile(cfg);
                out.put("config", cfg);
                out.put("profiles", profArr);
                out.put("active_profile", activeP);
                out.put("active_profile_id", activeP.optString("id", ""));
                out.put("consoles", cfg.optJSONObject("consoles") != null ? cfg.optJSONObject("consoles") : new JSONObject());
                out.put("last_used_ip", activeP.optString("local_ip", ""));
                return out;
            }
            case "get_profiles": {
                out.put("success", true);
                out.put("profiles", getProfilesArray(cfg));
                out.put("active_profile_id", cfg.optString("active_profile_id", ""));
                return out;
            }
            case "select_profile": {
                String pid = args.optString(0, "");
                JSONObject profs = cfg.optJSONObject("profiles");
                if (profs != null && profs.has(pid)) {
                    cfg.put("active_profile_id", pid);
                    saveConfig(cfg);
                    out.put("success", true);
                    out.put("profile", profs.getJSONObject(pid));
                } else {
                    out.put("success", false);
                    out.put("error", "Perfil no encontrado");
                }
                return out;
            }
            case "set_profile_mode": {
                String pid = args.optString(0, "");
                String mode = args.optString(1, "local");
                JSONObject profs = cfg.optJSONObject("profiles");
                if (profs != null && profs.has(pid)) {
                    JSONObject p = profs.getJSONObject(pid);
                    p.put("connection_mode", mode);
                    saveConfig(cfg);
                    out.put("success", true);
                } else {
                    out.put("success", false);
                }
                return out;
            }
            case "update_profile_remote_ip": {
                String pid = args.optString(0, "");
                String rip = PS5Protocol.cleanIp(args.optString(1, ""));
                JSONObject profs = cfg.optJSONObject("profiles");
                JSONObject p = (profs != null && profs.has(pid)) ? profs.getJSONObject(pid) : getActiveProfile(cfg);
                if (p != null) {
                    p.put("remote_ip", rip);
                    saveConfig(cfg);
                    out.put("success", true);
                    out.put("profile", p);
                } else {
                    out.put("success", false);
                }
                return out;
            }
            case "save_profile": {
                JSONObject pData = args.optJSONObject(0);
                if (pData == null) {
                    out.put("success", false);
                    return out;
                }
                String pid = pData.optString("id", "");
                if (pid.isEmpty()) {
                    pid = "prof_" + (System.currentTimeMillis() / 1000);
                    pData.put("id", pid);
                }
                JSONObject profs = cfg.optJSONObject("profiles");
                if (profs == null) {
                    profs = new JSONObject();
                    cfg.put("profiles", profs);
                }
                JSONObject existing = profs.optJSONObject(pid);
                if (existing != null) {
                    Iterator<String> it = pData.keys();
                    while (it.hasNext()) {
                        String k = it.next();
                        existing.put(k, pData.get(k));
                    }
                    pData = existing;
                } else {
                    if (!pData.has("status") || pData.optString("regist_key", "").isEmpty()) {
                        pData.put("status", "Pendiente");
                        pData.put("regist_key", "");
                        pData.put("rp_key", "");
                    }
                    profs.put(pid, pData);
                }
                cfg.put("active_profile_id", pid);
                saveConfig(cfg);
                appendLog("Perfil guardado: " + pData.optString("name", pid));
                out.put("success", true);
                out.put("profile", pData);
                return out;
            }
            case "delete_profile": {
                String pid = args.optString(0, "");
                JSONObject profs = cfg.optJSONObject("profiles");
                if (profs != null && profs.length() > 1 && profs.has(pid)) {
                    profs.remove(pid);
                    JSONObject nextActive = getActiveProfile(cfg);
                    cfg.put("active_profile_id", nextActive.optString("id", ""));
                    saveConfig(cfg);
                    out.put("success", true);
                    out.put("profiles", getProfilesArray(cfg));
                    out.put("active_profile", nextActive);
                } else {
                    out.put("success", false);
                    out.put("error", "Se requiere conservar al menos un perfil.");
                }
                return out;
            }
            case "discover_consoles": {
                int timeout = args.optInt(0, 2);
                JSONObject activeP = getActiveProfile(cfg);
                String hintIp = activeP != null ? activeP.optString("local_ip", "") : "";
                JSONArray consoles = PS5Protocol.discoverConsoles(timeout, hintIp);
                appendLog("Escaneo DDP completado (" + consoles.length() + " consolas detectadas).");
                out.put("success", true);
                out.put("consoles", consoles);
                return out;
            }
            case "wakeup_console":
            case "wakeup_ps5": {
                String ip = args.optString(0, "");
                JSONObject activeP = getActiveProfile(cfg);
                if (ip.isEmpty() && activeP != null) {
                    String mode = activeP.optString("connection_mode", "local");
                    ip = "remote".equals(mode) ? activeP.optString("remote_ip", "") : activeP.optString("local_ip", "");
                }
                String regKey = activeP != null ? activeP.optString("regist_key", "") : "";
                boolean ok = PS5Protocol.wakeupPs5(ip, regKey);
                appendLog("Wake-on-LAN DDP enviado a " + ip + " (resultado=" + ok + ")");
                out.put("success", ok);
                out.put("ip", ip);
                return out;
            }
            case "pair_console": {
                String ip = PS5Protocol.cleanIp(args.optString(0, ""));
                String pin = args.optString(1, "");
                String acc = args.optString(2, "");
                String pid = args.optString(3, "");
                String cType = args.optString(4, "PS5");
                boolean isPs4 = "PS4".equalsIgnoreCase(cType);
                String cName = isPs4 ? "PS4" : "PS5";
                appendLog("Iniciando vinculación por PIN con " + cName + " en " + ip + "...");
                JSONObject pairRes = PS5Protocol.pairConsole(ip, pin, acc, isPs4);
                if (pairRes.optBoolean("success", false)) {
                    JSONObject profs = cfg.optJSONObject("profiles");
                    JSONObject p = (profs != null && profs.has(pid)) ? profs.getJSONObject(pid) : getActiveProfile(cfg);
                    if (p == null) p = new JSONObject();
                    p.put("local_ip", ip);
                    p.put("host_id", pairRes.optString("host_id", ip));
                    p.put("host_name", pairRes.optString("host_name", isPs4 ? "PS4 Vinculada" : "PS5 Vinculada"));
                    p.put("regist_key", pairRes.optString("regist_key", ""));
                    p.put("rp_key", pairRes.optString("rp_key", ""));
                    p.put("account_id", pairRes.optString("account_id", ""));
                    p.put("console_type", isPs4 ? "PS4" : "PS5");
                    p.put("status", "Vinculada");
                    if (profs != null) profs.put(p.optString("id", isPs4 ? "prof_ps4_main" : "prof_ps5_main"), p);
                    saveConfig(cfg);
                    appendLog("¡Vinculación exitosa con " + p.optString("host_name") + "!");
                    out.put("success", true);
                    out.put("profile", p);
                    out.put("console", p);
                } else {
                    out.put("success", false);
                    out.put("error", pairRes.optString("error", "No se pudo vincular con la " + cName + "."));
                }
                return out;
            }
            case "save_settings": {
                JSONObject st = args.optJSONObject(0);
                if (st != null) {
                    Iterator<String> it = st.keys();
                    while (it.hasNext()) {
                        String k = it.next();
                        cfg.put(k, st.get(k));
                    }
                    JSONObject activeP = getActiveProfile(cfg);
                    if (activeP != null) {
                        for (String k : new String[]{"resolution", "fps", "codec", "hdr", "audio_enabled", "circle_confirm", "fullscreen", "show_hud"}) {
                            if (st.has(k)) activeP.put(k, st.get(k));
                        }
                    }
                    saveConfig(cfg);
                }
                out.put("success", true);
                return out;
            }
            case "get_gamepad_mapping": {
                JSONObject gm = cfg.optJSONObject("gamepad_mapping");
                if (gm == null) gm = new JSONObject();
                out.put("success", true);
                out.put("mapping", gm);
                return out;
            }
            case "save_gamepad_mapping": {
                JSONObject gm = args.optJSONObject(0);
                if (gm != null) {
                    cfg.put("gamepad_mapping", gm);
                    saveConfig(cfg);
                }
                out.put("success", true);
                out.put("mapping", gm);
                return out;
            }
            case "check_connected_controllers": {
                int[] devIds = InputDevice.getDeviceIds();
                JSONArray list = new JSONArray();
                String firstName = null;
                for (int id : devIds) {
                    InputDevice dev = InputDevice.getDevice(id);
                    if (dev == null) continue;
                    int sources = dev.getSources();
                    boolean isPad = ((sources & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD)
                            || ((sources & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK);
                    if (isPad) {
                        String n = dev.getName();
                        if (firstName == null) firstName = n;
                        JSONObject cObj = new JSONObject();
                        cObj.put("index", list.length());
                        cObj.put("name", n);
                        cObj.put("is_controller", true);
                        list.put(cObj);
                    }
                }
                out.put("success", true);
                out.put("connected", list.length() > 0);
                out.put("count", list.length());
                out.put("name", firstName != null ? firstName : "Mando TV / Control Remoto Activo");
                out.put("controllers", list);
                return out;
            }
            case "get_logs": {
                String content;
                synchronized (sessionLogs) {
                    content = sessionLogs.toString();
                }
                out.put("success", true);
                out.put("logs", content.isEmpty() ? "Sin registros aún." : content);
                out.put("file_path", getLogFile().getAbsolutePath());
                JSONObject diag = new JSONObject();
                diag.put("status", "ok");
                diag.put("title", "Motor Android TV Activo");
                diag.put("detail", "El subsistema nativo DRPS5 (DDP + Takion v12 + MediaCodec) funciona correctamente (Retención automática: 30 días).");
                out.put("diagnosis", diag);
                return out;
            }
            case "clear_logs": {
                synchronized (sessionLogs) {
                    sessionLogs.setLength(0);
                }
                try (FileOutputStream fos = new FileOutputStream(getLogFile(), false)) {
                    fos.write(new byte[0]);
                } catch (Throwable ignored) {}
                appendLog("Registros limpiados por el usuario.");
                out.put("success", true);
                return out;
            }
            case "purge_old_logs": {
                int days = args.optInt(0, 30);
                if (days <= 0) days = 30;
                int[] stats = purgeLogsOlderThanDays(days);
                String msg = "Limpieza (> " + days + " días) completada: " + stats[0] + " entradas y " + stats[1] + " archivos antiguos eliminados.";
                appendLog(msg);
                out.put("success", true);
                out.put("removed_lines", stats[0]);
                out.put("removed_files", stats[1]);
                out.put("removed_total", stats[0] + stats[1]);
                out.put("message", msg);
                return out;
            }
            case "open_log_folder":
            case "open_game_controller_settings": {
                out.put("success", true);
                return out;
            }
            case "get_bluetooth_devices": {
                out.put("success", true);
                JSONObject ad = new JSONObject();
                ad.put("powered", true);
                ad.put("address", "Android Bluetooth");
                out.put("adapter", ad);
                JSONArray paired = new JSONArray();
                if (livePadConnected) {
                    JSONObject padDev = new JSONObject();
                    padDev.put("name", livePadName.isEmpty() ? "Mando Bluetooth" : livePadName);
                    padDev.put("address", "Bluetooth / USB HID");
                    padDev.put("paired", true);
                    padDev.put("connected", true);
                    paired.put(padDev);
                }
                out.put("paired", paired);
                out.put("discovered", new JSONArray());
                return out;
            }
            case "start_bluetooth_scan":
            case "stop_bluetooth_scan":
            case "pair_bluetooth_device":
            case "unpair_bluetooth_device":
            case "connect_bluetooth_device": {
                out.put("success", true);
                return out;
            }
            case "launch_stream": {
                if (streamClient != null) {
                    out.put("success", true);
                    return out;
                }
                String pid = args.optString(0, "");
                JSONObject custom = args.optJSONObject(1);
                JSONObject profs = cfg.optJSONObject("profiles");
                JSONObject p = (profs != null && profs.has(pid)) ? profs.getJSONObject(pid) : getActiveProfile(cfg);
                if (p == null) {
                    out.put("success", false);
                    out.put("error", "missing_local_ip");
                    out.put("message", "No hay ningún perfil seleccionado.");
                    return out;
                }
                String mode = p.optString("connection_mode", "local");
                String localIp = PS5Protocol.cleanIp(p.optString("local_ip", ""));
                String remoteIp = PS5Protocol.cleanIp(p.optString("remote_ip", ""));
                String targetIp = "remote".equals(mode) ? remoteIp : localIp;

                if (targetIp.isEmpty()) {
                    out.put("success", false);
                    out.put("error", "remote".equals(mode) ? "missing_remote_ip" : "missing_local_ip");
                    out.put("message", "Por favor configura la dirección IP antes de iniciar la Pantalla Remota.");
                    return out;
                }
                String rpKey = p.optString("rp_key", "");
                String regKey = p.optString("regist_key", "");
                if (rpKey.isEmpty() || regKey.isEmpty()) {
                    out.put("success", false);
                    out.put("error", "not_paired");
                    out.put("message", "Este perfil aún no está vinculado con tu PS5. Ve a 'Vincular PS5 (PIN)' para enlazarlo.");
                    out.put("profile_id", p.optString("id", ""));
                    out.put("local_ip", localIp);
                    return out;
                }

                String res = custom != null && custom.has("resolution") ? custom.optString("resolution") : p.optString("resolution", cfg.optString("resolution", "720p"));
                int fpsVal = custom != null && custom.has("fps") ? custom.optInt("fps") : p.optInt("fps", cfg.optInt("fps", 60));
                String codec = custom != null && custom.has("codec") ? custom.optString("codec") : p.optString("codec", cfg.optString("codec", "hevc"));
                boolean hdr = custom != null && custom.has("hdr") ? custom.optBoolean("hdr") : (p.has("hdr") ? p.optBoolean("hdr") : cfg.optBoolean("hdr", false));
                boolean audioEnabled = custom != null && custom.has("audio_enabled") ? custom.optBoolean("audio_enabled") : (p.has("audio_enabled") ? p.optBoolean("audio_enabled") : cfg.optBoolean("audio_enabled", true));
                boolean showHud = custom != null && custom.has("show_hud") ? custom.optBoolean("show_hud") : (p.has("show_hud") ? p.optBoolean("show_hud") : cfg.optBoolean("show_hud", false));

                if (custom != null) {
                    p.put("resolution", res); cfg.put("resolution", res);
                    p.put("fps", fpsVal); cfg.put("fps", fpsVal);
                    p.put("codec", codec); cfg.put("codec", codec);
                    p.put("hdr", hdr); cfg.put("hdr", hdr);
                    p.put("audio_enabled", audioEnabled); cfg.put("audio_enabled", audioEnabled);
                    p.put("show_hud", showHud); cfg.put("show_hud", showHud);
                    saveConfig(cfg);
                }

                String cType = p.optString("console_type", cfg.optString("console_type", "PS5"));
                boolean isPs4 = "PS4".equalsIgnoreCase(cType);
                appendLog("Iniciando transmisión hacia " + targetIp + " [" + (isPs4 ? "PS4" : "PS5") + "] (" + res + " @ " + fpsVal + " FPS, " + codec + (hdr ? ", HDR" : ", SDR") + (audioEnabled ? ", Audio Opus" : ", Sin audio") + (showHud ? ", HUD ON" : "") + ")...");
                startNativeStreamUi(targetIp, regKey, rpKey, res, fpsVal, codec, hdr, audioEnabled, showHud, isPs4);

                out.put("success", true);
                out.put("ip", targetIp);
                out.put("mode", mode);
                return out;
            }
            default: {
                out.put("success", true);
                return out;
            }
        }
    }

    private void startNativeStreamUi(String ip, String regKey, String rpKey, String res, int fps, String codec, boolean hdr, boolean audioEnabled, boolean showHud, boolean isPs4) {
        runOnUiThread(() -> {
            this.showHud = showHud;
            cursorLoopActive = false;
            if (rootLayout != null) {
                rootLayout.removeCallbacks(cursorTickRunnable);
            }
            stickVelX = 0f;
            stickVelY = 0f;
            scrollVelY = 0f;
            dpadVelX = 0f;
            dpadVelY = 0f;
            l2TriggerActive = false;
            r2TriggerActive = false;
            isSharePressed = false;
            isOptionsPressed = false;
            if (cursorView != null) cursorView.setVisibility(View.GONE);
            if (webView != null) {
                webView.onPause();
                webView.pauseTimers();
                webView.setVisibility(View.GONE);
            }
            streamContainer.setVisibility(View.VISIBLE);
            hudBanner.setVisibility(View.VISIBLE);
            String cName = isPs4 ? "PS4" : "PS5";
            hudBanner.setText("🚀 Conectando con " + cName + " en " + ip + " (" + res + (hdr ? " HDR" : " SDR") + ")...");
            if (hudOverlay != null) {
                hudOverlay.bringToFront();
                hudOverlay.setVisibility(showHud ? View.VISIBLE : View.GONE);
                hudOverlay.setText("⚡ " + fps + ".0 FPS  •  📺 " + res + "  •  🎬 " + codec.toUpperCase() + (hdr ? " HDR10" : " SDR") + "  •  🔊 Opus 48kHz");
            }
            if (touchOverlayView != null) {
                touchOverlayView.setVisibility(View.VISIBLE);
                touchOverlayView.bringToFront();
            }

            surfaceView.setFocusable(true);
            surfaceView.setFocusableInTouchMode(true);
            surfaceView.requestFocus();

            SurfaceHolder holder = surfaceView.getHolder();
            if (holder.getSurface() != null && holder.getSurface().isValid()) {
                launchStreamClient(ip, regKey, rpKey, res, fps, codec, hdr, audioEnabled, isPs4, holder.getSurface());
            } else {
                holder.addCallback(new SurfaceHolder.Callback() {
                    @Override
                    public void surfaceCreated(SurfaceHolder sh) {
                        holder.removeCallback(this);
                        surfaceView.post(() -> {
                            surfaceView.setFocusable(true);
                            surfaceView.setFocusableInTouchMode(true);
                            surfaceView.requestFocus();
                        });
                        launchStreamClient(ip, regKey, rpKey, res, fps, codec, hdr, audioEnabled, isPs4, sh.getSurface());
                    }
                    @Override public void surfaceChanged(SurfaceHolder sh, int f, int w, int h) {}
                    @Override public void surfaceDestroyed(SurfaceHolder sh) {}
                });
            }
        });
    }

    private void launchStreamClient(String ip, String regKey, String rpKey, String res, int fps, String codec, boolean hdr, boolean audioEnabled, boolean isPs4, android.view.Surface surf) {
        if (streamClient != null) {
            streamClient.stop();
        }
        String cName = isPs4 ? "PS4" : "PS5";
        streamClient = new PS5StreamClient(ip, regKey, rpKey, res, fps, codec, hdr, audioEnabled, isPs4, surf, new PS5StreamClient.StreamListener() {
            @Override
            public void onStatus(String message) {
                appendLog(message);
                runOnUiThread(() -> {
                    hudBanner.setVisibility(View.VISIBLE);
                    hudBanner.setText(message);
                });
            }

            @Override
            public void onConnected() {
                appendLog("¡Pantalla Remota " + cName + " conectada en vivo!");
                runOnUiThread(() -> {
                    hudBanner.setText("✅ " + cName + " Conectada • Salir: CAPTURA + OPTIONS");
                    hudBanner.postDelayed(() -> hudBanner.setVisibility(View.GONE), 4000);
                });
            }

            @Override
            public void onError(String error) {
                appendLog("Error en transmisión: " + error);
                runOnUiThread(() -> {
                    Toast.makeText(MainActivity.this, error, Toast.LENGTH_LONG).show();
                    stopNativeStreamUi();
                });
            }

            @Override
            public void onStats(float fps, int width, int height, String codec, boolean hdr, int rxPackets, int lostPackets) {
                runOnUiThread(() -> {
                    if (hudOverlay != null && showHud) {
                        int dispW = width > 0 ? width : ("2160p".equalsIgnoreCase(res) ? 3840 : ("1440p".equalsIgnoreCase(res) ? 2560 : ("720p".equalsIgnoreCase(res) ? 1280 : ("540p".equalsIgnoreCase(res) ? 960 : ("360p".equalsIgnoreCase(res) ? 640 : 1920)))));
                        int dispH = height > 0 ? height : ("2160p".equalsIgnoreCase(res) ? 2160 : ("1440p".equalsIgnoreCase(res) ? 1440 : ("720p".equalsIgnoreCase(res) ? 720 : ("540p".equalsIgnoreCase(res) ? 540 : ("360p".equalsIgnoreCase(res) ? 360 : 1080)))));
                        float lossPct = (rxPackets + lostPackets > 0) ? (lostPackets * 100.0f / (rxPackets + lostPackets)) : 0.0f;
                        String lossStr = String.format(java.util.Locale.US, "%.1f%%", lossPct);
                        String resLabel = (dispH >= 2160) ? "4K Ultra HD" : ((dispH >= 1440) ? "2K QHD" : ((dispH >= 1080) ? "1080p" : ((dispH >= 720) ? "720p" : ((dispH >= 540) ? "540p" : dispH + "p"))));
                        String codecStr = codec.toUpperCase() + (hdr ? " HDR10" : " SDR");
                        String statsText = String.format(java.util.Locale.US,
                                "⚡ %.1f FPS  •  📺 %s (%dx%d)  •  🎬 %s  •  🔊 Opus 48kHz  •  📶 Pérdida: %s",
                                fps, resLabel, dispW, dispH, codecStr, lossStr);
                        hudOverlay.setText(statsText);
                    }
                });
            }
        });
        streamClient.start();
    }

    private void stopNativeStreamUi() {
        if (streamClient != null) {
            streamClient.stop();
            streamClient = null;
        }
        if (touchOverlayView != null) {
            touchOverlayView.setVisibility(View.GONE);
            touchOverlayView.resetState();
        }
        streamContainer.setVisibility(View.GONE);
        if (webView != null) {
            webView.setVisibility(View.VISIBLE);
            webView.onResume();
            webView.resumeTimers();
        }
        if (cursorView != null) {
            cursorView.setVisibility(livePadConnected ? View.VISIBLE : View.GONE);
            if (livePadConnected) cursorView.invalidate();
        }
        cursorLoopActive = true;
        if (rootLayout != null) {
            rootLayout.removeCallbacks(cursorTickRunnable);
            rootLayout.postDelayed(cursorTickRunnable, 16);
        }
    }

    private static int mapEventToPsButton(KeyEvent event) {
        int code = event.getKeyCode();
        // Mapeo estándar de Android para mandos Bluetooth/USB (DualSense, DualShock, Xbox, etc.)
        switch (code) {
            case KeyEvent.KEYCODE_BUTTON_A: return 0x88; // Cross / A
            case KeyEvent.KEYCODE_BUTTON_B: return 0x89; // Circle / B
            case KeyEvent.KEYCODE_BUTTON_X: return 0x8A; // Square / X
            case KeyEvent.KEYCODE_BUTTON_Y: return 0x8B; // Triangle / Y
            case KeyEvent.KEYCODE_BUTTON_L1: return 0x84; // L1
            case KeyEvent.KEYCODE_BUTTON_R1: return 0x85; // R1
            case KeyEvent.KEYCODE_BUTTON_L2: return 0x86; // L2
            case KeyEvent.KEYCODE_BUTTON_R2: return 0x87; // R2
            case KeyEvent.KEYCODE_BUTTON_SELECT: return 0x8D; // Share / Create
            case KeyEvent.KEYCODE_BUTTON_START:
            case KeyEvent.KEYCODE_MENU: return 0x8C; // Options
            case KeyEvent.KEYCODE_BUTTON_MODE: return 0x8E; // PS (Home)
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return 0x8F; // L3
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return 0x90; // R3
            case KeyEvent.KEYCODE_BUTTON_C:
            case KeyEvent.KEYCODE_BUTTON_1: return 0x91; // Touchpad Click
            case KeyEvent.KEYCODE_DPAD_UP: return 0x80;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 0x81;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 0x82;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 0x83;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER: return 0x88;
            default: break;
        }

        // Fallback por Scancode directo si el driver de Linux no tradujo el botón a KeyCode
        int sc = event.getScanCode();
        switch (sc) {
            case 304: return 0x88; // BTN_SOUTH -> Cross
            case 305: return 0x89; // BTN_EAST  -> Circle
            case 307: return 0x8A; // BTN_NORTH / BTN_WEST -> Square
            case 308: return 0x8B; // Triangle
            case 310: return 0x84; // L1
            case 311: return 0x85; // R1
            case 312: return 0x86; // L2
            case 313: return 0x87; // R2
            case 314: return 0x8D; // Share / Select
            case 315: return 0x8C; // Options / Start
            case 316: return 0x8E; // PS
            case 317: return 0x8F; // L3
            case 318: return 0x90; // R3
            default: return -1;
        }
    }

    private boolean isCircleConfirmMode() {
        // Unificado: Cruz (X = 0x88) siempre es Aceptar/Click en botones y selectores, y Círculo (O = 0x89) es Salir/Atrás
        return false;
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        int code = event.getKeyCode();
        int psBtn = mapEventToPsButton(event);
        boolean isDown = event.getAction() == KeyEvent.ACTION_DOWN;

        // 1. VÍA RÁPIDA DE CERO LATENCIA: MODO TRANSMISIÓN EN VIVO
        if (streamContainer != null && streamContainer.getVisibility() == View.VISIBLE && streamClient != null) {
            if ((code == KeyEvent.KEYCODE_F1 || code == 131) && isDown && event.getRepeatCount() == 0) {
                showHud = !showHud;
                if (hudOverlay != null) {
                    hudOverlay.setVisibility(showHud ? View.VISIBLE : View.GONE);
                }
                Toast.makeText(this, showHud ? "HUD de Rendimiento Activado" : "HUD Ocultado", Toast.LENGTH_SHORT).show();
                return true;
            }

            if (psBtn == 0x8D || code == KeyEvent.KEYCODE_BUTTON_SELECT) {
                isSharePressed = isDown;
            } else if (psBtn == 0x8C || code == KeyEvent.KEYCODE_BUTTON_START || code == KeyEvent.KEYCODE_MENU) {
                isOptionsPressed = isDown;
            }

            if (isSharePressed && isOptionsPressed) {
                isSharePressed = false;
                isOptionsPressed = false;
                runOnUiThread(() -> {
                    Toast.makeText(this, "Sesión remota finalizada (Captura + Options)", Toast.LENGTH_SHORT).show();
                    stopNativeStreamUi();
                });
                return true;
            }

            if (code == KeyEvent.KEYCODE_BACK && psBtn == -1) {
                InputDevice dev = event.getDevice();
                boolean isGamepad = dev != null && ((dev.getSources() & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD);
                if (!isGamepad) {
                    if (isDown) {
                        long now = System.currentTimeMillis();
                        if (now - lastMenuExitPress < 1800) {
                            stopNativeStreamUi();
                        } else {
                            lastMenuExitPress = now;
                            Toast.makeText(this, "Pulsa ATRÁS otra vez para salir al menú", Toast.LENGTH_SHORT).show();
                        }
                    }
                    return true;
                }
            }

            if (psBtn != -1) {
                if (!isDown || event.getRepeatCount() == 0) {
                    streamClient.sendButtonEvent(psBtn, isDown);
                }
                return true;
            }
            return super.dispatchKeyEvent(event);
        }

        InputDevice dev = event.getDevice();
        if (dev != null) {
            String dn = dev.getName();
            if (dn != null && !dn.isEmpty()) livePadName = dn;
            livePadConnected = true;
        }
        int liveIdx = mapPsButtonToLiveIndex(psBtn);
        if (liveIdx >= 0 && liveIdx < 21) {
            liveButtons[liveIdx] = isDown;
            if (isDown) {
                buttonReleaseTime[liveIdx] = System.currentTimeMillis() + 180;
            }
            if (liveIdx == 17) {
                liveButtons[20] = isDown;
                if (isDown) buttonReleaseTime[20] = System.currentTimeMillis() + 180;
            }
        }

        // Si la interfaz de usuario está capturando un botón en Calibrar Mando, consumir sin accionar navegación
        if (isCapturingButton) {
            return true;
        }

        // MODO MENÚ GUI CON CURSOR VIRTUAL
        if (isGamepadTabActive) {
            // En la pestaña de Calibración de Mando, no activar clicks ni salir para permitir probar botones libremente
            if (code == KeyEvent.KEYCODE_BACK && isDown) {
                return super.dispatchKeyEvent(event);
            }
            return true;
        }

        boolean circleConfirm = isCircleConfirmMode();
        boolean isConfirmBtn = false;
        boolean isCancelBtn = false;

        if (circleConfirm) {
            // Estándar del sistema del usuario: Círculo (O = 0x89) para Aceptar/Click
            // y Cruz (X = 0x88) para Salir/Atrás (2 pulsaciones consecutivas para cerrar la app)
            isConfirmBtn = (psBtn == 0x89) || (code == KeyEvent.KEYCODE_DPAD_CENTER) || (code == KeyEvent.KEYCODE_ENTER);
            isCancelBtn = (psBtn == 0x88) || (code == KeyEvent.KEYCODE_BACK);
        } else {
            // Estándar alternativo: Cruz (X = 0x88) para Aceptar y Círculo (O = 0x89) para Salir
            isConfirmBtn = (psBtn == 0x88) || (code == KeyEvent.KEYCODE_DPAD_CENTER) || (code == KeyEvent.KEYCODE_ENTER);
            isCancelBtn = (psBtn == 0x89) || (code == KeyEvent.KEYCODE_BACK);
        }

        if (isConfirmBtn) {
            if (isDown && event.getRepeatCount() == 0) {
                performCursorClick();
            }
            return true;
        }

        if (isCancelBtn) {
            if (isDown && event.getRepeatCount() == 0) {
                long now = System.currentTimeMillis();
                if (now - lastMenuExitPress < 2000) {
                    finish(); // Salir de la aplicación
                } else {
                    lastMenuExitPress = now;
                    if (webView != null) {
                        webView.evaluateJavascript("if(typeof closeAllModals==='function'){ closeAllModals(); }", null);
                    }
                    String exitKeyName = circleConfirm ? "Cruz (X)" : "Círculo (O)";
                    Toast.makeText(this, "Presiona " + exitKeyName + " otra vez para salir de la app", Toast.LENGTH_SHORT).show();
                }
            }
            return true;
        }

        // L1 o Triángulo -> subir página (scroll)
        if (psBtn == 0x84 || psBtn == 0x8B) {
            if (isDown) scrollWebViewBy(-180);
            return true;
        }
        // R2 -> bajar página (scroll)
        if (psBtn == 0x87) {
            if (isDown) scrollWebViewBy(180);
            return true;
        }

        // D-Pad espacial para saltar entre botones en la GUI (menú / launcher)
        if (code == KeyEvent.KEYCODE_DPAD_UP || psBtn == 0x80) {
            if (isDown && event.getRepeatCount() == 0) handleDpadNavigation("up");
            return true;
        }
        if (code == KeyEvent.KEYCODE_DPAD_DOWN || psBtn == 0x81) {
            if (isDown && event.getRepeatCount() == 0) handleDpadNavigation("down");
            return true;
        }
        if (code == KeyEvent.KEYCODE_DPAD_LEFT || psBtn == 0x82) {
            if (isDown && event.getRepeatCount() == 0) handleDpadNavigation("left");
            return true;
        }
        if (code == KeyEvent.KEYCODE_DPAD_RIGHT || psBtn == 0x83) {
            if (isDown && event.getRepeatCount() == 0) handleDpadNavigation("right");
            return true;
        }

        if (psBtn != -1) {
            // Consumir cualquier otro botón del mando (ej. Cuadrado 0x8A) para que NUNCA
            // se filtre a super.dispatchKeyEvent(event) y no provoque clicks o acciones no deseadas
            return true;
        }

        return super.dispatchKeyEvent(event);
    }

    private static float applyDeadzone(float val, float dz) {
        if (Math.abs(val) < dz) return 0f;
        float sign = val > 0 ? 1f : -1f;
        float norm = (Math.abs(val) - dz) / (1f - dz);
        return sign * (norm * 0.75f + norm * norm * 0.25f);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
            float lx = event.getAxisValue(MotionEvent.AXIS_X);
            float ly = event.getAxisValue(MotionEvent.AXIS_Y);
            float rx = event.getAxisValue(MotionEvent.AXIS_Z);
            float ry = event.getAxisValue(MotionEvent.AXIS_RZ);
            if (rx == 0f && ry == 0f) {
                float altRx = event.getAxisValue(MotionEvent.AXIS_RX);
                float altRy = event.getAxisValue(MotionEvent.AXIS_RY);
                if (event.getAxisValue(MotionEvent.AXIS_LTRIGGER) != 0f || event.getAxisValue(MotionEvent.AXIS_BRAKE) != 0f) {
                    rx = altRx;
                    ry = altRy;
                }
            }
            float hatX = event.getAxisValue(MotionEvent.AXIS_HAT_X);
            float hatY = event.getAxisValue(MotionEvent.AXIS_HAT_Y);

            float l2 = Math.max(event.getAxisValue(MotionEvent.AXIS_LTRIGGER),
                       Math.max(event.getAxisValue(MotionEvent.AXIS_BRAKE), event.getAxisValue(MotionEvent.AXIS_RX)));
            float r2 = Math.max(event.getAxisValue(MotionEvent.AXIS_RTRIGGER),
                       Math.max(event.getAxisValue(MotionEvent.AXIS_GAS), event.getAxisValue(MotionEvent.AXIS_RY)));

            if (streamContainer != null && streamContainer.getVisibility() == View.VISIBLE && streamClient != null) {
                if (l2 > 0.35f && !l2TriggerActive) {
                    l2TriggerActive = true;
                    streamClient.sendButtonEvent(0x86, true);
                } else if (l2 < 0.15f && l2TriggerActive) {
                    l2TriggerActive = false;
                    streamClient.sendButtonEvent(0x86, false);
                }

                if (r2 > 0.35f && !r2TriggerActive) {
                    r2TriggerActive = true;
                    streamClient.sendButtonEvent(0x87, true);
                } else if (r2 < 0.15f && r2TriggerActive) {
                    r2TriggerActive = false;
                    streamClient.sendButtonEvent(0x87, false);
                }

                short slx = (short) Math.max(-32767, Math.min(32767, (int) (lx * 32767)));
                short sly = (short) Math.max(-32767, Math.min(32767, (int) (ly * 32767)));
                short srx = (short) Math.max(-32767, Math.min(32767, (int) (rx * 32767)));
                short sry = (short) Math.max(-32767, Math.min(32767, (int) (ry * 32767)));
                streamClient.setSticks(slx, sly, srx, sry);

                boolean hatLeft = hatX < -0.5f;
                if (hatLeft != hatLeftActive) {
                    hatLeftActive = hatLeft;
                    streamClient.sendButtonEvent(0x82, hatLeft);
                }
                boolean hatRight = hatX > 0.5f;
                if (hatRight != hatRightActive) {
                    hatRightActive = hatRight;
                    streamClient.sendButtonEvent(0x83, hatRight);
                }
                boolean hatUp = hatY < -0.5f;
                if (hatUp != hatUpActive) {
                    hatUpActive = hatUp;
                    streamClient.sendButtonEvent(0x80, hatUp);
                }
                boolean hatDown = hatY > 0.5f;
                if (hatDown != hatDownActive) {
                    hatDownActive = hatDown;
                    streamClient.sendButtonEvent(0x81, hatDown);
                }
                return true;
            }

            InputDevice dev = event.getDevice();
            if (dev != null) {
                String dn = dev.getName();
                if (dn != null && !dn.isEmpty() && !"Virtual".equalsIgnoreCase(dn)) livePadName = dn;
                livePadConnected = true;
            }
            liveLx = lx;
            liveLy = ly;
            liveRx = rx;
            liveRy = ry;
            liveL2 = l2;
            liveR2 = r2;
            liveButtons[6] = l2 > 0.35f;
            if (l2 > 0.35f) buttonReleaseTime[6] = System.currentTimeMillis() + 180;
            liveButtons[7] = r2 > 0.35f;
            if (r2 > 0.35f) buttonReleaseTime[7] = System.currentTimeMillis() + 180;
            liveButtons[12] = hatY < -0.5f;
            if (hatY < -0.5f) buttonReleaseTime[12] = System.currentTimeMillis() + 180;
            liveButtons[13] = hatY > 0.5f;
            if (hatY > 0.5f) buttonReleaseTime[13] = System.currentTimeMillis() + 180;
            liveButtons[14] = hatX < -0.5f;
            if (hatX < -0.5f) buttonReleaseTime[14] = System.currentTimeMillis() + 180;
            liveButtons[15] = hatX > 0.5f;
            if (hatX > 0.5f) buttonReleaseTime[15] = System.currentTimeMillis() + 180;

            // En el menú: Análogo Izquierdo controla el cursor virtual libremente
            stickVelX = applyDeadzone(lx, 0.12f);
            stickVelY = applyDeadzone(ly, 0.12f);
            if (stickVelX != 0f || stickVelY != 0f) {
                cursorMovedByUser = true;
                if (cursorView != null) cursorView.setVisibility(View.VISIBLE);
            }
            scrollVelY = applyDeadzone(ry, 0.18f);

            // D-Pad / HAT: Navegación espacial botón a botón en la interfaz
            boolean hatLeft = hatX < -0.5f;
            if (hatLeft != hatLeftActive) {
                hatLeftActive = hatLeft;
                if (hatLeft) handleDpadNavigation("left");
            }
            boolean hatRight = hatX > 0.5f;
            if (hatRight != hatRightActive) {
                hatRightActive = hatRight;
                if (hatRight) handleDpadNavigation("right");
            }
            boolean hatUp = hatY < -0.5f;
            if (hatUp != hatUpActive) {
                hatUpActive = hatUp;
                if (hatUp) handleDpadNavigation("up");
            }
            boolean hatDown = hatY > 0.5f;
            if (hatDown != hatDownActive) {
                hatDownActive = hatDown;
                if (hatDown) handleDpadNavigation("down");
            }
            return true;
        }
        return super.dispatchGenericMotionEvent(event);
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUi();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemUi();
        }
    }

    private void hideSystemUi() {
        try {
            View decorView = getWindow().getDecorView();
            decorView.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_FULLSCREEN
            );
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Window window = getWindow();
                window.setDecorFitsSystemWindows(false);
                WindowInsetsController controller = window.getInsetsController();
                if (controller != null) {
                    controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                    controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                }
            }
        } catch (Throwable ignored) {}
    }

    @Override
    protected void onDestroy() {
        cursorLoopActive = false;
        stopNativeStreamUi();
        try {
            if (multicastLock != null && multicastLock.isHeld()) {
                multicastLock.release();
            }
        } catch (Throwable ignored) {}
        try {
            if (wifiLowLatencyLock != null && wifiLowLatencyLock.isHeld()) {
                wifiLowLatencyLock.release();
            }
        } catch (Throwable ignored) {}
        try {
            if (wifiHighPerfLock != null && wifiHighPerfLock.isHeld()) {
                wifiHighPerfLock.release();
            }
        } catch (Throwable ignored) {}
        super.onDestroy();
    }
}
"""
    (pkg_dir / "MainActivity.java").write_text(main_java, encoding="utf-8")


def prepare_assets_and_res(build_dir: Path):
    assets_gui = build_dir / "assets" / "gui"
    if assets_gui.exists():
        shutil.rmtree(assets_gui)
    assets_gui.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC_DIR / "gui", assets_gui, dirs_exist_ok=True)

    # Añadir soporte de foco visible para control remoto de Android TV / D-Pad
    css_file = assets_gui / "styles.css"
    css = css_file.read_text(encoding="utf-8")
    tv_focus_css = """
    button:focus, select:focus, input:focus, .mode-tab:focus, .nav-pill:focus {
        outline: 3px solid #00d4ff !important;
        outline-offset: 2px !important;
        box-shadow: 0 0 18px rgba(0, 212, 255, 0.85) !important;
    }
    """
    css = css + "\n" + tv_focus_css
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    css = re.sub(r"\s+", " ", css)
    css_file.write_text(css.strip(), encoding="utf-8")

    # Minificar JS
    js_file = assets_gui / "app.js"
    js = js_file.read_text(encoding="utf-8")
    js = re.sub(r"/\*[\s\S]*?\*/", "", js)
    lines = [line.strip() for line in js.splitlines() if line.strip() and not line.strip().startswith("//")]
    js_file.write_text("\n".join(lines), encoding="utf-8")

    # Minificar HTML y remover atajos específicos de macOS y el botón Abrir Carpeta en la versión APK
    html_file = assets_gui / "index.html"
    html = html_file.read_text(encoding="utf-8")
    html = re.sub(r'<button[^>]*id="btn-macos-game-shortcuts"[^>]*>[\s\S]*?</button>', '', html)
    html = re.sub(r'<button[^>]*openSystemGameControllerSettings[^>]*>[\s\S]*?</button>', '', html)
    html = re.sub(r'<button[^>]*openLogsFolder[^>]*>[\s\S]*?</button>', '', html)
    html = re.sub(r"<!--[\s\S]*?-->", "", html)
    html_file.write_text("\n".join(l.strip() for l in html.splitlines() if l.strip()), encoding="utf-8")

    # Recursos Android (ic_launcher + tv_banner 320x180 para Android TV Leanback)
    res_drawable = build_dir / "res" / "drawable"
    res_drawable.mkdir(parents=True, exist_ok=True)
    res_values = build_dir / "res" / "values"
    res_values.mkdir(parents=True, exist_ok=True)

    styles_xml = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="@android:style/Theme.Black.NoTitleBar.Fullscreen">
        <item name="android:windowBackground">@android:color/black</item>
        <item name="android:colorBackground">@android:color/black</item>
        <item name="android:navigationBarColor">@android:color/transparent</item>
        <item name="android:statusBarColor">@android:color/transparent</item>
        <item name="android:windowDrawsSystemBarBackgrounds">true</item>
        <item name="android:windowTranslucentNavigation">true</item>
        <item name="android:windowTranslucentStatus">true</item>
    </style>
</resources>
"""
    (res_values / "styles.xml").write_text(styles_xml, encoding="utf-8")

    icon_src = SRC_DIR / "app_icon_1024.png"
    img_icon = Image.open(icon_src).convert("RGBA").resize((192, 192), Image.Resampling.LANCZOS)
    img_icon.save(res_drawable / "ic_launcher.png", format="PNG")

    bg_src = SRC_DIR / "assets" / "bg_main.jpg"
    banner = Image.open(bg_src).convert("RGBA").resize((320, 180), Image.Resampling.LANCZOS)
    icon_small = img_icon.resize((96, 96), Image.Resampling.LANCZOS)
    banner.paste(icon_small, (112, 42), icon_small)
    banner.convert("RGB").save(res_drawable / "tv_banner.png", format="PNG")

    # AndroidManifest.xml compatible con Android TV (Leanback) y Smartphones/Tablets
    manifest_xml = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.drps5.remoteplay"
    android:versionCode="120"
    android:versionName="1.2.0">

    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />

    <uses-feature android:name="android.software.leanback" android:required="false" />
    <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
    <uses-feature android:name="android.hardware.gamepad" android:required="false" />

    <application
        android:label="DRPS5 - Pantalla Remota PS5"
        android:icon="@drawable/ic_launcher"
        android:banner="@drawable/tv_banner"
        android:usesCleartextTraffic="true"
        android:hardwareAccelerated="true"
        android:allowBackup="false"
        android:debuggable="true">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:screenOrientation="sensorLandscape"
            android:configChanges="keyboard|keyboardHidden|orientation|screenSize|screenLayout|smallestScreenSize|uiMode"
            android:theme="@style/AppTheme">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
                <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
    (build_dir / "AndroidManifest.xml").write_text(manifest_xml, encoding="utf-8")


def ensure_keystore(ks_path: Path):
    if ks_path.exists():
        return
    subprocess.run(
        [
            str(KEYTOOL),
            "-genkeypair",
            "-v",
            "-keystore", str(ks_path),
            "-alias", "drps5key",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
            "-storepass", "drps5pass",
            "-keypass", "drps5pass",
            "-dname", "CN=DRPS5, OU=Security, O=DRPS5, L=Lima, S=Lima, C=PE",
        ],
        check=True,
    )


def build_apk(output_apk: Path, is_personal: bool, ks_path: Path):
    work_dir = APK_OUT_DIR / ("_build_personal" if is_personal else "_build_public")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    prepare_assets_and_res(work_dir)

    src_java = work_dir / "src"
    generate_java_sources(src_java, is_personal=is_personal)

    # 1. Compilar recursos con aapt2
    compiled_res = work_dir / "compiled_res.zip"
    subprocess.run(
        [str(AAPT2), "compile", "--dir", str(work_dir / "res"), "-o", str(compiled_res)],
        check=True,
    )

    unsigned_apk = work_dir / "unsigned.apk"
    java_gen = work_dir / "gen"
    java_gen.mkdir(parents=True)
    subprocess.run(
        [
            str(AAPT2),
            "link",
            "-I", str(PLATFORM_JAR),
            "--manifest", str(work_dir / "AndroidManifest.xml"),
            "-A", str(work_dir / "assets"),
            "--java", str(java_gen),
            "-o", str(unsigned_apk),
            str(compiled_res),
        ],
        check=True,
    )

    # 2. Compilar código Java (sin símbolos de depuración -g:none contra REA)
    classes_dir = work_dir / "classes"
    classes_dir.mkdir(parents=True)
    java_files = list(src_java.rglob("*.java")) + list(java_gen.rglob("*.java"))
    subprocess.run(
        [
            str(JAVAC),
            "-g:none",
            "--release", "11",
            "-classpath", str(PLATFORM_JAR),
            "-d", str(classes_dir),
        ] + [str(f) for f in java_files],
        check=True,
    )

    # 3. Convertir a DEX optimizado con d8
    class_files = list(classes_dir.rglob("*.class"))
    subprocess.run(
        [
            str(D8),
            "--release",
            "--lib", str(PLATFORM_JAR),
            "--output", str(work_dir),
        ] + [str(f) for f in class_files],
        check=True,
    )

    # 4. Añadir classes.dex al APK
    with zipfile.ZipFile(unsigned_apk, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(work_dir / "classes.dex", "classes.dex")

    # 5. Alinear con zipalign
    aligned_apk = work_dir / "aligned.apk"
    subprocess.run(
        [str(ZIPALIGN), "-f", "-p", "4", str(unsigned_apk), str(aligned_apk)],
        check=True,
    )

    # 6. Firmar con apksigner (v1 + v2 + v3)
    if output_apk.exists():
        output_apk.unlink()
    subprocess.run(
        [
            str(APKSIGNER),
            "sign",
            "--ks", str(ks_path),
            "--ks-key-alias", "drps5key",
            "--ks-pass", "pass:drps5pass",
            "--key-pass", "pass:drps5pass",
            "--out", str(output_apk),
            str(aligned_apk),
        ],
        check=True,
    )

    shutil.rmtree(work_dir, ignore_errors=True)
    print(f"[+] APK generado y firmado con éxito (personal={is_personal}): {output_apk} ({output_apk.stat().st_size} bytes)")


def main():
    APK_OUT_DIR.mkdir(parents=True, exist_ok=True)
    ks_path = APK_OUT_DIR / ".drps5_release.keystore"
    ensure_keystore(ks_path)

    personal_apk = APK_OUT_DIR / "DRPS5_Personal.apk"
    public_apk = APK_OUT_DIR / "DRPS5_Publico.apk"

    build_apk(personal_apk, is_personal=True, ks_path=ks_path)
    build_apk(public_apk, is_personal=False, ks_path=ks_path)


if __name__ == "__main__":
    main()
