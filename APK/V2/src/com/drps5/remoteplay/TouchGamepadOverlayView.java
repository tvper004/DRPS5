package com.drps5.remoteplay;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.Handler;
import android.os.Looper;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import java.util.Arrays;

    public final class TouchGamepadOverlayView extends View {
    public interface InputTarget {
        void sendButtonEvent(int code, boolean pressed);
        void setSticks(short lx, short ly, short rx, short ry);
        void sendTouchpadEvent(boolean down, int pointerId, int x, int y);
        void onMenuRequested();
    }
    private InputTarget target;
    private boolean livePadConnected = false;
    private short touchLx = 0, touchLy = 0, touchRx = 0, touchRy = 0;
    public void setInputTarget(InputTarget t) { this.target = t; }
    public void setLivePadConnected(boolean connected) { this.livePadConnected = connected; }
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
        private int touchpadPointerId = -1;
        private float touchpadDownX = 0, touchpadDownY = 0;
        private float touchpadCurX = 0, touchpadCurY = 0;
        private float touchpadMaxDrag = 0;
        private final RectF touchpadRect = new RectF();

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
            if (lStickPointerId != -1 || rStickPointerId != -1 || touchpadPointerId != -1) return true;
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
            lStickCy = 0.80f * h;
            lStickBaseR = 52f * density;
            lStickThumbR = 22f * density;
            lStickCurX = lStickCx;
            lStickCurY = lStickCy;

            rStickCx = 0.87f * w;
            rStickCy = 0.80f * h;
            rStickBaseR = 52f * density;
            rStickThumbR = 22f * density;
            rStickCurX = rStickCx;
            rStickCurY = rStickCy;

            float topY = Math.max(20f * density, 0.052f * h);
            touchpadRect.set(
                0.365f * w,
                Math.max(6f * density, topY - 17f * density),
                0.635f * w,
                Math.max(topY + 40f * density, 0.34f * h)
            );
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (w <= 0 || h <= 0 || overlayAlpha <= 0.001f) return;

            int saveCount = canvas.saveLayerAlpha(0f, 0f, (float) w, (float) h, (int) (overlayAlpha * 255f));
            try {
                // Fila superior: Gatillos y Botones de Sistema en una franja limpia
                float topY = Math.max(20f * density, 0.052f * h);
                float shW = 32f * density;
                float shH = 18f * density;

                // 1. Shoulders: L1 y L2 horizontales a la izquierda
                drawCapsule(canvas, 0.08f * w, topY, shW, shH, "L1", 0x84);
                drawCapsule(canvas, 0.18f * w, topY, shW, shH, "L2", 0x86);

                // 2. Botones de Sistema: SHARE, TOUCHPAD (botón directo), OPTION
                drawCapsule(canvas, 0.30f * w, topY, 26f * density, 15f * density, "SHARE", 0x8D);
                boolean tpActive = (touchpadPointerId != -1) || touchBtnPressed[0x91];
                canvas.drawRoundRect(touchpadRect, 14f * density, 14f * density, tpActive ? pressedBgPaint : bgPaint);
                canvas.drawRoundRect(touchpadRect, 14f * density, 14f * density, borderPaint);
                canvas.drawText("TOUCHPAD", touchpadRect.centerX(), touchpadRect.centerY() + 5f * density, textPaint);
                drawCapsule(canvas, 0.70f * w, topY, 26f * density, 15f * density, "OPT", 0x8C);

                // 3. Shoulders: R2 y R1 horizontales a la derecha
                drawCapsule(canvas, 0.82f * w, topY, shW, shH, "R2", 0x87);
                drawCapsule(canvas, 0.92f * w, topY, shW, shH, "R1", 0x85);

                // 4. CRUCETA D-PAD (Centrada 50/50 entre L1/L2 y el análogo izquierdo)
                float dpadCx = 0.13f * w;
                float dpadCy = 0.38f * h;
                float dpadR = 23f * density;
                float dpadOffset = 38f * density;
                drawRoundButton(canvas, dpadCx, dpadCy - dpadOffset, dpadR, 0x80); // UP
                drawArrow(canvas, dpadCx, dpadCy - dpadOffset, dpadR * 0.45f, 0);
                drawRoundButton(canvas, dpadCx, dpadCy + dpadOffset, dpadR, 0x81); // DOWN
                drawArrow(canvas, dpadCx, dpadCy + dpadOffset, dpadR * 0.45f, 180);
                drawRoundButton(canvas, dpadCx - dpadOffset, dpadCy, dpadR, 0x82); // LEFT
                drawArrow(canvas, dpadCx - dpadOffset, dpadCy, dpadR * 0.45f, 270);
                drawRoundButton(canvas, dpadCx + dpadOffset, dpadCy, dpadR, 0x83); // RIGHT
                drawArrow(canvas, dpadCx + dpadOffset, dpadCy, dpadR * 0.45f, 90);

                // 5. BOTONES DE ACCIÓN PERSONALIZADOS (Centrados 50/50 entre R1/R2 y el análogo derecho)
                float actCx = 0.87f * w;
                float actCy = 0.38f * h;
                float actR = 23f * density;
                float actSpread = 40f * density;

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
                if (getContext() instanceof MainActivity) { /* fullscreen maintained by Activity */ }
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
                    if (target != null) {
                        target.setSticks((short) 0, (short) 0, (short) 0, (short) 0);
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

            if (touchpadRect.contains(x, y) && touchpadPointerId == -1) {
                touchpadPointerId = pId;
                pointerAction[actIdx] = 0x91;
                touchBtnPressed[0x91] = true;
                try { performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY); } catch (Throwable ignored) {}
                if (target != null) {
                    target.sendButtonEvent(0x91, true);
                }
                invalidate();
                return;
            }

            int hitBtn = hitTestButton(x, y);
            if (hitBtn != -1) {
                touchBtnPressed[hitBtn] = true;
                pointerAction[actIdx] = hitBtn;
                try { performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY); } catch (Throwable ignored) {}
                if (target != null) {
                    target.sendButtonEvent(hitBtn, true);
                }

                // Salida de pantalla remota con botones virtuales: SHARE + OPTION
                if (touchBtnPressed[0x8D] && touchBtnPressed[0x8C]) {
                    touchBtnPressed[0x8D] = false;
                    touchBtnPressed[0x8C] = false;
                    post(new Runnable() {
                        @Override
                        public void run() {
                            if (target != null) target.onMenuRequested();
                        }
                    });
                    return;
                }
            }
        }

        private int tpCoordX(float x) {
            float rw = Math.max(1f, touchpadRect.width());
            float norm = Math.max(0f, Math.min(1f, (x - touchpadRect.left) / rw));
            return Math.round(norm * 1919f);
        }

        private int tpCoordY(float y) {
            float rh = Math.max(1f, touchpadRect.height());
            float norm = Math.max(0f, Math.min(1f, (y - touchpadRect.top) / rh));
            return Math.round(norm * 941f);
        }

        private void handlePointerMove(int pId, float x, float y) {
            if (pId == lStickPointerId) {
                updateLeftStick(x, y);
            } else if (pId == rStickPointerId) {
                updateRightStick(x, y);
            } else if (pId == touchpadPointerId) {
                // El botón táctil se mantiene activo sin desplazar puntero
            }
        }

        private void handlePointerUp(int pId) {
            int actIdx = pId % pointerAction.length;
            if (pId == lStickPointerId) {
                lStickPointerId = -1;
                lStickCurX = lStickCx;
                lStickCurY = lStickCy;
                touchLx = 0; touchLy = 0;
                if (target != null) {
                    target.setSticks(touchLx, touchLy, touchRx, touchRy);
                }
            } else if (pId == rStickPointerId) {
                rStickPointerId = -1;
                rStickCurX = rStickCx;
                rStickCurY = rStickCy;
                touchRx = 0; touchRy = 0;
                if (target != null) {
                    target.setSticks(touchLx, touchLy, touchRx, touchRy);
                }
            } else if (pId == touchpadPointerId) {
                touchpadPointerId = -1;
                touchBtnPressed[0x91] = false;
                if (target != null) {
                    target.sendButtonEvent(0x91, false);
                }
                invalidate();
            } else {
                int code = pointerAction[actIdx];
                if (code >= 0 && code < 256) {
                    touchBtnPressed[code] = false;
                    if (target != null) {
                        target.sendButtonEvent(code, false);
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
            if (target != null) {
                target.setSticks(touchLx, touchLy, touchRx, touchRy);
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
            if (target != null) {
                target.setSticks(touchLx, touchLy, touchRx, touchRy);
            }
        }

        private int hitTestButton(float x, float y) {
            float dpadCx = 0.13f * w;
            float dpadCy = 0.38f * h;
            float dpadR = 28f * density;
            float dpadOffset = 38f * density;
            if (Math.hypot(x - dpadCx, y - (dpadCy - dpadOffset)) <= dpadR) return 0x80; // UP
            if (Math.hypot(x - dpadCx, y - (dpadCy + dpadOffset)) <= dpadR) return 0x81; // DOWN
            if (Math.hypot(x - (dpadCx - dpadOffset), y - dpadCy) <= dpadR) return 0x82; // LEFT
            if (Math.hypot(x - (dpadCx + dpadOffset), y - dpadCy) <= dpadR) return 0x83; // RIGHT

            float actCx = 0.87f * w;
            float actCy = 0.38f * h;
            float actR = 28f * density;
            float actSpread = 40f * density;
            if (Math.hypot(x - actCx, y - (actCy + actSpread)) <= actR) return 0x88; // Cruz (+)
            if (Math.hypot(x - (actCx - actSpread), y - actCy) <= actR) return 0x8A; // L invertida
            if (Math.hypot(x - (actCx + actSpread), y - actCy) <= actR) return 0x89; // Medialuna
            if (Math.hypot(x - actCx, y - (actCy - actSpread)) <= actR) return 0x8B; // Angulo 45

            float topY = Math.max(20f * density, 0.052f * h);
            float shW = 34f * density, shH = 22f * density;
            if (Math.abs(x - 0.08f * w) <= shW && Math.abs(y - topY) <= shH) return 0x84; // L1
            if (Math.abs(x - 0.18f * w) <= shW && Math.abs(y - topY) <= shH) return 0x86; // L2
            if (Math.abs(x - 0.82f * w) <= shW && Math.abs(y - topY) <= shH) return 0x87; // R2
            if (Math.abs(x - 0.92f * w) <= shW && Math.abs(y - topY) <= shH) return 0x85; // R1

            if (Math.abs(x - 0.30f * w) <= 30f * density && Math.abs(y - topY) <= 18f * density) return 0x8D; // SHARE
            if (Math.abs(x - 0.70f * w) <= 30f * density && Math.abs(y - topY) <= 18f * density) return 0x8C; // OPTIONS

            if (Math.hypot(x - (lStickCx + lStickBaseR + 24f * density), y - lStickCy) <= 22f * density) return 0x8F; // L3
            if (Math.hypot(x - (rStickCx - rStickBaseR - 24f * density), y - rStickCy) <= 22f * density) return 0x90; // R3

            if (Math.hypot(x - 0.50f * w, y - 0.90f * h) <= 26f * density) return 0x8E; // PS

            return -1;
        }
    }
