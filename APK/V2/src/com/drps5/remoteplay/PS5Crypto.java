package com.drps5.remoteplay;

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
