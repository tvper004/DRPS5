package com.drps5.remoteplay;

import android.content.Context;
import android.util.Log;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

public final class AppLogger {
    public interface Listener {
        void onLogAdded(String line);
    }

    private static final int MAX_LINES = 400;
    private static final List<String> LINES = new ArrayList<>();
    private static final SimpleDateFormat FMT = new SimpleDateFormat("HH:mm:ss.SSS", Locale.US);
    private static volatile Listener listener;
    private static volatile File logFile;
    private static volatile boolean fileEnabled = false;

    private AppLogger() {}

    public static void init(Context ctx, boolean enableFile) {
        fileEnabled = enableFile;
        if (ctx != null) {
            logFile = new File(ctx.getFilesDir(), "drps5_v2.log");
            if (enableFile && logFile.exists() && logFile.length() > 512 * 1024) {
                // Truncate oversized log on startup
                try (PrintWriter pw = new PrintWriter(new FileWriter(logFile, false))) {
                    pw.print("");
                } catch (Throwable ignored) {}
            }
        }
    }

    public static void setFileEnabled(boolean enabled) {
        fileEnabled = enabled;
    }

    public static void setListener(Listener l) {
        listener = l;
    }

    public static void i(String tag, String msg) {
        Log.i("DRPS5-" + tag, msg);
        append("I", tag, msg);
    }

    public static void w(String tag, String msg) {
        Log.w("DRPS5-" + tag, msg);
        append("W", tag, msg);
    }

    public static void e(String tag, String msg) {
        Log.e("DRPS5-" + tag, msg);
        append("E", tag, msg);
    }

    private static void append(String level, String tag, String msg) {
        String ts;
        synchronized (FMT) {
            ts = FMT.format(new Date());
        }
        String line = ts + " [" + level + "/" + tag + "] " + msg;
        synchronized (LINES) {
            if (LINES.size() >= MAX_LINES) {
                LINES.remove(0);
            }
            LINES.add(line);
        }
        if (fileEnabled && logFile != null) {
            try (PrintWriter pw = new PrintWriter(new FileWriter(logFile, true))) {
                pw.println(line);
            } catch (Throwable ignored) {}
        }
        Listener l = listener;
        if (l != null) {
            l.onLogAdded(line);
        }
    }

    public static String dumpText() {
        StringBuilder sb = new StringBuilder();
        synchronized (LINES) {
            for (String s : LINES) {
                sb.append(s).append('\n');
            }
        }
        return sb.toString();
    }

    public static void clear() {
        synchronized (LINES) {
            LINES.clear();
        }
    }
}
