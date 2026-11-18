package com.drps5.remoteplay;

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
    private int bitrateKbps = 0;

    public void setBitrateKbps(int kbps) {
        this.bitrateKbps = Math.max(0, kbps);
    }

    public void requestRecoveryIdr() {
        if (running.get()) {
            waitingForIdr = true;
            sendIdrRequest();
        }
    }

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
    private final Object codecLock = new Object();
    private volatile int consecutiveFeedTimeouts = 0;

    private PS5Crypto.SessionCipher sessionCipher;
    private byte[] sessionId;
    private PS5Crypto.StreamECDH ecdh;
    private volatile PS5Crypto.StreamCipher streamCipher;

    private int tagLocal = 1;
    private volatile int tagRemote = 0;
    private int tsn = 1;
    private volatile boolean cookieAcked = false;
    private byte[] videoHeader = new byte[0];
    private long remoteKeyPosHigh = 0L;
    private long lastRemoteKeyPosLow = -1L;

    private synchronized long resolveRemoteKeyPos(long keyPosLow) {
        if (lastRemoteKeyPosLow >= 0) {
            if (keyPosLow < 0x40000000L && lastRemoteKeyPosLow > 0xC0000000L) {
                remoteKeyPosHigh += 0x100000000L;
            } else if (keyPosLow > 0xC0000000L && lastRemoteKeyPosLow < 0x40000000L && remoteKeyPosHigh >= 0x100000000L) {
                return (remoteKeyPosHigh - 0x100000000L) | keyPosLow;
            }
        }
        if (keyPosLow > lastRemoteKeyPosLow || (lastRemoteKeyPosLow - keyPosLow) > 0x80000000L) {
            lastRemoteKeyPosLow = keyPosLow;
        }
        return remoteKeyPosHigh | keyPosLow;
    }

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
        boolean delivered = false;
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
            delivered = false;
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
    private final byte[] fbTouchPlain = new byte[5];
    private final byte[] fbTouchPktBuf = new byte[12 + 5];
    private final ByteBuffer fbTouchPktWrap = ByteBuffer.wrap(fbTouchPktBuf);
    private DatagramPacket fbEventDatagram;
    private DatagramPacket fbStateDatagram;
    private DatagramPacket fbTouchDatagram;

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
                reassemblySlots[i].delivered = false;
                reassemblySlots[i].unitsReceivedCount = 0;
                reassemblySlots[i].fecUnitsReceived = 0;
            }
        }
        audioWriteIdx = 0;
        audioReadIdx = 0;
        nextDeliveryFrame = -1;
        highestReceivedFrame = -1;
        waitingForIdr = true;
        remoteKeyPosHigh = 0L;
        lastRemoteKeyPosLow = -1L;

        initMediaCodec();
        initAudio();
        udpSocket = new DatagramSocket();
        udpSocket.setReceiveBufferSize(1024 * 1024);
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
        fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 2 * 1024 * 1024);
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
        try { fmt.setInteger("vendor.qti-ext-dec-low-latency.enable", 1); } catch (Throwable ignored) {}
        try { fmt.setInteger("vendor.rtc-ext-dec-low-latency.enable", 1); } catch (Throwable ignored) {}
        try { fmt.setInteger("vendor.hisi.low-latency", 1); } catch (Throwable ignored) {}
        AppLogger.i("CODEC", "MediaCodec init " + mime + " " + w + "x" + h + " hdr=" + hdr);

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
            basicFmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 2 * 1024 * 1024);
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
                try { Thread.sleep(25); } catch (InterruptedException ie) { break; }
            } catch (Exception e) {
                android.util.Log.w("DRPS5", "Excepción en bucle de drenaje de vídeo: " + e.getMessage());
            }
        }
    }

    private void recoverVideoDecoder(boolean hardReset) {
        synchronized (codecLock) {
            if (!running.get()) return;
            boolean needRecreate = hardReset || videoCodec == null;
            if (!needRecreate) {
                try {
                    videoCodec.flush();
                    android.util.Log.w("DRPS5", "🔄 MediaCodec flush de recuperación ejecutado");
                } catch (Throwable t) {
                    android.util.Log.w("DRPS5", "MediaCodec flush falló, recreando decodificador: " + t.getMessage());
                    needRecreate = true;
                }
            }
            if (needRecreate) {
                try {
                    if (videoCodec != null) {
                        try { videoCodec.stop(); } catch (Throwable ignored) {}
                        try { videoCodec.release(); } catch (Throwable ignored) {}
                        videoCodec = null;
                    }
                    initMediaCodec();
                    android.util.Log.w("DRPS5", "🔄 MediaCodec recreado tras bloqueo");
                } catch (Throwable t) {
                    android.util.Log.e("DRPS5", "Error recreando MediaCodec: " + t.getMessage());
                }
            }
            waitingForIdr = true;
            nextDeliveryFrame = -1;
            consecutiveFeedTimeouts = 0;
        }
        sendIdrRequest();
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
                        long keyPosLow = (((long) buf[14] & 0xFF) << 24) | (((long) buf[15] & 0xFF) << 16) | (((long) buf[16] & 0xFF) << 8) | ((long) buf[17] & 0xFF);
                        long keyPos = resolveRemoteKeyPos(keyPosLow);
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
        long keyPosLow = (((long) buf[14] & 0xFF) << 24) | (((long) buf[15] & 0xFF) << 16) | (((long) buf[16] & 0xFF) << 8) | ((long) buf[17] & 0xFF);
        long keyPos = resolveRemoteKeyPos(keyPosLow);

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
            if (slot.frameIndex == frameIndex && slot.delivered) {
                return;
            }
            if (slot.frameIndex != frameIndex) {
                if (slot.frameIndex >= 0 && !slot.completed && !slot.delivered) {
                    int lost = Math.max(0, slot.expectedSrcUnits - slot.unitsReceivedCount);
                    if (lost > 0) {
                        totalPacketsLost += lost;
                    }
                }
                slot.reset(frameIndex, srcUnits, fecUnits);
            }

            if (!slot.unitPresent[unitIndex]) {
                System.arraycopy(buf, offset, slot.unitBuffers[unitIndex], 0, encLen);
                slot.unitDecrypted[unitIndex] = false;
                slot.unitLengths[unitIndex] = encLen;
                slot.unitKeyPos[unitIndex] = keyPos;
                slot.unitPresent[unitIndex] = true;
                if (unitIndex < slot.expectedSrcUnits) {
                    slot.unitsReceivedCount++;
                } else {
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
            slot.delivered = true;
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
                    } else if (waitingForIdr) {
                        nextDeliveryFrame = targetFrame;
                        targetFrameWaitStartTime = System.currentTimeMillis();
                        continue;
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
                    } else if (targetSlot.frameIndex == targetFrame && !targetSlot.completed && !targetSlot.delivered) {
                        int lost = Math.max(0, targetSlot.expectedSrcUnits - targetSlot.unitsReceivedCount);
                        if (lost > 0) totalPacketsLost += lost;
                        targetSlot.completed = false;
                        targetSlot.delivered = true;
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
                consecutiveFeedTimeouts = 0;
                ByteBuffer inBuf = codec.getInputBuffer(inIdx);
                if (inBuf != null) {
                    inBuf.clear();
                    int hdrLen = (isIdr && videoHeader != null) ? videoHeader.length : 0;
                    int totalLen = hdrLen + rawLen;
                    if (totalLen > inBuf.remaining()) {
                        codec.queueInputBuffer(inIdx, 0, 0, 0, 0);
                        android.util.Log.w("DRPS5", "⚠️ Frame excede buffer MediaCodec (" + totalLen + " > " + inBuf.remaining() + "), solicitando IDR");
                        waitingForIdr = true;
                        sendIdrRequest();
                        return;
                    }
                    if (hdrLen > 0) {
                        inBuf.put(videoHeader, 0, hdrLen);
                    }
                    inBuf.put(data, 0, rawLen);
                    codec.queueInputBuffer(inIdx, 0, totalLen, System.nanoTime() / 1000, 0);
                }
            } else {
                consecutiveFeedTimeouts++;
                if (consecutiveFeedTimeouts >= 5) {
                    recoverVideoDecoder(true);
                } else {
                    notifyCorruptFrame(Math.max(0, nextDeliveryFrame), Math.max(0, highestReceivedFrame));
                    sendIdrRequest();
                }
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
                if (zeroFpsTicks >= 16 && frames > 0) {
                    lastIdrReqTime = now;
                    zeroFpsTicks = 0;
                    android.util.Log.w("DRPS5", "🚨 Stall crítico (4s sin frames): recreando decodificador MediaCodec...");
                    recoverVideoDecoder(true);
                } else if (zeroFpsTicks == 10 && frames > 0) {
                    lastIdrReqTime = now;
                    android.util.Log.w("DRPS5", "🔄 Stall persistente (2.5s sin frames): ejecutando flush de MediaCodec...");
                    recoverVideoDecoder(false);
                } else if (zeroFpsTicks >= 2 && now - lastIdrReqTime > 500) {
                    lastIdrReqTime = now;
                    if (zeroFpsTicks >= 7 && frames > 0) {
                        waitingForIdr = true;
                        nextDeliveryFrame = -1;
                        android.util.Log.w("DRPS5", "⚡ Stall Watchdog: 0 FPS (" + (zeroFpsTicks * 250) + "ms). Reiniciando reensamblado a espera de IDR...");
                    } else {
                        android.util.Log.w("DRPS5", "⚡ Fast Recovery: 0 FPS (" + (zeroFpsTicks * 250) + "ms). Solicitando IDR de recuperación...");
                    }
                    notifyCorruptFrame( Math.max(0, nextDeliveryFrame), Math.max(0, highestReceivedFrame) );
                    sendIdrRequest();
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
            if (bitrateKbps > 0) {
                bw = bitrateKbps;
            }
            // MTU 1200 en Tailscale / enlaces remotos para evitar fragmentación IP sobre túnel WireGuard (MTU 1280)
            int mtu = tailscaleMode ? 1200 : 1454;
            int rtt = tailscaleMode ? 10 : 1;
            String vc = codecName.startsWith("h264") ? "avc" : "hevc";
            String hsB64 = Base64.encodeToString(ecdh.handshakeKey, Base64.NO_WRAP);
            String drStr = (hdr && !codecName.startsWith("h264")) ? "HDR" : "SDR";
            AppLogger.i("STREAM", "BigPayload: res=" + resolution + " fps=" + fps + " bw=" + bw + "kbps mtu=" + mtu + " vc=" + vc + " dr=" + drStr + " remote=" + tailscaleMode);

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

    public void sendTouchpadEvent(boolean down, int pointerId, int x, int y) {
        if (streamCipher == null || udpSocket == null) return;
        int cx = Math.max(0, Math.min(1919, x));
        int cy = Math.max(0, Math.min(941, y));
        synchronized (sendLock) {
            try {
                if (fbTouchDatagram == null && hostAddress != null) {
                    fbTouchDatagram = new DatagramPacket(fbTouchPktBuf, fbTouchPktBuf.length, hostAddress, 9296);
                }
                fbTouchPlain[0] = (byte) (down ? 0xD0 : 0xC0);
                fbTouchPlain[1] = (byte) (pointerId & 0x7F);
                fbTouchPlain[2] = (byte) ((cx >> 4) & 0xFF);
                fbTouchPlain[3] = (byte) (((cx & 0x0F) << 4) | ((cy >> 8) & 0x0F));
                fbTouchPlain[4] = (byte) (cy & 0xFF);
                feedbackSeqEvent = (feedbackSeqEvent + 1) & 0xFFFF;
                sendFeedbackPacketZeroAllocLocked(0x01, feedbackSeqEvent, fbTouchPlain, fbTouchPktBuf, fbTouchPktWrap, fbTouchDatagram);
            } catch (Exception e) {
                android.util.Log.w("DRPS5", "Error enviando touchpad: " + e.getMessage());
            }
        }
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
