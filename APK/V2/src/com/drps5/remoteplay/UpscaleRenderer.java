package com.drps5.remoteplay;

import android.content.Context;
import android.graphics.SurfaceTexture;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.opengl.Matrix;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * Hardware-accelerated OpenGL ES 2.0 video upscaler for 2K (1440p) and 4K (2160p) @ 60FPS.
 * Uses a single-pass 5-tap Contrast Adaptive Sharpening (CAS) fragment shader on top of
 * hardware bilinear filtering, driven strictly on-demand via SurfaceTexture.OnFrameAvailableListener.
 */
public final class UpscaleRenderer extends GLSurfaceView
        implements GLSurfaceView.Renderer, SurfaceTexture.OnFrameAvailableListener {

    public interface SurfaceReadyListener {
        void onDecoderSurfaceReady(Surface surface);
    }

    private static final String VERT_SHADER =
        "attribute vec4 aPos;\n" +
        "attribute vec2 aTexCoord;\n" +
        "uniform mat4 uTexMatrix;\n" +
        "varying vec2 vTexCoord;\n" +
        "void main() {\n" +
        "    gl_Position = aPos;\n" +
        "    vTexCoord = (uTexMatrix * vec4(aTexCoord, 0.0, 1.0)).xy;\n" +
        "}\n";

    // Single-pass 5-tap CAS shader: crisp 2K/4K edges with minimal fragment cost for TV Sticks & Phones
    private static final String FRAG_SHADER =
        "#extension GL_OES_EGL_image_external : require\n" +
        "precision mediump float;\n" +
        "uniform samplerExternalOES uTex;\n" +
        "uniform vec2 uTexelSize;\n" +
        "uniform float uSharpness;\n" +
        "varying vec2 vTexCoord;\n" +
        "void main() {\n" +
        "    vec3 c = texture2D(uTex, vTexCoord).rgb;\n" +
        "    if (uSharpness <= 0.01) {\n" +
        "        gl_FragColor = vec4(c, 1.0);\n" +
        "        return;\n" +
        "    }\n" +
        "    vec3 n = texture2D(uTex, vTexCoord + vec2(0.0, -uTexelSize.y)).rgb;\n" +
        "    vec3 s = texture2D(uTex, vTexCoord + vec2(0.0,  uTexelSize.y)).rgb;\n" +
        "    vec3 w = texture2D(uTex, vTexCoord + vec2(-uTexelSize.x, 0.0)).rgb;\n" +
        "    vec3 e = texture2D(uTex, vTexCoord + vec2( uTexelSize.x, 0.0)).rgb;\n" +
        "    vec3 minRGB = min(c, min(min(n, s), min(w, e)));\n" +
        "    vec3 maxRGB = max(c, max(max(n, s), max(w, e)));\n" +
        "    vec3 amp = clamp(min(minRGB, 1.0 - maxRGB) / max(maxRGB, vec3(0.001)), 0.0, 1.0);\n" +
        "    float wPeak = -1.0 / mix(8.0, 5.0, uSharpness);\n" +
        "    vec3 weight = sqrt(amp) * wPeak;\n" +
        "    vec3 outColor = (c + (n + s + w + e) * weight) / (1.0 + 4.0 * weight);\n" +
        "    gl_FragColor = vec4(clamp(outColor, 0.0, 1.0), 1.0);\n" +
        "}\n";

    private static final float[] QUAD_COORDS = {
        -1f, -1f, 0f, 0f,
         1f, -1f, 1f, 0f,
        -1f,  1f, 0f, 1f,
         1f,  1f, 1f, 1f
    };

    private final FloatBuffer quadBuf;
    private final float[] stMatrix = new float[16];
    private final SurfaceReadyListener surfaceListener;

    private int program = 0;
    private int oesTexId = 0;
    private int aPosLoc = -1;
    private int aTexCoordLoc = -1;
    private int uTexMatrixLoc = -1;
    private int uTexelSizeLoc = -1;
    private int uSharpnessLoc = -1;

    private SurfaceTexture surfaceTexture;
    private Surface decoderSurface;
    private volatile boolean frameAvailable = false;

    private int srcWidth = 1920;
    private int srcHeight = 1080;
    private int targetOutWidth = 1920;
    private int targetOutHeight = 1080;
    private int surfaceViewWidth = 1920;
    private int surfaceViewHeight = 1080;

    private volatile String upscaleMode = "auto";
    private volatile float configuredSharpness = 0.65f;
    private volatile float activeSharpness = 0.65f;
    private volatile float avgGpuMs = 0f;
    private int slowFrameStreak = 0;
    private int maxViewportW = 3840;
    private int maxViewportH = 2160;

    public UpscaleRenderer(Context context, SurfaceReadyListener listener) {
        super(context);
        this.surfaceListener = listener;
        Matrix.setIdentityM(stMatrix, 0);

        quadBuf = ByteBuffer.allocateDirect(QUAD_COORDS.length * 4)
            .order(ByteOrder.nativeOrder())
            .asFloatBuffer();
        quadBuf.put(QUAD_COORDS);
        quadBuf.position(0);

        setEGLContextClientVersion(2);
        setEGLConfigChooser(8, 8, 8, 8, 0, 0);
        setRenderer(this);
        setRenderMode(RENDERMODE_WHEN_DIRTY);
    }

    public void configure(String resolution, String mode) {
        this.upscaleMode = mode != null ? mode : "auto";
        if ("2160p".equalsIgnoreCase(resolution) || "4k".equalsIgnoreCase(resolution)) {
            targetOutWidth = 3840;
            targetOutHeight = 2160;
        } else if ("1440p".equalsIgnoreCase(resolution) || "2k".equalsIgnoreCase(resolution)) {
            targetOutWidth = 2560;
            targetOutHeight = 1440;
        } else if ("720p".equalsIgnoreCase(resolution)) {
            targetOutWidth = 1280;
            targetOutHeight = 720;
            srcWidth = 1280;
            srcHeight = 720;
        } else {
            targetOutWidth = 1920;
            targetOutHeight = 1080;
            srcWidth = 1920;
            srcHeight = 1080;
        }

        if ("cas_high".equals(this.upscaleMode)) {
            configuredSharpness = 0.85f;
        } else if ("cas_med".equals(this.upscaleMode)) {
            configuredSharpness = 0.50f;
        } else if ("direct".equals(this.upscaleMode)) {
            configuredSharpness = 0.0f;
        } else {
            // Auto: strong sharpness for 2K/4K upscaling, moderate for 1080p
            configuredSharpness = targetOutHeight >= 1440 ? 0.72f : 0.45f;
        }
        activeSharpness = configuredSharpness;
        slowFrameStreak = 0;

        post(() -> {
            int applyW = Math.min(targetOutWidth, maxViewportW);
            int applyH = Math.min(targetOutHeight, maxViewportH);
            if (applyW >= 1280 && applyH >= 720) {
                getHolder().setFixedSize(applyW, applyH);
                AppLogger.i("GPU", "UpscaleRenderer fixedSize=" + applyW + "x" + applyH + " mode=" + this.upscaleMode + " sharp=" + configuredSharpness);
            }
        });
    }

    public void setSourceDimensions(int w, int h) {
        if (w > 0 && h > 0) {
            this.srcWidth = w;
            this.srcHeight = h;
        }
    }

    public float getAvgGpuMs() {
        return avgGpuMs;
    }

    public int getOutputWidth() {
        return surfaceViewWidth;
    }

    public int getOutputHeight() {
        return surfaceViewHeight;
    }

    public float getActiveSharpness() {
        return activeSharpness;
    }

    @Override
    public void onSurfaceCreated(GL10 gl, EGLConfig config) {
        int[] dims = new int[2];
        GLES20.glGetIntegerv(GLES20.GL_MAX_VIEWPORT_DIMS, dims, 0);
        if (dims[0] > 0 && dims[1] > 0) {
            maxViewportW = dims[0];
            maxViewportH = dims[1];
        }
        AppLogger.i("GPU", "GL Renderer: " + GLES20.glGetString(GLES20.GL_RENDERER) + " maxViewport=" + maxViewportW + "x" + maxViewportH);

        int vs = compileShader(GLES20.GL_VERTEX_SHADER, VERT_SHADER);
        int fs = compileShader(GLES20.GL_FRAGMENT_SHADER, FRAG_SHADER);
        program = GLES20.glCreateProgram();
        GLES20.glAttachShader(program, vs);
        GLES20.glAttachShader(program, fs);
        GLES20.glLinkProgram(program);
        GLES20.glDeleteShader(vs);
        GLES20.glDeleteShader(fs);

        aPosLoc = GLES20.glGetAttribLocation(program, "aPos");
        aTexCoordLoc = GLES20.glGetAttribLocation(program, "aTexCoord");
        uTexMatrixLoc = GLES20.glGetUniformLocation(program, "uTexMatrix");
        uTexelSizeLoc = GLES20.glGetUniformLocation(program, "uTexelSize");
        uSharpnessLoc = GLES20.glGetUniformLocation(program, "uSharpness");

        int[] tex = new int[1];
        GLES20.glGenTextures(1, tex, 0);
        oesTexId = tex[0];
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, oesTexId);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);

        if (decoderSurface != null) {
            decoderSurface.release();
        }
        if (surfaceTexture != null) {
            surfaceTexture.release();
        }
        surfaceTexture = new SurfaceTexture(oesTexId);
        surfaceTexture.setOnFrameAvailableListener(this);
        decoderSurface = new Surface(surfaceTexture);

        if (surfaceListener != null) {
            post(() -> surfaceListener.onDecoderSurfaceReady(decoderSurface));
        }
    }

    @Override
    public void onSurfaceChanged(GL10 gl, int width, int height) {
        surfaceViewWidth = width;
        surfaceViewHeight = height;
        GLES20.glViewport(0, 0, width, height);
    }

    @Override
    public void onFrameAvailable(SurfaceTexture st) {
        frameAvailable = true;
        requestRender();
    }

    @Override
    public void onDrawFrame(GL10 gl) {
        long t0 = System.nanoTime();
        if (frameAvailable && surfaceTexture != null) {
            surfaceTexture.updateTexImage();
            surfaceTexture.getTransformMatrix(stMatrix);
            frameAvailable = false;
        }

        GLES20.glClearColor(0f, 0f, 0f, 1f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);

        if (program == 0) return;
        GLES20.glUseProgram(program);

        GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, oesTexId);

        GLES20.glUniformMatrix4fv(uTexMatrixLoc, 1, false, stMatrix, 0);
        GLES20.glUniform2f(uTexelSizeLoc, 1.0f / Math.max(1, srcWidth), 1.0f / Math.max(1, srcHeight));
        GLES20.glUniform1f(uSharpnessLoc, activeSharpness);

        quadBuf.position(0);
        GLES20.glEnableVertexAttribArray(aPosLoc);
        GLES20.glVertexAttribPointer(aPosLoc, 2, GLES20.GL_FLOAT, false, 16, quadBuf);

        quadBuf.position(2);
        GLES20.glEnableVertexAttribArray(aTexCoordLoc);
        GLES20.glVertexAttribPointer(aTexCoordLoc, 2, GLES20.GL_FLOAT, false, 16, quadBuf);

        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        GLES20.glDisableVertexAttribArray(aPosLoc);
        GLES20.glDisableVertexAttribArray(aTexCoordLoc);

        float drawMs = (System.nanoTime() - t0) / 1_000_000.0f;
        avgGpuMs = (avgGpuMs == 0f) ? drawMs : (avgGpuMs * 0.9f + drawMs * 0.1f);

        // Adaptive 60FPS protection on low-end TV Sticks
        if ("auto".equals(upscaleMode) && activeSharpness > 0.0f) {
            if (drawMs > 13.5f) {
                slowFrameStreak++;
                if (slowFrameStreak >= 12) {
                    activeSharpness = 0.0f;
                    AppLogger.w("GPU", "Modo Auto: GPU lenta (" + String.format("%.1f", avgGpuMs) + " ms), cambiando a filtro bilineal rapido para mantener 60FPS");
                }
            } else {
                slowFrameStreak = 0;
            }
        }
    }

    public void releaseSurface() {
        queueEvent(() -> {
            if (decoderSurface != null) {
                decoderSurface.release();
                decoderSurface = null;
            }
            if (surfaceTexture != null) {
                surfaceTexture.release();
                surfaceTexture = null;
            }
            if (oesTexId != 0) {
                GLES20.glDeleteTextures(1, new int[]{ oesTexId }, 0);
                oesTexId = 0;
            }
        });
    }

    private static int compileShader(int type, String src) {
        int shader = GLES20.glCreateShader(type);
        GLES20.glShaderSource(shader, src);
        GLES20.glCompileShader(shader);
        return shader;
    }
}
