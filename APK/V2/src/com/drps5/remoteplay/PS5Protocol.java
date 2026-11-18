package com.drps5.remoteplay;

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
