#!/usr/bin/env python3
"""
DRPS5 - Motor de Streaming de Pantalla Remota de PS5
Renderizado en tiempo real a 60 FPS con aceleración por hardware (Pygame + PyAV + Sounddevice).
Soporte completo de mandos DualSense/Xbox y teclado, sin inicio de sesión en PSN ni comprobaciones de licencia.
"""

import os
import sys

# Identidad estricta de proceso macOS
if sys.platform == "darwin":
    try:
        import Foundation
        Foundation.NSProcessInfo.processInfo().setProcessName_("DRPS5")
    except Exception:
        pass

import time
import math
import ctypes
import threading
import queue
import logging
import asyncio
from typing import Optional

# Carga opcional del acelerador nativo Universal C/SIMD Contrast Adaptive Sharpening (CAS)
_CAS_LIB = None
for _cas_cand in (
    os.path.join(os.environ.get("DRPS5_RESOURCES_DIR", ""), "libdrps5_cas.dylib"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "libdrps5_cas.dylib"),
    "/Applications/DRPS5.app/Contents/Resources/libdrps5_cas.dylib",
):
    if _cas_cand and os.path.exists(_cas_cand):
        try:
            _CAS_LIB = ctypes.CDLL(_cas_cand)
            _CAS_LIB.drps5_cas_rgb24.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
            ]
            _CAS_LIB.drps5_cas_rgb24.restype = None
            break
        except Exception:
            _CAS_LIB = None

# Configuración de base de datos de mandos SDL2 (Universal GameControllerDB)
base_dir = os.path.dirname(os.path.abspath(__file__))
gcdb_candidates = [
    os.path.join(base_dir, "gamecontrollerdb.txt"),
    os.path.join(base_dir, "Resources", "gamecontrollerdb.txt"),
    os.path.join(os.path.dirname(base_dir), "Resources", "gamecontrollerdb.txt"),
    "/Applications/DRPS5.app/Contents/Resources/gamecontrollerdb.txt",
    "/Users/rleon/Documents/PXPLAY/DRPS5/gamecontrollerdb.txt"
]
for gcdb in gcdb_candidates:
    if os.path.exists(gcdb):
        os.environ["SDL_GAMECONTROLLERCONFIG_FILE"] = gcdb
        break

os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
os.environ["SDL_HINT_JOYSTICK_MFI"] = "1"
os.environ["SDL_HINT_JOYSTICK_IOKIT"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI"] = "1"
os.environ["SDL_JOYSTICK_HIDAPI_PS5"] = "1"
os.environ["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"

# Suprimir captura global del botón PS/Home/Backbone por macOS (Launchpad / Games app)
if sys.platform == "darwin":
    try:
        import subprocess
        subprocess.run(["defaults", "write", "com.apple.GameController", "HomeButtonAction", "-integer", "0"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["defaults", "write", "com.apple.GameController", "bluetoothPrefsMenuLongPressAction", "-integer", "0"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["defaults", "write", "com.apple.GameController", "bluetoothPrefsShareLongPressSystemGestureMode", "-integer", "-1"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["defaults", "write", "com.apple.GameController", "systemGesturesEnabled", "-bool", "false"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

import pygame
import pygame._sdl2.controller as sdl2_controller
import av
import sounddevice as sd

from pyremoteplay.receiver import AVReceiver
from pyremoteplay.session import Session
from pyremoteplay.controller import Controller
from pyremoteplay.const import Resolution, FPS, TYPE_PS5, TYPE_PS4
from pyremoteplay.profile import UserProfile
from pyremoteplay.stream_packets import FeedbackEvent

logger = logging.getLogger("DRPS5.Stream")

# Asegurar persistencia de logs en ~/.drps5/stream.log en cualquier ejecución (GUI o CLI)
try:
    from pathlib import Path
    _stream_log_dir = Path.home() / ".drps5"
    _stream_log_dir.mkdir(parents=True, exist_ok=True)
    _stream_log_file = _stream_log_dir / "stream.log"
    _has_sh = any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith('stream.log') for h in logging.getLogger().handlers)
    if not _has_sh:
        _sh = logging.FileHandler(_stream_log_file, encoding="utf-8")
        _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(_sh)
        logging.getLogger().setLevel(logging.INFO)
except Exception as _log_init_err:
    pass

def clean_ip_target(ip_str: str) -> str:
    """Limpia cadenas de IP que incluyan comas, IPv6 secundarias o espacios (ej. Tailscale GUI)."""
    if not ip_str:
        return ""
    part = str(ip_str).split(",")[0].strip()
    part = part.split()[0].strip()
    return part

# Mapeo universal SDL2 GameController (Backbone One, DualSense, Xbox, Switch, MFi, etc.)
SDL_CONTROLLER_MAP = {
    pygame.CONTROLLER_BUTTON_A: "CROSS",
    pygame.CONTROLLER_BUTTON_B: "CIRCLE",
    pygame.CONTROLLER_BUTTON_X: "SQUARE",
    pygame.CONTROLLER_BUTTON_Y: "TRIANGLE",
    pygame.CONTROLLER_BUTTON_BACK: "SHARE",
    pygame.CONTROLLER_BUTTON_GUIDE: "PS",       # Botón PS en DualSense / Botón Backbone en Backbone One
    pygame.CONTROLLER_BUTTON_START: "OPTIONS",
    pygame.CONTROLLER_BUTTON_LEFTSTICK: "L3",
    pygame.CONTROLLER_BUTTON_RIGHTSTICK: "R3",
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "L1",
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "R1",
    pygame.CONTROLLER_BUTTON_DPAD_UP: "UP",
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: "DOWN",
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: "LEFT",
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "RIGHT",
    15: "TOUCHPAD",                             # Touchpad / Mute
    16: "TOUCHPAD",                             # Botón de Captura (Backbone One) -> Touchpad PS
    17: "PS",                                   # Botón Backbone (Guía Mac alternativa) -> PS
    18: "TOUCHPAD",                             # Touchpad extra
    20: "TOUCHPAD",                             # Touchpad clic estándar SDL2 (DualSense / PS4 / PS5)
}
if hasattr(pygame, "CONTROLLER_BUTTON_TOUCHPAD"):
    SDL_CONTROLLER_MAP[pygame.CONTROLLER_BUTTON_TOUCHPAD] = "TOUCHPAD"

# Fallback para joysticks sin mapear en macOS (incluyendo Backbone por MFi/IOKit)
RAW_JOYSTICK_BUTTON_MAP = {
    0: "CROSS",       # Cross / A
    1: "CIRCLE",      # Circle / B
    2: "SQUARE",      # Square / X
    3: "TRIANGLE",    # Triangle / Y
    4: "SHARE",       # Share / Create
    5: "PS",          # PS Guide / Backbone Button -> PS
    6: "OPTIONS",     # Options / Start
    7: "L3",          # L3
    8: "R3",          # R3
    9: "L1",          # L1
    10: "R1",         # R1
    11: "UP",         # Dpad Up
    12: "PS",         # Backbone Guide (Mac MFi) -> PS
    13: "LEFT",       # Dpad Left
    14: "RIGHT",      # Dpad Right
    15: "TOUCHPAD",   # Touchpad / Mute
    16: "TOUCHPAD",   # Botón de Captura (Backbone One) -> Touchpad
    17: "PS",         # Botón Backbone (b17 en GCDB) -> PS
    18: "TOUCHPAD",   # Touchpad extra
    20: "TOUCHPAD",   # Touchpad clic DualSense
}

# Mapeo de teclado extendido
KEYBOARD_MAP = {
    pygame.K_SPACE: "CROSS",
    pygame.K_RETURN: "CROSS",
    pygame.K_BACKSPACE: "CIRCLE",
    pygame.K_ESCAPE: "OPTIONS",
    pygame.K_q: "SQUARE",
    pygame.K_e: "TRIANGLE",
    pygame.K_TAB: "PS",
    pygame.K_p: "PS",
    pygame.K_h: "SHARE",
    pygame.K_t: "TOUCHPAD",
    pygame.K_1: "L1",
    pygame.K_2: "R1",
    pygame.K_3: "L2",
    pygame.K_4: "R2",
    pygame.K_UP: "UP",
    pygame.K_DOWN: "DOWN",
    pygame.K_LEFT: "LEFT",
    pygame.K_RIGHT: "RIGHT"
}

def get_macos_default_audio_output_device():
    """Consulta el AudioDeviceID y nombre del dispositivo de salida de audio predeterminado."""
    if sys.platform != "darwin":
        try:
            default_dev = sd.query_devices(kind='output')
            return None, default_dev.get('name', 'Predeterminado')
        except Exception:
            return None, "Predeterminado"
    try:
        import ctypes
        from ctypes import c_uint32, byref, Structure, create_string_buffer

        coreaudio = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')

        class AudioObjectPropertyAddress(Structure):
            _fields_ = [
                ('mSelector', c_uint32),
                ('mScope', c_uint32),
                ('mElement', c_uint32)
            ]

        # kAudioHardwarePropertyDefaultOutputDevice = 'dOut' (0x644f7574)
        prop_addr = AudioObjectPropertyAddress(0x644f7574, 0x676c6f62, 0)
        dev_id = c_uint32()
        size = c_uint32(ctypes.sizeof(dev_id))

        status = coreaudio.AudioObjectGetPropertyData(1, byref(prop_addr), 0, None, byref(size), byref(dev_id))
        if status != 0:
            return None, "Predeterminado"

        # kAudioDevicePropertyDeviceName = 'name' (0x6e616d65)
        name_prop = AudioObjectPropertyAddress(0x6e616d65, 0x676c6f62, 0)
        name_buf = create_string_buffer(256)
        name_size = c_uint32(256)
        name_status = coreaudio.AudioObjectGetPropertyData(dev_id.value, byref(name_prop), 0, None, byref(name_size), name_buf)
        dev_name = name_buf.value.decode('utf-8', errors='replace') if name_status == 0 else f"Dispositivo {dev_id.value}"

        return dev_id.value, dev_name
    except Exception as e:
        logger.debug(f"Error consultando CoreAudio: {e}")
        return None, "Predeterminado"


class DRPS5Receiver(AVReceiver):
    """Receptor AV de ultra-baja latencia para la pantalla remota de la PS5 con cambio dinámico de audio y CAS SIMD."""

    def __init__(self, audio_enabled: bool = True, cas_strength: int = 0):
        super().__init__()
        self.audio_enabled = audio_enabled
        self.cas_strength = max(0, min(255, int(cas_strength or 0)))
        self._cas_buf: Optional[bytearray] = None
        self._cas_c_dst = None
        self.frame_queue = queue.Queue(maxsize=2)
        self.audio_queue = queue.Queue(maxsize=150)
        self.audio_stream: Optional[sd.RawOutputStream] = None
        self.latest_frame_surface: Optional[pygame.Surface] = None
        self.frame_width = 1280
        self.frame_height = 720
        self.fps_counter = 0
        self.fps_displayed = 0
        self.last_fps_time = time.time()
        self._audio_initialized = False
        self._audio_prefill_done = False
        self._audio_buffer = bytearray()
        self._audio_lock = threading.Lock()
        self._audio_restart_lock = threading.Lock()
        self._current_audio_device_id = None
        self._current_audio_device_name = "Predeterminado"
        self._audio_device_changed = False
        self._audio_listener_proc = None

        if self.audio_enabled:
            self._setup_coreaudio_listener()

    def _setup_coreaudio_listener(self):
        """Registra un listener nativo de CoreAudio para detectar cambios inmediatos en auriculares/altavoces."""
        if sys.platform != "darwin":
            return
        try:
            import ctypes
            from ctypes import c_uint32, c_void_p, byref, Structure, CFUNCTYPE

            coreaudio = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')

            class AudioObjectPropertyAddress(Structure):
                _fields_ = [
                    ('mSelector', c_uint32),
                    ('mScope', c_uint32),
                    ('mElement', c_uint32)
                ]

            AudioObjectPropertyListenerProc = CFUNCTYPE(
                ctypes.c_int32,
                c_uint32,
                c_uint32,
                ctypes.POINTER(AudioObjectPropertyAddress),
                c_void_p
            )

            def _listener_cb(obj_id, num_addr, addr_ptr, client_data):
                logger.info("🎧 Evento CoreAudio: Cambio de dispositivo de audio del sistema detectado.")
                self._audio_device_changed = True
                return 0

            self._audio_listener_proc = AudioObjectPropertyListenerProc(_listener_cb)
            prop_addr = AudioObjectPropertyAddress(0x644f7574, 0x676c6f62, 0)
            status = coreaudio.AudioObjectAddPropertyListener(1, byref(prop_addr), self._audio_listener_proc, None)
            if status == 0:
                logger.info("🎧 Listener de CoreAudio activo para migración automática de auriculares/altavoces.")
        except Exception as e:
            logger.debug(f"No se pudo registrar listener de CoreAudio: {e}")

    def _remove_coreaudio_listener(self):
        """Elimina el listener nativo de CoreAudio al cerrar la sesión."""
        if sys.platform != "darwin":
            return
        if self._audio_listener_proc:
            try:
                import ctypes
                from ctypes import c_uint32, byref, Structure
                coreaudio = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
                class AudioObjectPropertyAddress(Structure):
                    _fields_ = [
                        ('mSelector', c_uint32),
                        ('mScope', c_uint32),
                        ('mElement', c_uint32)
                    ]
                prop_addr = AudioObjectPropertyAddress(0x644f7574, 0x676c6f62, 0)
                coreaudio.AudioObjectRemovePropertyListener(1, byref(prop_addr), self._audio_listener_proc, None)
            except Exception:
                pass
            self._audio_listener_proc = None

    def _audio_callback(self, outdata, frames, time_info, status):
        """Callback de audio de ultra-baja latencia para el stream de sounddevice/PortAudio."""
        bytes_needed = len(outdata)
        with self._audio_lock:
            while True:
                try:
                    chunk = self.audio_queue.get_nowait()
                    self._audio_buffer.extend(chunk)
                except queue.Empty:
                    break

            # Pre-buffer de 50ms (9600 bytes a 48kHz 16-bit estéreo) para absorción suave de fluctuaciones de red
            min_prefill = 9600
            if not self._audio_prefill_done:
                if len(self._audio_buffer) >= min_prefill:
                    self._audio_prefill_done = True
                else:
                    outdata[:] = b'\x00' * bytes_needed
                    return

            # Control de latencia estricto: retener máx 250ms (48000 bytes a 48kHz estéreo)
            # Asegurar SIEMPRE alineación estricta a 4 bytes (16-bit estéreo)
            max_buf = 48000
            excess = len(self._audio_buffer) - max_buf
            if excess > 0:
                excess_aligned = (excess // 4) * 4
                if excess_aligned > 0:
                    del self._audio_buffer[:excess_aligned]

            avail = (len(self._audio_buffer) // 4) * 4
            if avail >= bytes_needed:
                outdata[:] = self._audio_buffer[:bytes_needed]
                del self._audio_buffer[:bytes_needed]
            elif avail > 0:
                outdata[:avail] = self._audio_buffer[:avail]
                outdata[avail:] = b'\x00' * (bytes_needed - avail)
                del self._audio_buffer[:avail]
                self._audio_prefill_done = False
            else:
                outdata[:] = b'\x00' * bytes_needed
                self._audio_prefill_done = False

    def restart_audio_stream(self, force: bool = False):
        """Migra la salida de audio hacia el dispositivo predeterminado actual sin perder paquetes ni pausar el juego."""
        if not self.audio_enabled:
            return

        with self._audio_restart_lock:
            dev_id, dev_name = get_macos_default_audio_output_device()
            if not force and dev_id == self._current_audio_device_id and self.audio_stream and self.audio_stream.active:
                self._audio_device_changed = False
                return

            self._audio_prefill_done = False
            logger.info(f"🎧 Enrutando audio hacia dispositivo predeterminado: '{dev_name}' (ID: {dev_id})...")

            # 1. Abortar y cerrar el stream anterior
            old_st = self.audio_stream
            self.audio_stream = None
            if old_st:
                try:
                    old_st.abort()
                    old_st.close()
                except Exception:
                    pass

            # 2. Reiniciar PortAudio para actualizar la tabla de dispositivos de audio del kernel macOS
            try:
                sd._terminate()
                sd._initialize()
            except Exception as e:
                logger.debug(f"Error reiniciando PortAudio: {e}")

            # 3. Abrir nuevo stream enlazado al dispositivo predeterminado del sistema (device=None)
            try:
                self.audio_stream = sd.RawOutputStream(
                    samplerate=48000,
                    channels=2,
                    dtype="int16",
                    callback=self._audio_callback,
                    latency=0.035,
                    device=None
                )
                self.audio_stream.start()
                self._current_audio_device_id = dev_id
                self._current_audio_device_name = dev_name
                self._audio_device_changed = False
                logger.info(f"🔊 Salida de audio activa y transmitiendo a: '{dev_name}'.")
            except Exception as e:
                logger.warning(f"No se pudo inicializar salida de audio hacia '{dev_name}': {e}")
                self.audio_stream = None

    def check_audio_device(self):
        """Verifica periódicamente si el dispositivo de audio del sistema cambió o si el stream se detuvo."""
        if not self.audio_enabled:
            return

        if self._audio_device_changed:
            self.restart_audio_stream()
            return

        dev_id, _ = get_macos_default_audio_output_device()
        if dev_id is not None and dev_id != self._current_audio_device_id:
            logger.info(f"🎧 Cambio en dispositivo predeterminado de audio (ID: {self._current_audio_device_id} -> {dev_id}).")
            self.restart_audio_stream()
        elif self.audio_stream is not None and not self.audio_stream.active:
            logger.warning("Stream de audio inactivo detectado. Reactivando en dispositivo predeterminado...")
            self.restart_audio_stream(force=True)

    def handle_video(self, frame: av.VideoFrame):
        """Llamado inmediatamente cuando un fotograma de vídeo H.264/HEVC es decodificado."""
        try:
            if getattr(frame.format, "name", "") == "rgb24":
                plane = frame.planes[0]
                w, h = frame.width, frame.height
            else:
                img = frame.to_rgb()
                plane = img.planes[0]
                w, h = img.width, img.height

            self.frame_width = w
            self.frame_height = h
            stride = getattr(plane, "line_size", w * 3)
            tight_size = w * h * 3

            if _CAS_LIB is not None and (self.cas_strength > 0 or stride != w * 3):
                # Doble búfer alterno para evitar tearing mientras el hilo principal lee el Surface anterior
                if not hasattr(self, "_cas_ring") or self._cas_ring_size != tight_size:
                    self._cas_ring = [bytearray(tight_size), bytearray(tight_size)]
                    self._cas_ptrs = [
                        ctypes.addressof((ctypes.c_uint8 * tight_size).from_buffer(self._cas_ring[0])),
                        ctypes.addressof((ctypes.c_uint8 * tight_size).from_buffer(self._cas_ring[1])),
                    ]
                    self._cas_idx = 0
                    self._cas_ring_size = tight_size
                slot_i = self._cas_idx
                self._cas_idx ^= 1
                src_ptr = getattr(plane, "buffer_ptr", None)
                if src_ptr:
                    _CAS_LIB.drps5_cas_rgb24(src_ptr, self._cas_ptrs[slot_i], w, h, stride, self.cas_strength)
                    surface = pygame.image.frombuffer(self._cas_ring[slot_i], (w, h), "RGB")
                else:
                    surface = pygame.image.frombuffer(plane, (w, h), "RGB")
            elif stride != w * 3:
                arr = frame.to_ndarray(format="rgb24")
                surface = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGB")
            else:
                surface = pygame.image.frombuffer(plane, (w, h), "RGB")

            # Descartar fotograma antiguo si la cola está llena para latencia ultra-baja
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self.frame_queue.put_nowait(surface)

            if not hasattr(self, "_logged_first_frame"):
                self._logged_first_frame = True
                logger.info(f"¡Primer fotograma de vídeo decodificado exitosamente! ({w}x{h}, CAS={self.cas_strength})")

            self.fps_counter += 1
            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.fps_displayed = self.fps_counter
                self.fps_counter = 0
                self.last_fps_time = now

        except Exception as e:
            logger.error(f"Error procesando video frame: {e}")

    def close_audio(self):
        st = self.audio_stream
        self.audio_stream = None
        if st:
            try:
                st.abort()
                st.close()
            except Exception:
                pass

    def on_audio_reset(self):
        """Limpia el búfer interno y la cola de reproducción de audio tras un fallo o reinicio del códec."""
        try:
            self._audio_prefill_done = False
            with self._audio_lock:
                self._audio_buffer.clear()
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
        except Exception:
            pass

    def handle_audio(self, frame: av.AudioFrame):
        """Llamado cuando un paquete de audio Opus es decodificado a PCM estéreo."""
        if not self.audio_enabled or frame is None:
            return
        if getattr(frame, "is_corrupt", False):
            return
        try:
            if not self._audio_initialized:
                self._audio_initialized = True
                self.restart_audio_stream(force=True)
            elif self._audio_device_changed:
                self.restart_audio_stream()

            # Asegurar formato s16
            if getattr(frame.format, "name", "") != "s16":
                if not hasattr(self, "_fallback_resampler"):
                    self._fallback_resampler = av.audio.resampler.AudioResampler(
                        format="s16", layout="stereo", rate=48000
                    )
                resampled = self._fallback_resampler.resample(frame)
                if resampled:
                    frame = resampled[0] if isinstance(resampled, (list, tuple)) else resampled
                else:
                    return

            # Extraer PCM estéreo exactamente sin el stride/padding de 128 bytes de FFmpeg (elimina el ruido de lluvia)
            raw_pcm = frame.to_ndarray().tobytes()
            if not raw_pcm:
                return
            pcm_len = (len(raw_pcm) // 4) * 4
            if pcm_len < len(raw_pcm):
                raw_pcm = raw_pcm[:pcm_len]

            if self.audio_queue.full():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    pass
            self.audio_queue.put_nowait(raw_pcm)
        except Exception:
            pass

    def close(self):
        self._remove_coreaudio_listener()
        self.close_audio()
        if hasattr(self, "_audio_buffer"):
            try:
                with self._audio_lock:
                    self._audio_buffer.clear()
            except Exception:
                pass

def run_drps5_stream(
    host_ip: str,
    regist_key: str,
    rp_key: str,
    mac_address: str = "AA:BB:CC:DD:EE:FF",
    account_id: str = "AAAAAAAAAAAAAAAAAAAAAA==",
    resolution_str: str = "720p",
    fps_val: int = 60,
    codec_str: str = "hevc",
    hdr: bool = False,
    audio_enabled: bool = True,
    fullscreen: bool = False,
    show_hud: bool = True,
    console_type: str = "PS5",
    bitrate_kbps: int = 0,
    upscale_mode: str = "auto"
):
    """Inicia la ventana de visualización y control de pantalla remota de la PS5 o PS4."""
    host_ip = clean_ip_target(host_ip)
    is_ps4 = str(console_type).upper() == "PS4"
    target_console_name = "PS4" if is_ps4 else "PS5"
    if is_ps4:
        codec_str = "h264"
        if resolution_str in ("2160p", "1440p"):
            resolution_str = "1080p"

    # Integración macOS nativa
    if sys.platform == "darwin":
        try:
            import Foundation
            import AppKit
            bundle = Foundation.NSBundle.mainBundle()
            info = bundle.infoDictionary()
            if info is not None:
                info["CFBundleName"] = "DRPS5"
                info["CFBundleDisplayName"] = "DRPS5"
            Foundation.NSProcessInfo.processInfo().setProcessName_("DRPS5")

            cocoa_app = AppKit.NSApplication.sharedApplication()
            cocoa_app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)

            main_menu = cocoa_app.mainMenu()
            if main_menu and main_menu.numberOfItems() > 0:
                app_item = main_menu.itemAtIndex_(0)
                if app_item:
                    app_item.setTitle_("DRPS5")
                    sub = app_item.submenu()
                    if sub:
                        sub.setTitle_("DRPS5")
        except Exception as e:
            logger.debug(f"Cocoa AppKit setup: {e}")

    # Forzar controladores directos HIDAPI para DualSense en SDL2 (evita conflicto con cursor de macOS)
    os.environ["SDL_JOYSTICK_HIDAPI_PS5"] = "1"
    os.environ["SDL_JOYSTICK_HIDAPI"] = "1"

    # Aceleración GPU 2K/4K @ 60FPS (Metal en macOS M/Intel; Direct3D 11 en Windows x86/ARM64)
    os.environ["SDL_RENDER_SCALE_QUALITY"] = "2"
    os.environ["SDL_HINT_RENDER_SCALE_QUALITY"] = "2"
    if sys.platform == "darwin":
        os.environ.setdefault("SDL_RENDER_DRIVER", "metal")
    elif sys.platform == "win32":
        os.environ.setdefault("SDL_RENDER_DRIVER", "direct3d11")

    # Prevenir reposo / App Nap durante streaming
    app_nap_activity = None
    if sys.platform == "darwin":
        try:
            import AppKit
            app_nap_activity = AppKit.NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
                AppKit.NSActivityUserInitiated | AppKit.NSActivityLatencyCritical,
                "DRPS5 Pantalla Remota PS5 Background Streaming"
            )
            logger.info("🛡️ macOS App Nap deshabilitado con NSActivityLatencyCritical para estabilidad en segundo plano.")
        except Exception as e:
            logger.debug(f"No se pudo desactivar App Nap: {e}")
    elif sys.platform == "win32":
        try:
            import ctypes
            # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_AWAYMODE_REQUIRED (0x00000040)
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000041)
            logger.info("🛡️ Modo de suspensión de Windows prevenido durante la transmisión de DRPS5.")
        except Exception as e:
            logger.debug(f"Error llamando SetThreadExecutionState: {e}")

    pygame.init()
    pygame.font.init()
    pygame.joystick.init()
    try:
        sdl2_controller.init()
    except Exception as e:
        logger.warning(f"No se pudo inicializar sdl2_controller: {e}")

    # Estructuras para mandos (GameController API de SDL2 + Joysticks genéricos indexados por instance_id)
    active_controllers = {}
    active_joysticks = {}
    connected_controller_name = "Teclado Activo"

    def update_controller_name():
        nonlocal connected_controller_name
        if active_controllers:
            first_c = next(iter(active_controllers.values()))
            connected_controller_name = first_c.name or "GameController"
        elif active_joysticks:
            first_j = next(iter(active_joysticks.values()))
            connected_controller_name = first_j.get_name() or "Mando Genérico"
        else:
            connected_controller_name = "Teclado Activo"

    toast_msg = None
    toast_expire_time = 0.0
    def set_controller_toast(msg: str):
        nonlocal toast_msg, toast_expire_time
        toast_msg = msg
        toast_expire_time = time.time() + 3.5

    last_refresh_time = 0.0
    def refresh_all_controllers(force: bool = False):
        """Re-enumera mandos conectados sin destruir mandos ya activos y operativos."""
        nonlocal last_refresh_time
        now = time.time()
        if not force and (now - last_refresh_time < 0.25):
            return
        last_refresh_time = now

        # Verificar qué controladores siguen físicamente conectados
        for inst_id, c in list(active_controllers.items()):
            try:
                if not c.attached():
                    c.quit()
                    active_controllers.pop(inst_id, None)
                    set_controller_toast("⚠️ Mando desconectado - Usa Teclado o reconecta")
            except Exception:
                active_controllers.pop(inst_id, None)

        for inst_id, j in list(active_joysticks.items()):
            try:
                if not j.get_init():
                    active_joysticks.pop(inst_id, None)
            except Exception:
                active_joysticks.pop(inst_id, None)

        pygame.event.pump()
        total_devs = pygame.joystick.get_count()
        for i in range(total_devs):
            try:
                temp_j = pygame.joystick.Joystick(i)
                temp_j.init()
                inst = temp_j.get_instance_id()

                if inst in active_controllers or inst in active_joysticks:
                    continue

                if sdl2_controller.is_controller(i):
                    c = sdl2_controller.Controller(i)
                    c.init()
                    active_controllers[inst] = c
                    logger.info(f"🎮 GameController registrado [inst={inst}, dev={i}]: {c.name}")
                    set_controller_toast(f"🎮 {c.name} Conectado")
                else:
                    active_joysticks[inst] = temp_j
                    logger.info(f"🕹️ Joystick registrado [inst={inst}, dev={i}]: {temp_j.get_name()}")
                    set_controller_toast(f"🕹️ {temp_j.get_name()} Conectado")
            except Exception as e:
                logger.debug(f"Error enumerando mando {i}: {e}")
            except Exception as e:
                logger.debug(f"Error enumerando mando {i}: {e}")

        update_controller_name()

    # Detección inicial de mandos
    refresh_all_controllers()

    # Auto-detección de soporte real HDR/EDR en el monitor macOS para evitar lavado de color y 3x carga CPU en pantallas SDR
    if hdr and sys.platform == "darwin":
        try:
            import AppKit
            edr_max = max(
                (float(sc.maximumPotentialExtendedDynamicRangeColorComponentValue()) for sc in AppKit.NSScreen.screens()),
                default=1.0
            )
            if edr_max <= 1.05:
                logger.info("📺 Pantalla SDR detectada (EDR=%.2f). Ajustando transmisión a SDR 8-bit nativo para color fiel y menor latencia.", edr_max)
                hdr = False
        except Exception:
            pass

    # Dimensiones de ventana según resolución seleccionada (360p a 4K 2160p)
    res_dimensions = {
        "2160p": (3840, 2160),
        "1440p": (2560, 1440),
        "1080p": (1920, 1080),
        "720p": (1280, 720),
        "540p": (960, 540),
        "360p": (640, 360),
    }
    target_w, target_h = res_dimensions.get(resolution_str, (1920, 1080))
    try:
        disp_info = pygame.display.Info()
        if disp_info.current_w > 0 and disp_info.current_h > 0 and not fullscreen:
            max_win_w = int(disp_info.current_w * 0.90)
            max_win_h = int(disp_info.current_h * 0.86)
            if target_w > max_win_w or target_h > max_win_h:
                scale = min(max_win_w / float(target_w), max_win_h / float(target_h))
                target_w = max(960, int(target_w * scale))
                target_h = max(540, int(target_h * scale))
    except Exception:
        pass

    # Usar siempre pygame.SCALED + Metal para que la GPU realice el escalado a Retina/2K/4K con cero copia CPU
    flags = pygame.RESIZABLE
    use_gpu_scaled = hasattr(pygame, "SCALED")
    if use_gpu_scaled:
        flags = pygame.RESIZABLE | pygame.SCALED
        if resolution_str in ("2160p", "1440p", "1080p"):
            mode_size = (1920, 1080)
        elif resolution_str == "720p":
            mode_size = (1280, 720)
        else:
            mode_size = res_dimensions.get(resolution_str, (1280, 720))
    else:
        mode_size = (target_w, target_h)

    # Intensidad del filtro nativo Contrast Adaptive Sharpening (CAS) según el perfil elegido
    if upscale_mode == "cas_high":
        cas_strength = 210
    elif upscale_mode == "cas_med":
        cas_strength = 145
    elif upscale_mode == "direct":
        cas_strength = 0
    else:
        cas_strength = 145 if resolution_str in ("2160p", "1440p") else (85 if resolution_str == "1080p" else 0)

    # Establecer título de ventana antes y después de inicializar la pantalla
    pygame.display.set_caption(f"DRPS5 - Pantalla Remota {target_console_name}")

    def configure_cocoa_app_identity():
        """Asegura el nombre DRPS5 y el icono oficial en el Dock de macOS (AppIcon.icns)."""
        try:
            import AppKit
            cocoa_app = AppKit.NSApplication.sharedApplication()
            try:
                AppKit.NSProcessInfo.processInfo().setProcessName_("DRPS5")
            except Exception:
                pass

            icns_candidates = [
                "/Applications/DRPS5.app/Contents/Resources/AppIcon.icns",
                os.path.join(base_dir, "AppIcon.icns"),
                os.path.join(base_dir, "Resources", "AppIcon.icns"),
                "/Users/rleon/Documents/PXPLAY/DRPS5/AppIcon.icns"
            ]
            for icns in icns_candidates:
                if os.path.exists(icns):
                    ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(icns)
                    if ns_img:
                        cocoa_app.setApplicationIconImage_(ns_img)
                        cocoa_app.dockTile().display()
                        break
        except Exception as e:
            logger.debug(f"configure_cocoa_app_identity: {e}")

    configure_cocoa_app_identity()

    # Pre-cargar icono oficial en Pygame antes de inicializar la ventana
    try:
        icon_candidates = [
            os.path.join(base_dir, "app_icon_1024.png"),
            "/Applications/DRPS5.app/Contents/Resources/app_icon_1024.png",
            os.path.join(base_dir, "Resources", "app_icon_1024.png"),
            "/Users/rleon/Documents/PXPLAY/DRPS5/app_icon_1024.png"
        ]
        for ic_path in icon_candidates:
            if os.path.exists(ic_path):
                icon_surf = pygame.image.load(ic_path)
                pygame.display.set_icon(icon_surf)
                break
    except Exception as ic_err:
        logger.debug(f"pygame.display.set_icon pre-mode: {ic_err}")

    try:
        screen = pygame.display.set_mode(mode_size, flags)
        if not fullscreen and use_gpu_scaled and (target_w != mode_size[0] or target_h != mode_size[1]):
            try:
                from pygame._sdl2 import video as _sdl2_vid
                _win = _sdl2_vid.Window.from_display_module()
                _win.size = (target_w, target_h)
                _win.position = _sdl2_vid.WINDOWPOS_CENTERED
            except Exception:
                pass
    except pygame.error:
        flags = pygame.RESIZABLE
        use_gpu_scaled = False
        mode_size = (target_w, target_h)
        screen = pygame.display.set_mode(mode_size, flags)
    pygame.display.set_caption(f"DRPS5 - Pantalla Remota {target_console_name}")

    def configure_cocoa_window():
        """Asegura tracking de ratón y modo pantalla completa nativo en macOS Cocoa sin recrear la ventana."""
        try:
            import AppKit
            cocoa_app = AppKit.NSApplication.sharedApplication()
            try:
                AppKit.NSProcessInfo.processInfo().setProcessName_("DRPS5")
            except Exception:
                pass
            for win in cocoa_app.windows():
                win.setAcceptsMouseMovedEvents_(True)
                win.setCollectionBehavior_(
                    AppKit.NSWindowCollectionBehaviorFullScreenPrimary |
                    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                )
                try:
                    win.setHidesOnDeactivate_(False)
                except Exception:
                    pass
                if hdr and hasattr(win, "contentView") and win.contentView():
                    try:
                        win.contentView().setWantsLayer_(True)
                        layer = win.contentView().layer()
                        if layer and hasattr(layer, "setWantsExtendedDynamicRangeContent_"):
                            layer.setWantsExtendedDynamicRangeContent_(True)
                    except Exception as edr_err:
                        logger.debug(f"EDR activation: {edr_err}")
        except Exception as e:
            logger.debug(f"configure_cocoa_window: {e}")

    def toggle_macos_fullscreen():
        """Alterna pantalla completa nativa de macOS (Spaces) o pantalla completa en Windows."""
        if sys.platform == "darwin":
            try:
                import AppKit
                cocoa_app = AppKit.NSApplication.sharedApplication()
                win = cocoa_app.keyWindow() or (cocoa_app.windows()[0] if cocoa_app.windows() else None)
                if win:
                    win.toggleFullScreen_(None)
                    return True
            except Exception as e:
                logger.debug(f"toggle_macos_fullscreen: {e}")
        else:
            try:
                pygame.display.toggle_fullscreen()
                return True
            except Exception as e:
                logger.debug(f"toggle_fullscreen: {e}")
        return False

    configure_cocoa_window()
    configure_cocoa_app_identity()

    if fullscreen:
        toggle_macos_fullscreen()

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Helvetica", 18, bold=True)
    small_font = pygame.font.SysFont("Helvetica", 14)
    menu_title_font = pygame.font.SysFont("Helvetica", 20, bold=True)
    menu_item_font = pygame.font.SysFont("Helvetica", 15, bold=True)

    receiver = DRPS5Receiver(audio_enabled=audio_enabled, cas_strength=cas_strength)

    # Construir mapa de hosts resiliente para UserProfile
    clean_mac = (mac_address or "AA:BB:CC:DD:EE:FF").strip()
    host_type_val = TYPE_PS4 if is_ps4 else TYPE_PS5
    hosts_dict = {}
    for cand in [clean_mac, clean_mac.upper(), clean_mac.lower(), clean_mac.replace(":", ""), host_ip, "AA:BB:CC:DD:EE:FF"]:
        if cand:
            hosts_dict[cand] = {
                "type": host_type_val,
                "data": {
                    "RegistKey": regist_key or "",
                    "RP-Key": rp_key
                }
            }

    user_profile = UserProfile("DRPS5_User", {
        "id": account_id or "AAAAAAAAAAAAAAAAAAAAAA==",
        "hosts": hosts_dict
    })

    res_parsed = Resolution.parse(resolution_str)
    fps_parsed = FPS.parse("high" if int(fps_val) == 60 else "low")

    session_loop = asyncio.new_event_loop()
    session = Session(
        host=host_ip,
        profile=user_profile,
        loop=session_loop,
        receiver=receiver,
        resolution=res_parsed,
        fps=fps_parsed,
        codec=codec_str,
        hdr=hdr,
        bitrate_kbps=int(bitrate_kbps or 0),
    )

    controller = Controller()
    controller.connect(session)

    session_state = {
        "connected": False,
        "error": None,
        "status_message": f"Conectando a {target_console_name} ({host_ip})..."
    }

    def _on_status_update(msg):
        logger.info(f"Estado de conexión: {msg}")
        session_state["status_message"] = msg

    if hasattr(session, "events") and session.events:
        session.events.on("status_update", _on_status_update)

    def _run_async_session():
        asyncio.set_event_loop(session_loop)
        try:
            logger.info(f"Iniciando sesión de {target_console_name} en {host_ip}...")
            ok = session_loop.run_until_complete(session.start())
            if ok:
                session_state["connected"] = True
                logger.info("Sesión de PS5 autenticada y conectada con éxito.")
                try:
                    controller.start()
                except Exception as e:
                    logger.warning(f"No se pudo iniciar el worker de controller: {e}")
                session_loop.run_forever()
                if session.is_stopped and not session_state.get("error"):
                    session_state["error"] = session.disconnect_reason or session.error or "La conexión con la PS5 se ha cerrado."
            else:
                err_msg = session.error or "La PS5 no respondió o rechazó la autenticación."
                if not err_msg or err_msg == "''" or err_msg == '""':
                    err_msg = f"Host @ {host_ip} no responde o rechazó la conexión."
                session_state["error"] = err_msg
                logger.error(f"Fallo en session.start: {session_state['error']}")
        except Exception as e:
            err_msg = str(e)
            if not err_msg or err_msg == "''" or err_msg == '""':
                err_msg = f"Error de comunicación con {host_ip} ({type(e).__name__})"
            session_state["error"] = err_msg
            logger.error(f"Excepción en bucle de sesión: {e}", exc_info=True)
        finally:
            try:
                session_loop.close()
            except Exception:
                pass

    session_thread = threading.Thread(target=_run_async_session, daemon=True)
    session_thread.start()

    running = True
    show_hud = bool(show_hud)
    current_frame = None
    pressed_buttons = set()
    pressed_physical_buttons = {}

    # Control del Menú de Transmisión (equivalente al in-stream overlay de Android)
    stream_menu_open = False
    menu_selected_idx = 0
    menu_items_rects = []
    menu_card_rect = pygame.Rect(0, 0, 0, 0)
    last_stick_nav_time = 0.0

    def get_menu_items():
        cas_label = "Desactivado"
        if cas_strength >= 180:
            cas_label = "Alto (100%)"
        elif cas_strength >= 115:
            cas_label = "Medio (60%)"
        elif cas_strength > 0:
            cas_label = "Bajo (30%)"

        return [
            {"id": "resume", "icon": "▶", "title": "Volver al juego", "desc": "Reanudar transmisión", "badge": None},
            {"id": "hud", "icon": "⚙", "title": "HUD en pantalla", "desc": "Estadísticas en tiempo real", "badge": "Activado" if show_hud else "Oculto"},
            {"id": "cas", "icon": "✦", "title": "Nitidez CAS (Metal)", "desc": "Escalado adaptativo GPU", "badge": cas_label},
            {"id": "audio", "icon": "🔊", "title": "Audio de sesión", "desc": "Salida de sonido PCM 48kHz", "badge": "Activado" if getattr(receiver, "audio_enabled", True) else "Silenciado"},
            {"id": "fullscreen", "icon": "🖥️", "title": "Pantalla completa", "desc": "Modo ventana o Spaces", "badge": "Completa" if fullscreen else "Ventana"},
            {"id": "disconnect", "icon": "✕", "title": "Desconectar sesión", "desc": "Salir al menú de DRPS5", "badge": None, "danger": True},
        ]

    def execute_menu_action(action_id: str):
        nonlocal stream_menu_open, show_hud, cas_strength, fullscreen, running
        if action_id == "resume":
            stream_menu_open = False
        elif action_id == "hud":
            show_hud = not show_hud
            receiver._hud_cache_key = None
        elif action_id == "cas":
            if cas_strength < 40:
                cas_strength = 85
            elif cas_strength < 115:
                cas_strength = 145
            elif cas_strength < 180:
                cas_strength = 210
            else:
                cas_strength = 0
            receiver.cas_strength = cas_strength
            receiver._hud_cache_key = None
        elif action_id == "audio":
            new_audio = not getattr(receiver, "audio_enabled", True)
            receiver.audio_enabled = new_audio
            receiver._hud_cache_key = None
        elif action_id == "fullscreen":
            fullscreen = not fullscreen
            if not toggle_macos_fullscreen():
                try:
                    pygame.display.toggle_fullscreen()
                except Exception:
                    pass
            configure_cocoa_window()
            try:
                if session and not session.is_stopped:
                    session.stream.send_corrupt(0, 0)
            except Exception:
                pass
        elif action_id == "disconnect":
            logger.info("Desconexión solicitada desde el menú de transmisión.")
            running = False
            stream_menu_open = False

    # Control de visibilidad automática del cursor del ratón y tracking continuo
    last_mouse_activity = time.time()
    last_mouse_pos = pygame.mouse.get_pos()
    mouse_visible = True
    last_esc_time = 0.0
    last_audio_check = 0.0

    # Emisores de pulsos de hardware garantizados (PS5 Home y Touchpad)
    def trigger_ps_pulse():
        def _pulse():
            try:
                logger.info("⚡ Emitiendo pulso garantizado de botón PS (150ms)...")
                controller.button("PS", action="press")
                time.sleep(0.15)
                controller.button("PS", action="release")
            except Exception as e:
                logger.warning(f"Error emitiendo pulso PS: {e}")
        threading.Thread(target=_pulse, daemon=True).start()

    def trigger_touchpad_pulse():
        def _pulse():
            try:
                logger.info("📱 Emitiendo pulso garantizado de Touchpad (150ms)...")
                controller.button("TOUCHPAD", action="press")
                time.sleep(0.15)
                controller.button("TOUCHPAD", action="release")
            except Exception as e:
                logger.warning(f"Error emitiendo pulso Touchpad: {e}")
        threading.Thread(target=_pulse, daemon=True).start()

    # Cargar mapeo de botones y preferencias de jugabilidad
    cfg_circle_confirm = False
    try:
        from drps5_config import DRPS5Config
        full_cfg = DRPS5Config.load()
        cfg_circle_confirm = bool(full_cfg.get("circle_confirm", False))
        gp_map = DRPS5Config.get_gamepad_mapping()
        cfg_ps_btn = int(gp_map.get("ps_button", 5))
        cfg_touch_btn = int(gp_map.get("touchpad_button", 20))
        cfg_opt_btn = int(gp_map.get("options_button", 6))
        cfg_share_btn = int(gp_map.get("share_button", 4))
        cfg_deadzone = float(gp_map.get("stick_deadzone", 0.10))
        logger.info(f"Mapeo de mando activo: PS={cfg_ps_btn}, Touchpad={cfg_touch_btn}, Options={cfg_opt_btn}, Share={cfg_share_btn}, Deadzone={cfg_deadzone}, CircleConfirm={cfg_circle_confirm}")
    except Exception as e:
        logger.debug(f"Error cargando mapeo de mando: {e}")
        cfg_ps_btn = 5
        cfg_touch_btn = 20
        cfg_opt_btn = 6
        cfg_share_btn = 4
        cfg_deadzone = 0.10

    def remap_confirm_button(btn_name: Optional[str]) -> Optional[str]:
        if cfg_circle_confirm:
            if btn_name == "CROSS":
                return "CIRCLE"
            if btn_name == "CIRCLE":
                return "CROSS"
        return btn_name

    # Estado de sticks con zona muerta radial 2D real y envío asíncrono a 125Hz sin bloquear el bucle de renderizado
    raw_stick_left = [0.0, 0.0]
    raw_stick_right = [0.0, 0.0]
    stick_left = [0.0, 0.0]
    stick_right = [0.0, 0.0]
    stick_deadzone = max(0.03, min(0.35, cfg_deadzone))
    stick_min_delta = 0.005
    trigger_l2_pressed = False
    trigger_r2_pressed = False

    def apply_radial_stick(rx: float, ry: float, deadzone: float = stick_deadzone) -> tuple[float, float]:
        """Zona muerta radial 2D genuina con curva suave de precisión (sin encaje axial en X/Y)."""
        mag = math.hypot(rx, ry)
        if mag <= deadzone:
            return 0.0, 0.0
        clamped = min(1.0, mag)
        norm = (clamped - deadzone) / (1.0 - deadzone)
        # Curva híbrida 85% lineal + 15% cúbica para micro-apuntado preciso sin perder velocidad máxima
        curved = norm * (0.85 + 0.15 * norm * norm)
        scale = curved / mag
        return max(-1.0, min(1.0, rx * scale)), max(-1.0, min(1.0, ry * scale))

    def apply_stick_filter(raw_val: float, deadzone: float = stick_deadzone) -> float:
        if abs(raw_val) <= deadzone:
            return 0.0
        sign = 1.0 if raw_val > 0 else -1.0
        scaled = sign * ((abs(raw_val) - deadzone) / (1.0 - deadzone))
        return max(-1.0, min(1.0, scaled))

    def push_stick_2d(side: str, raw_vec: list, out_vec: list):
        fx, fy = apply_radial_stick(raw_vec[0], raw_vec[1], stick_deadzone)
        centered_now = (fx == 0.0 and fy == 0.0 and (out_vec[0] != 0.0 or out_vec[1] != 0.0))
        if centered_now or abs(fx - out_vec[0]) >= stick_min_delta or abs(fy - out_vec[1]) >= stick_min_delta:
            out_vec[0], out_vec[1] = fx, fy
            controller.stick(side, point=(fx, fy))
            if centered_now:
                controller.update_sticks()

    last_stick_watchdog = 0.0
    last_hotplug_check = 0.0
    last_frame_recv_time = time.time()
    has_received_any_frame = False
    last_keyframe_request_time = 0.0

    try:
        while running:
            # Procesar eventos de entrada
            for event in pygame.event.get():
                try:
                    if event.type in (pygame.QUIT, getattr(pygame, "WINDOWCLOSE", 32788)):
                        logger.info("Cierre de ventana solicitado (pygame.QUIT / WINDOWCLOSE). Saliendo...")
                        running = False
                        break

                    # Movimiento de ratón: restaurar visibilidad sólo si el movimiento es intencional (>6px)
                    # evitando que el micro-temblor o el giroscopio del DualSense despierten el cursor
                    elif event.type == pygame.MOUSEMOTION:
                        m_dx, m_dy = getattr(event, "rel", (0, 0))
                        if abs(m_dx) > 3 or abs(m_dy) > 3:
                            last_mouse_activity = time.time()
                            last_mouse_pos = event.pos
                            if not mouse_visible:
                                pygame.mouse.set_visible(True)
                                mouse_visible = True
                        if stream_menu_open:
                            for idx, (r, a_id) in enumerate(menu_items_rects):
                                if r.collidepoint(event.pos):
                                    menu_selected_idx = idx
                                    break

                    elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                        last_mouse_activity = time.time()
                        last_mouse_pos = event.pos
                        if not mouse_visible:
                            pygame.mouse.set_visible(True)
                            mouse_visible = True

                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            if stream_menu_open:
                                clicked_action = None
                                for r, a_id in menu_items_rects:
                                    if r.collidepoint(event.pos):
                                        clicked_action = a_id
                                        break
                                if clicked_action:
                                    execute_menu_action(clicked_action)
                                elif not menu_card_rect.collidepoint(event.pos):
                                    stream_menu_open = False
                                continue

                            # Detección de clic en botón Salir translúcido en esquina superior derecha
                            screen_w, _ = screen.get_size()
                            btn_w, btn_h = 92, 34
                            btn_rect = pygame.Rect(screen_w - btn_w - 16, 16, btn_w, btn_h)
                            if btn_rect.collidepoint(event.pos):
                                logger.info("Botón Salir pulsado con el ratón. Desconectando sesión...")
                                running = False
                                break

                            # Detección de clic en el HUD para abrir el menú de transmisión
                            hud_rect = pygame.Rect(10, 10, 400, 92)
                            if show_hud and hud_rect.collidepoint(event.pos):
                                logger.info("HUD pulsado con el ratón. Abriendo menú de transmisión...")
                                stream_menu_open = True
                                menu_selected_idx = 0
                                continue

                    # Eventos de cambio de pantalla / desconexión o reposo de lentes XR / cambio de resolución
                    elif event.type in (getattr(pygame, "WINDOWDISPLAYCHANGED", 32791),
                                        getattr(pygame, "WINDOWSIZECHANGED", 32779),
                                        getattr(pygame, "WINDOWRESIZED", 32778),
                                        getattr(pygame, "WINDOWEXPOSED", 32776),
                                        getattr(pygame, "WINDOWRESTORED", 32782)):
                        try:
                            screen = pygame.display.get_surface()
                            if screen is None or screen.get_width() <= 10 or screen.get_height() <= 10:
                                screen = pygame.display.set_mode((target_w, target_h), flags)
                            configure_cocoa_window()
                        except Exception as disp_err:
                            logger.debug(f"Ajuste de display tras evento {event.type}: {disp_err}")

                    elif event.type in (getattr(pygame, "WINDOWFOCUSLOST", 32786),
                                        getattr(pygame, "WINDOWHIDDEN", 32775)):
                        # Ventana en segundo plano o lentes en reposo: neutralizar sticks y liberar botones en PS5
                        stick_left = [0.0, 0.0]
                        stick_right = [0.0, 0.0]
                        controller.stick("left", point=(0.0, 0.0))
                        controller.stick("right", point=(0.0, 0.0))
                        controller.update_sticks()
                        pressed_physical_buttons.clear()
                        for btn in list(pressed_buttons):
                            try:
                                controller.button(btn, action="release")
                            except Exception:
                                pass
                        pressed_buttons.clear()

                    elif event.type == getattr(pygame, "WINDOWFOCUSGAINED", 32785):
                        refresh_all_controllers()
                        try:
                            if hasattr(session, "stream") and session.stream and hasattr(session.stream, "send_idr_request"):
                                v_st = getattr(getattr(session, "av", None), "_v_stream", None)
                                if v_st:
                                    v_st._waiting_for_idr = True
                                session.stream.send_idr_request()
                                logger.info("⚡ Foco recuperado: solicitando IDR keyframe inmediato a PS5...")
                        except Exception:
                            pass

                    # Hotplugging dinámico de mandos (DualSense cable/Bluetooth, Backbone One, Xbox, etc.)
                    elif event.type in (pygame.CONTROLLERDEVICEADDED, pygame.JOYDEVICEADDED):
                        refresh_all_controllers(force=True)

                    elif event.type in (pygame.CONTROLLERDEVICEREMOVED, pygame.JOYDEVICEREMOVED):
                        inst_id = getattr(event, "instance_id", getattr(event, "which", 0))
                        logger.info(f"Mando desconectado (instance_id={inst_id}). Neutralizando y refrescando...")
                        stick_left = [0.0, 0.0]
                        stick_right = [0.0, 0.0]
                        controller.stick("left", point=(0.0, 0.0))
                        controller.stick("right", point=(0.0, 0.0))
                        controller.update_sticks()
                        pressed_physical_buttons.clear()
                        for btn in list(pressed_buttons):
                            try:
                                controller.button(btn, action="release")
                            except Exception:
                                pass
                        pressed_buttons.clear()
                        refresh_all_controllers(force=True)

                    # Eventos de botones de GameController (DualSense / Backbone One / Xbox)
                    elif event.type == pygame.CONTROLLERBUTTONDOWN:
                        logger.info(f"🎮 CONTROLLERBUTTONDOWN: button={event.button}")
                        btn_name = SDL_CONTROLLER_MAP.get(event.button)

                        # Si el menú de transmisión está abierto, capturar entradas para navegarlo
                        if stream_menu_open:
                            items = get_menu_items()
                            if event.button == pygame.CONTROLLER_BUTTON_DPAD_UP or btn_name == "UP":
                                menu_selected_idx = (menu_selected_idx - 1) % len(items)
                            elif event.button == pygame.CONTROLLER_BUTTON_DPAD_DOWN or btn_name == "DOWN":
                                menu_selected_idx = (menu_selected_idx + 1) % len(items)
                            elif event.button == pygame.CONTROLLER_BUTTON_A or btn_name == ("CIRCLE" if cfg_circle_confirm else "CROSS"):
                                if 0 <= menu_selected_idx < len(items):
                                    execute_menu_action(items[menu_selected_idx]["id"])
                            elif event.button == pygame.CONTROLLER_BUTTON_B or btn_name == ("CROSS" if cfg_circle_confirm else "CIRCLE"):
                                stream_menu_open = False
                            elif event.button in (cfg_opt_btn, cfg_share_btn, pygame.CONTROLLER_BUTTON_START, pygame.CONTROLLER_BUTTON_BACK) or btn_name in ("OPTIONS", "SHARE"):
                                stream_menu_open = False
                            continue

                        target_name = None

                        # Prioridad 1: Botón PS (Home) asignado o estándar
                        if event.button == cfg_ps_btn or btn_name == "PS":
                            logger.info(f"⚡ Pulsación detectada para Botón PS (botón {event.button}). Enviando press a PS5...")
                            target_name = "PS"
                        # Prioridad 2: Botón Touchpad asignado o estándar (B20 DualSense, B16 Backbone, etc.)
                        elif event.button in (cfg_touch_btn, 20, 16, 18, 15) or btn_name == "TOUCHPAD":
                            logger.info(f"📱 Pulsación detectada para Touchpad (botón {event.button}). Manteniendo presionado...")
                            target_name = "TOUCHPAD"
                        # Prioridad 3: Botones Options / Share según mapeo
                        elif event.button == cfg_opt_btn or btn_name == "OPTIONS":
                            target_name = "OPTIONS"
                        elif event.button == cfg_share_btn or btn_name == "SHARE":
                            target_name = "SHARE"
                        elif btn_name:
                            target_name = remap_confirm_button(btn_name)

                        if target_name:
                            pressed_physical_buttons[event.button] = target_name
                            if target_name not in pressed_buttons:
                                pressed_buttons.add(target_name)
                                controller.button(target_name, action="press")

                            # Menú de transmisión por combo de mando: CAPTURE / SHARE + OPTIONS
                            if "SHARE" in pressed_buttons and "OPTIONS" in pressed_buttons:
                                logger.info("🎮 Combo Capture + Options detectado en mando físico. Abriendo menú de transmisión...")
                                for b in ("SHARE", "OPTIONS"):
                                    try:
                                        controller.button(b, action="release")
                                    except Exception:
                                        pass
                                    pressed_buttons.discard(b)
                                pressed_physical_buttons.clear()
                                stream_menu_open = not stream_menu_open
                                if stream_menu_open:
                                    menu_selected_idx = 0
                                    mouse_visible = True
                                    pygame.mouse.set_visible(True)
                                continue

                    elif event.type == pygame.CONTROLLERBUTTONUP:
                        if stream_menu_open:
                            continue
                        btn_name = SDL_CONTROLLER_MAP.get(event.button)
                        target_name = None
                        if event.button == cfg_ps_btn or btn_name == "PS":
                            logger.info(f"⚡ Liberación detectada para Botón PS (botón {event.button}). Liberando...")
                            target_name = "PS"
                        elif event.button in (cfg_touch_btn, 20, 16, 18, 15) or btn_name == "TOUCHPAD":
                            logger.info(f"📱 Liberación detectada para Touchpad (botón {event.button}). Liberando...")
                            target_name = "TOUCHPAD"
                        elif event.button == cfg_opt_btn or btn_name == "OPTIONS":
                            target_name = "OPTIONS"
                        elif event.button == cfg_share_btn or btn_name == "SHARE":
                            target_name = "SHARE"
                        elif btn_name:
                            target_name = remap_confirm_button(btn_name)

                        if target_name:
                            pressed_physical_buttons.pop(event.button, None)
                            if target_name not in pressed_physical_buttons.values():
                                pressed_buttons.discard(target_name)
                                controller.button(target_name, action="release")

                    # Ejes analógicos y gatillos de GameController (-32768 a 32767) con zona muerta radial 2D real
                    elif event.type == pygame.CONTROLLERAXISMOTION:
                        if stream_menu_open:
                            axis = getattr(event, "axis", -1)
                            val = getattr(event, "value", 0)
                            if axis == pygame.CONTROLLER_AXIS_LEFTY:
                                norm_val = val / 32767.0
                                now = time.time()
                                if norm_val < -0.55 and (now - last_stick_nav_time > 0.22):
                                    menu_selected_idx = (menu_selected_idx - 1) % len(get_menu_items())
                                    last_stick_nav_time = now
                                elif norm_val > 0.55 and (now - last_stick_nav_time > 0.22):
                                    menu_selected_idx = (menu_selected_idx + 1) % len(get_menu_items())
                                    last_stick_nav_time = now
                            continue
                        val = max(-1.0, min(1.0, event.value / 32767.0))
                        axis = event.axis
                        if axis == pygame.CONTROLLER_AXIS_LEFTX:
                            raw_stick_left[0] = val
                            push_stick_2d("left", raw_stick_left, stick_left)
                        elif axis == pygame.CONTROLLER_AXIS_LEFTY:
                            raw_stick_left[1] = val
                            push_stick_2d("left", raw_stick_left, stick_left)
                        elif axis == pygame.CONTROLLER_AXIS_RIGHTX:
                            raw_stick_right[0] = val
                            push_stick_2d("right", raw_stick_right, stick_right)
                        elif axis == pygame.CONTROLLER_AXIS_RIGHTY:
                            raw_stick_right[1] = val
                            push_stick_2d("right", raw_stick_right, stick_right)
                        elif axis == pygame.CONTROLLER_AXIS_TRIGGERLEFT:
                            is_down = (event.value > 8000) if not trigger_l2_pressed else (event.value > 4500)
                            if is_down != trigger_l2_pressed:
                                trigger_l2_pressed = is_down
                                controller.button("L2", action="press" if is_down else "release")
                        elif axis == pygame.CONTROLLER_AXIS_TRIGGERRIGHT:
                            is_down = (event.value > 8000) if not trigger_r2_pressed else (event.value > 4500)
                            if is_down != trigger_r2_pressed:
                                trigger_r2_pressed = is_down
                                controller.button("R2", action="press" if is_down else "release")

                    # Soporte para Joysticks genéricos cuando no hay GameController activo
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if active_controllers and event.button not in (cfg_touch_btn, 20, 19, 18, 16, 15, cfg_ps_btn):
                            continue
                        logger.info(f"🕹️ JOYBUTTONDOWN (Joystick Genérico): button={event.button}")
                        btn_name = RAW_JOYSTICK_BUTTON_MAP.get(event.button)

                        if stream_menu_open:
                            items = get_menu_items()
                            if btn_name == "UP":
                                menu_selected_idx = (menu_selected_idx - 1) % len(items)
                            elif btn_name == "DOWN":
                                menu_selected_idx = (menu_selected_idx + 1) % len(items)
                            elif btn_name == ("CIRCLE" if cfg_circle_confirm else "CROSS"):
                                if 0 <= menu_selected_idx < len(items):
                                    execute_menu_action(items[menu_selected_idx]["id"])
                            elif btn_name == ("CROSS" if cfg_circle_confirm else "CIRCLE") or btn_name in ("OPTIONS", "SHARE"):
                                stream_menu_open = False
                            continue

                        target_name = None
                        if event.button == cfg_ps_btn or btn_name == "PS":
                            logger.info(f"⚡ Pulsación Joystick para Botón PS (botón {event.button}). Enviando press...")
                            target_name = "PS"
                        elif event.button in (cfg_touch_btn, 20, 16, 18, 15) or btn_name == "TOUCHPAD":
                            logger.info(f"📱 Pulsación Joystick para Touchpad (botón {event.button}). Manteniendo presionado...")
                            target_name = "TOUCHPAD"
                        elif btn_name:
                            target_name = remap_confirm_button(btn_name)

                        if target_name:
                            pressed_physical_buttons[event.button] = target_name
                            if target_name not in pressed_buttons:
                                pressed_buttons.add(target_name)
                                controller.button(target_name, action="press")

                            # Menú de transmisión por combo de mando: CAPTURE / SHARE + OPTIONS
                            if "SHARE" in pressed_buttons and "OPTIONS" in pressed_buttons:
                                logger.info("🎮 Combo Capture + Options detectado en joystick. Abriendo menú de transmisión...")
                                for b in ("SHARE", "OPTIONS"):
                                    try:
                                        controller.button(b, action="release")
                                    except Exception:
                                        pass
                                    pressed_buttons.discard(b)
                                pressed_physical_buttons.clear()
                                stream_menu_open = not stream_menu_open
                                if stream_menu_open:
                                    menu_selected_idx = 0
                                    mouse_visible = True
                                    pygame.mouse.set_visible(True)
                                continue

                    elif event.type == pygame.JOYBUTTONUP:
                        if (active_controllers and event.button not in (cfg_touch_btn, 20, 19, 18, 16, 15, cfg_ps_btn)) or stream_menu_open:
                            continue
                        btn_name = RAW_JOYSTICK_BUTTON_MAP.get(event.button)
                        target_name = None
                        if event.button == cfg_ps_btn or btn_name == "PS":
                            logger.info(f"⚡ Liberación Joystick para Botón PS (botón {event.button}). Liberando...")
                            target_name = "PS"
                        elif event.button in (cfg_touch_btn, 20, 16, 18, 15) or btn_name == "TOUCHPAD":
                            logger.info(f"📱 Liberación Joystick para Touchpad (botón {event.button}). Liberando...")
                            target_name = "TOUCHPAD"
                        elif btn_name:
                            target_name = remap_confirm_button(btn_name)

                        if target_name:
                            pressed_physical_buttons.pop(event.button, None)
                            if target_name not in pressed_physical_buttons.values():
                                pressed_buttons.discard(target_name)
                                controller.button(target_name, action="release")

                    elif event.type == pygame.JOYAXISMOTION:
                        if not active_controllers:
                            if stream_menu_open:
                                if getattr(event, "axis", -1) == 1:
                                    val = getattr(event, "value", 0.0)
                                    now = time.time()
                                    if val < -0.55 and (now - last_stick_nav_time > 0.22):
                                        menu_selected_idx = (menu_selected_idx - 1) % len(get_menu_items())
                                        last_stick_nav_time = now
                                    elif val > 0.55 and (now - last_stick_nav_time > 0.22):
                                        menu_selected_idx = (menu_selected_idx + 1) % len(get_menu_items())
                                        last_stick_nav_time = now
                                continue

                            val = max(-1.0, min(1.0, float(event.value)))
                            if event.axis == 0:
                                raw_stick_left[0] = val
                                push_stick_2d("left", raw_stick_left, stick_left)
                            elif event.axis == 1:
                                raw_stick_left[1] = val
                                push_stick_2d("left", raw_stick_left, stick_left)
                            elif event.axis == 2:
                                raw_stick_right[0] = val
                                push_stick_2d("right", raw_stick_right, stick_right)
                            elif event.axis == 3:
                                raw_stick_right[1] = val
                                push_stick_2d("right", raw_stick_right, stick_right)
                            elif event.axis in (4, 5):
                                is_down = (val > 0.30) if not (trigger_l2_pressed if event.axis == 4 else trigger_r2_pressed) else (val > 0.15)
                                if event.axis == 4 and is_down != trigger_l2_pressed:
                                    trigger_l2_pressed = is_down
                                    controller.button("L2", action="press" if is_down else "release")
                                elif event.axis == 5 and is_down != trigger_r2_pressed:
                                    trigger_r2_pressed = is_down
                                    controller.button("R2", action="press" if is_down else "release")

                    elif event.type == pygame.JOYHATMOTION:
                        if not active_controllers:
                            if stream_menu_open:
                                hat_x, hat_y = event.value
                                if hat_y == 1:
                                    menu_selected_idx = (menu_selected_idx - 1) % len(get_menu_items())
                                elif hat_y == -1:
                                    menu_selected_idx = (menu_selected_idx + 1) % len(get_menu_items())
                                continue

                            hat_x, hat_y = event.value
                            if hat_x == -1:
                                controller.button("LEFT", action="press")
                            elif hat_x == 1:
                                controller.button("RIGHT", action="press")
                            else:
                                controller.button("LEFT", action="release")
                                controller.button("RIGHT", action="release")

                            if hat_y == 1:
                                controller.button("UP", action="press")
                            elif hat_y == -1:
                                controller.button("DOWN", action="press")
                            else:
                                controller.button("UP", action="release")
                                controller.button("DOWN", action="release")

                    elif event.type == pygame.KEYDOWN:
                        mods = pygame.key.get_mods()
                        if stream_menu_open:
                            items = get_menu_items()
                            if event.key in (pygame.K_UP, pygame.K_w):
                                menu_selected_idx = (menu_selected_idx - 1) % len(items)
                            elif event.key in (pygame.K_DOWN, pygame.K_s):
                                menu_selected_idx = (menu_selected_idx + 1) % len(items)
                            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                                if 0 <= menu_selected_idx < len(items):
                                    execute_menu_action(items[menu_selected_idx]["id"])
                            elif event.key in (pygame.K_ESCAPE, pygame.K_F2, pygame.K_m):
                                stream_menu_open = False
                            elif event.key == pygame.K_F1:
                                show_hud = not show_hud
                                receiver._hud_cache_key = None
                            continue

                        if (event.key in (pygame.K_q, pygame.K_w) and (mods & pygame.KMOD_GUI)) or \
                           (event.key == pygame.K_c and (mods & pygame.KMOD_CTRL)):
                            logger.info("Cmd+Q / Cmd+W / Ctrl+C recibido. Saliendo de DRPS5...")
                            running = False
                            break

                        elif event.key in (pygame.K_F2, pygame.K_m):
                            stream_menu_open = not stream_menu_open
                            menu_selected_idx = 0
                            continue

                        elif event.key == pygame.K_F11 or (event.key == pygame.K_f and (mods & (pygame.KMOD_GUI | pygame.KMOD_META))):
                            # Alternar pantalla completa nativa de macOS (Spaces)
                            fullscreen = not fullscreen
                            if not toggle_macos_fullscreen():
                                try:
                                    pygame.display.toggle_fullscreen()
                                except Exception:
                                    pass
                            configure_cocoa_window()
                            # Solicitar un IDR keyframe limpio a la PS5
                            try:
                                if session and not session.is_stopped:
                                    session.stream.send_corrupt(0, 0)
                            except Exception:
                                pass

                        elif event.key == pygame.K_F1:
                            show_hud = not show_hud

                        elif event.key == pygame.K_ESCAPE:
                            if not session_state.get("connected") or session_state.get("error"):
                                logger.info("Escape recibido en pantalla de espera/error. Cancelando...")
                                running = False
                                break

                            is_shift = bool(mods & pygame.KMOD_SHIFT)
                            keys_pressed = pygame.key.get_pressed()
                            if keys_pressed[pygame.K_LSHIFT] or keys_pressed[pygame.K_RSHIFT]:
                                is_shift = True

                            now = time.time()
                            # Salida inmediata si presiona Shift+Esc O si presiona Escape 2 veces seguidas (<0.7s)
                            if is_shift or (now - last_esc_time < 0.7):
                                logger.info("Escape de salida recibido (Shift+Esc o doble Esc). Saliendo de la pantalla remota...")
                                running = False
                                break
                            else:
                                last_esc_time = now
                                logger.info("Tecla Escape pulsada (1 vez). Enviando botón PS a la PS5 (presiona Esc de nuevo para salir)...")
                                trigger_ps_pulse()

                        elif event.key == pygame.K_HOME:
                            trigger_ps_pulse()

                        # Mapeo de teclas a mando
                        if event.key in KEYBOARD_MAP:
                            btn_name = KEYBOARD_MAP[event.key]
                            controller.button(btn_name, action="press")

                        # Mapeo de WASD para stick izquierdo (solo si NO hay gamepad físico conectado)
                        if not active_controllers:
                            wasd_changed = False
                            if event.key == pygame.K_w:
                                stick_left[1] = -1.0
                                wasd_changed = True
                            elif event.key == pygame.K_s:
                                stick_left[1] = 1.0
                                wasd_changed = True
                            elif event.key == pygame.K_a:
                                stick_left[0] = -1.0
                                wasd_changed = True
                            elif event.key == pygame.K_d:
                                stick_left[0] = 1.0
                                wasd_changed = True
                            if wasd_changed:
                                controller.stick("left", point=tuple(stick_left))
                                controller.update_sticks()

                    elif event.type == pygame.KEYUP:
                        if event.key in KEYBOARD_MAP:
                            btn_name = KEYBOARD_MAP[event.key]
                            controller.button(btn_name, action="release")

                        if not active_controllers:
                            wasd_changed = False
                            if event.key in (pygame.K_w, pygame.K_s):
                                stick_left[1] = 0.0
                                wasd_changed = True
                            if event.key in (pygame.K_a, pygame.K_d):
                                stick_left[0] = 0.0
                                wasd_changed = True
                            if wasd_changed:
                                controller.stick("left", point=tuple(stick_left))
                                controller.update_sticks()

                except Exception as ev_err:
                    logger.debug(f"Error procesando evento de entrada: {ev_err}")

            # Verificar si la sesión terminó o tuvo error
            if session.is_stopped and not session_state.get("error"):
                session_state["error"] = session.disconnect_reason or session.error or "La sesión de PS5 ha finalizado o se ha cerrado."

            if session_state.get("error"):
                current_frame = None

            # Obtener el fotograma más reciente drenando la cola (cero latencia ni micro-tirones)
            new_frame = None
            while True:
                try:
                    new_frame = receiver.frame_queue.get_nowait()
                except queue.Empty:
                    break
            if new_frame is not None and not session_state.get("error"):
                current_frame = new_frame
                last_frame_recv_time = time.time()
                has_received_any_frame = True

            # Watchdog anti-congelamiento de vídeo: si la sesión está activa y no se reciben
            # nuevos fotogramas durante > 1.2s, solicitar inmediatamente un fotograma clave (IDR) a la PS5
            now_t = time.time()
            if has_received_any_frame and not session.is_stopped and not session_state.get("error"):
                if now_t - last_frame_recv_time > 1.2 and now_t - last_keyframe_request_time > 1.0:
                    last_keyframe_request_time = now_t
                    try:
                        v_st = getattr(getattr(session, "av", None), "_v_stream", None)
                        if v_st and getattr(v_st, "frame", -1) >= 0:
                            start = (getattr(v_st, "last_complete", -1) + 1) & 0xFFFF if getattr(v_st, "last_complete", -1) >= 0 else 1
                            end = max(start, v_st.frame) & 0xFFFF
                        else:
                            start, end = 1, 2
                        session.stream.send_corrupt(start, end)
                        logger.info(f"⚡ Watchdog de vídeo: fotogramas demorados > 1.2s, solicitando IDR keyframe a PS5 (frames {start} a {end})...")
                    except Exception:
                        pass

            # Polling continuo del ratón para asegurar visibilidad en Cocoa/macOS solo con movimiento intencional (>10px)
            curr_mouse_pos = pygame.mouse.get_pos()
            mouse_delta = max(abs(curr_mouse_pos[0] - last_mouse_pos[0]), abs(curr_mouse_pos[1] - last_mouse_pos[1]))
            if mouse_delta > 10:
                last_mouse_pos = curr_mouse_pos
                last_mouse_activity = time.time()
                if not mouse_visible:
                    pygame.mouse.set_visible(True)
                    mouse_visible = True
            elif mouse_delta > 0:
                last_mouse_pos = curr_mouse_pos

            # Renderizar en pantalla (escalado 100% en GPU Metal con cero copias CPU cuando SCALED está activo)
            screen_w, screen_h = screen.get_size()
            if screen_w <= 10 or screen_h <= 10:
                clock.tick(125)
                continue

            if current_frame is not None:
                fw, fh = current_frame.get_size()
                if fw > 0 and fh > 0:
                    if fw == screen_w and fh == screen_h:
                        screen.blit(current_frame, (0, 0))
                    elif use_gpu_scaled and not fullscreen:
                        # Ajustar una sola vez la superficie lógica de Metal al tamaño nativo del stream entrante
                        try:
                            from pygame._sdl2 import video as _sdl2_vid
                            _cur_win_sz = _sdl2_vid.Window.from_display_module().size
                            mode_size = (fw, fh)
                            screen = pygame.display.set_mode(mode_size, flags)
                            _sdl2_vid.Window.from_display_module().size = _cur_win_sz
                            configure_cocoa_window()
                            screen_w, screen_h = screen.get_size()
                            screen.blit(current_frame, (0, 0))
                        except Exception:
                            scaled_surf = pygame.transform.smoothscale(current_frame, (screen_w, screen_h))
                            screen.blit(scaled_surf, (0, 0))
                    else:
                        scale = min(screen_w / fw, screen_h / fh)
                        scaled_w = max(1, int(fw * scale))
                        scaled_h = max(1, int(fh * scale))
                        if scaled_w == fw and scaled_h == fh:
                            scaled_surf = current_frame
                        else:
                            scaled_surf = pygame.transform.smoothscale(current_frame, (scaled_w, scaled_h))
                        if scaled_w < screen_w or scaled_h < screen_h:
                            screen.fill((10, 14, 23))
                        screen.blit(scaled_surf, ((screen_w - scaled_w) // 2, (screen_h - scaled_h) // 2))
            else:
                # Pantalla de espera o error de conexión
                screen.fill((15, 23, 42))
                err = session_state.get("error")
                if err:
                    err_txt = font.render("Aviso de Conexión PS5:", True, (239, 68, 68))
                    screen.blit(err_txt, (screen_w // 2 - err_txt.get_width() // 2, screen_h // 2 - 40))
                    err_msg_str = str(err).strip()
                    if not err_msg_str or err_msg_str in ("''", '""'):
                        err_msg_str = "No se pudo establecer la sesión con la PS5. Verifica que la consola esté encendida y el PIN sea válido."
                    reason_txt = small_font.render(err_msg_str, True, (254, 202, 202))
                    screen.blit(reason_txt, (screen_w // 2 - reason_txt.get_width() // 2, screen_h // 2 - 10))
                    hint_txt = small_font.render("[Presiona Shift+Esc para volver al menú de DRPS5]", True, (148, 163, 184))
                    screen.blit(hint_txt, (screen_w // 2 - hint_txt.get_width() // 2, screen_h // 2 + 30))
                else:
                    curr_status = session_state.get("status_message", f"Conectando a PS5 ({host_ip})...")
                    loading_txt = font.render(curr_status, True, (240, 240, 255))
                    screen.blit(loading_txt, (screen_w // 2 - loading_txt.get_width() // 2, screen_h // 2 - 20))
                    hint_txt = small_font.render("[Presiona Esc o cierra la ventana para cancelar]", True, (148, 163, 184))
                    screen.blit(hint_txt, (screen_w // 2 - hint_txt.get_width() // 2, screen_h // 2 + 15))

            # HUD informativo cacheado (sólo se re-dibuja cuando cambia FPS/Mando/Audio/Estado, 0 allocs por frame)
            if show_hud:
                audio_dev_name = getattr(receiver, "_current_audio_device_name", "Predeterminado")[:34]
                hud_key = (receiver.fps_displayed, connected_controller_name, audio_dev_name, bool(session_state.get("error")), resolution_str, hdr, cas_strength)
                if getattr(receiver, "_hud_cache_key", None) != hud_key or getattr(receiver, "_hud_cache_surf", None) is None:
                    hud_surf = pygame.Surface((400, 92), pygame.SRCALPHA)
                    hud_surf.fill((15, 23, 42, 195))
                    hdr_badge = " | HDR" if hdr else (" | CAS" if cas_strength > 0 else "")
                    res_labels = {
                        "2160p": "4K GPU (2160P)",
                        "1440p": "2K GPU (1440P)",
                        "1080p": "1080P FULL HD",
                        "720p": "720P HD",
                        "540p": "540P",
                        "360p": "360P",
                    }
                    res_label_hud = res_labels.get(resolution_str, resolution_str.upper())
                    hud_status = "ERROR DE CONEXIÓN" if session_state.get("error") else f"{receiver.fps_displayed} FPS | {res_label_hud}{hdr_badge}"
                    fps_text = font.render(f"DRPS5 | {hud_status}", True, (56, 189, 248) if not session_state.get("error") else (239, 68, 68))
                    hud_surf.blit(fps_text, (10, 4))
                    is_gamepad = (connected_controller_name != "Teclado Activo")
                    ctrl_color = (52, 211, 153) if is_gamepad else (148, 163, 184)
                    hud_surf.blit(small_font.render(f"🎮 {connected_controller_name}", True, ctrl_color), (10, 24))
                    hud_surf.blit(small_font.render(f"🔊 {audio_dev_name}", True, (148, 163, 184)), (10, 42))
                    hud_surf.blit(small_font.render("Capture+Options: Menú | F1: HUD | F11: Pantalla completa", True, (203, 213, 225)), (10, 60))
                    receiver._hud_cache_key = hud_key
                    receiver._hud_cache_surf = hud_surf
                screen.blit(receiver._hud_cache_surf, (10, 10))

            # Botón translúcido de Menú en esquina superior derecha
            btn_w, btn_h = 96, 34
            btn_x = screen_w - btn_w - 16
            btn_y = 16
            btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

            in_proximity = (curr_mouse_pos[0] >= screen_w - 240 and curr_mouse_pos[1] <= 110)
            is_hover = btn_rect.collidepoint(curr_mouse_pos)

            if in_proximity or is_hover or show_hud:
                if not hasattr(receiver, "_exit_btn_surfs"):
                    s_norm = pygame.Surface((btn_w, btn_h), pygame.SRCALPHA)
                    pygame.draw.rect(s_norm, (15, 23, 42, 185), (0, 0, btn_w, btn_h), border_radius=8)
                    pygame.draw.rect(s_norm, (148, 163, 184, 160), (0, 0, btn_w, btn_h), width=1, border_radius=8)
                    tn = small_font.render("✕ Salir", True, (226, 232, 240))
                    s_norm.blit(tn, (btn_w // 2 - tn.get_width() // 2, btn_h // 2 - tn.get_height() // 2))

                    s_hov = pygame.Surface((btn_w, btn_h), pygame.SRCALPHA)
                    pygame.draw.rect(s_hov, (225, 29, 72, 225), (0, 0, btn_w, btn_h), border_radius=8)
                    pygame.draw.rect(s_hov, (251, 113, 133, 230), (0, 0, btn_w, btn_h), width=2, border_radius=8)
                    th_t = small_font.render("✕ Salir", True, (255, 255, 255))
                    s_hov.blit(th_t, (btn_w // 2 - th_t.get_width() // 2, btn_h // 2 - th_t.get_height() // 2))
                    receiver._exit_btn_surfs = (s_norm, s_hov)
                screen.blit(receiver._exit_btn_surfs[1 if is_hover else 0], (btn_x, btn_y))

            # Toast visual de conexión/desconexión de mando
            if toast_msg and time.time() < toast_expire_time:
                tw, th = 380, 36
                toast_surf = pygame.Surface((tw, th), pygame.SRCALPHA)
                toast_surf.fill((15, 23, 42, 225))
                is_warn = ("desconectado" in toast_msg or "⚠️" in toast_msg)
                border_color = (245, 158, 11) if is_warn else (52, 211, 153)
                pygame.draw.rect(toast_surf, border_color, (0, 0, tw, th), width=1, border_radius=8)
                t_txt = small_font.render(toast_msg, True, (254, 243, 199) if is_warn else (240, 253, 244))
                toast_surf.blit(t_txt, (tw // 2 - t_txt.get_width() // 2, th // 2 - t_txt.get_height() // 2))
                screen.blit(toast_surf, (screen_w // 2 - tw // 2, 20))

            # Renderizado del Menú de Transmisión Frosted (WebOS / Android V2 style)
            if stream_menu_open:
                mouse_visible = True
                pygame.mouse.set_visible(True)

                # 1. Overlay translúcido de fondo (dimming)
                overlay_surf = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
                overlay_surf.fill((5, 8, 17, 215))
                screen.blit(overlay_surf, (0, 0))

                # 2. Geometría de tarjeta adaptativa
                items = get_menu_items()
                card_w = min(540, screen_w - 40)
                item_h = 42 if screen_h >= 600 else 36
                item_gap = 7 if screen_h >= 600 else 5
                header_h = 88 if screen_h >= 600 else 76
                footer_h = 36
                card_h = header_h + len(items) * (item_h + item_gap) + footer_h
                card_x = (screen_w - card_w) // 2
                card_y = (screen_h - card_h) // 2
                menu_card_rect = pygame.Rect(card_x, card_y, card_w, card_h)

                # 3. Fondo y borde brillante de la tarjeta
                card_surf = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
                pygame.draw.rect(card_surf, (15, 23, 42, 248), (0, 0, card_w, card_h), border_radius=16)
                pygame.draw.rect(card_surf, (56, 189, 248, 140), (0, 0, card_w, card_h), width=2, border_radius=16)
                screen.blit(card_surf, (card_x, card_y))

                # 4. Título de cabecera
                title_surf = menu_title_font.render("MENÚ DE TRANSMISIÓN", True, (56, 189, 248))
                screen.blit(title_surf, (card_x + 22, card_y + 18))

                # 5. Chips informativos en vivo (Calidad y GPU)
                res_labels = {
                    "2160p": "4K GPU (2160P)",
                    "1440p": "2K GPU (1440P)",
                    "1080p": "1080P FULL HD",
                    "720p": "720P HD",
                    "540p": "540P",
                    "360p": "360P",
                }
                res_label_m = res_labels.get(resolution_str, resolution_str.upper())
                c1_str = f"{res_label_m} • {receiver.fps_displayed} FPS"
                c1_txt = small_font.render(c1_str, True, (226, 232, 240))
                c1_w, c1_h = c1_txt.get_width() + 16, 24
                c1_surf = pygame.Surface((c1_w, c1_h), pygame.SRCALPHA)
                pygame.draw.rect(c1_surf, (30, 41, 59, 220), (0, 0, c1_w, c1_h), border_radius=12)
                pygame.draw.rect(c1_surf, (71, 85, 105, 180), (0, 0, c1_w, c1_h), width=1, border_radius=12)
                c1_surf.blit(c1_txt, (8, (c1_h - c1_txt.get_height()) // 2))
                screen.blit(c1_surf, (card_x + 22, card_y + 48))

                c2_str = "Metal GPU • 0-Frame Slice"
                c2_txt = small_font.render(c2_str, True, (52, 211, 153))
                c2_w, c2_h = c2_txt.get_width() + 16, 24
                c2_surf = pygame.Surface((c2_w, c2_h), pygame.SRCALPHA)
                pygame.draw.rect(c2_surf, (6, 78, 59, 160), (0, 0, c2_w, c2_h), border_radius=12)
                pygame.draw.rect(c2_surf, (52, 211, 153, 140), (0, 0, c2_w, c2_h), width=1, border_radius=12)
                c2_surf.blit(c2_txt, (8, (c2_h - c2_txt.get_height()) // 2))
                screen.blit(c2_surf, (card_x + 26 + c1_w, card_y + 48))

                # 6. Opciones interactivas con foco y badges dinámicos
                menu_items_rects.clear()
                for idx, item in enumerate(items):
                    ix = card_x + 20
                    iy = card_y + header_h + idx * (item_h + item_gap)
                    iw = card_w - 40
                    ih = item_h
                    item_rect = pygame.Rect(ix, iy, iw, ih)
                    menu_items_rects.append((item_rect, item["id"]))

                    is_sel = (idx == menu_selected_idx)
                    is_danger = item.get("danger", False)

                    if is_sel:
                        if is_danger:
                            bg_col = (225, 29, 72, 240)
                            border_col = (255, 255, 255, 240)
                        else:
                            bg_col = (2, 132, 199, 240)
                            border_col = (56, 189, 248, 255)
                        text_col = (255, 255, 255)
                    else:
                        bg_col = (30, 41, 59, 190)
                        border_col = (51, 65, 85, 170)
                        text_col = (248, 113, 113) if is_danger else (226, 232, 240)

                    btn_surf = pygame.Surface((iw, ih), pygame.SRCALPHA)
                    pygame.draw.rect(btn_surf, bg_col, (0, 0, iw, ih), border_radius=10)
                    pygame.draw.rect(btn_surf, border_col, (0, 0, iw, ih), width=2 if is_sel else 1, border_radius=10)

                    label_surf = menu_item_font.render(f"{item['icon']}  {item['title']}", True, text_col)
                    btn_surf.blit(label_surf, (14, (ih - label_surf.get_height()) // 2))

                    if item.get("badge"):
                        badge_text = str(item["badge"])
                        is_active = (badge_text in ("Activado", "Completa", "Alto (100%)", "Medio (60%)", "Bajo (30%)"))
                        b_txt_col = (255, 255, 255) if is_sel else ((52, 211, 153) if is_active else (148, 163, 184))
                        b_surf = small_font.render(badge_text, True, b_txt_col)
                        bw, bh = b_surf.get_width() + 16, 24
                        bx, by = iw - bw - 12, (ih - bh) // 2
                        p_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
                        p_bg = (0, 0, 0, 90) if is_sel else ((16, 185, 129, 50) if is_active else (15, 23, 42, 160))
                        p_border = (255, 255, 255, 180) if is_sel else ((16, 185, 129, 130) if is_active else (71, 85, 105, 130))
                        pygame.draw.rect(p_surf, p_bg, (0, 0, bw, bh), border_radius=6)
                        pygame.draw.rect(p_surf, p_border, (0, 0, bw, bh), width=1, border_radius=6)
                        p_surf.blit(b_surf, (8, (bh - b_surf.get_height()) // 2))
                        btn_surf.blit(p_surf, (bx, by))

                    screen.blit(btn_surf, (ix, iy))

                # 7. Pie de navegación
                footer_str = "Mando: ↑↓ Mover • ✕ Seleccionar • ○ Volver  |  Teclado: Enter / Esc"
                footer_surf = small_font.render(footer_str, True, (148, 163, 184))
                screen.blit(footer_surf, (card_x + (card_w - footer_surf.get_width()) // 2, card_y + card_h - footer_h + 8))

            # Auto-ocultar cursor de ratón tras 2.5 segundos de inactividad sólo si está lejos del botón de salir y el menú no está abierto
            if not stream_menu_open and mouse_visible and not in_proximity and not is_hover and (time.time() - last_mouse_activity > 2.5):
                pygame.mouse.set_visible(False)
                mouse_visible = False

            # Watchdog de reconexión periódica de mandos si no hay ninguno activo
            now_time = time.time()
            if not active_controllers and not active_joysticks and (now_time - last_hotplug_check > 0.5):
                last_hotplug_check = now_time
                pygame.event.pump()
                if pygame.joystick.get_count() > 0 or sdl2_controller.get_count() > 0:
                    refresh_all_controllers(force=True)

            # Watchdog de sticks (radial 2D) y botones cada 50ms para evitar botones pegados o drift
            if (now_time - last_stick_watchdog > 0.050) and active_controllers:
                last_stick_watchdog = now_time
                try:
                    c_first = next(iter(active_controllers.values()))
                    if c_first and c_first.attached():
                        for b_code in list(pressed_physical_buttons.keys()):
                            b_name = pressed_physical_buttons.get(b_code)
                            # Preservar pulsaciones sostenidas de botones críticos (Touchpad para cinemáticas y PS para menús)
                            if b_name in ("TOUCHPAD", "PS"):
                                continue
                            try:
                                if hasattr(c_first, "get_button") and not c_first.get_button(b_code):
                                    b_name = pressed_physical_buttons.pop(b_code, None)
                                    if b_name and b_name not in pressed_physical_buttons.values():
                                        logger.info(f"⚡ Reconciliador de seguridad: {b_name} (botón físico {b_code}) liberado.")
                                        pressed_buttons.discard(b_name)
                                        controller.button(b_name, action="release")
                            except Exception:
                                pass

                        raw_stick_left[0] = c_first.get_axis(pygame.CONTROLLER_AXIS_LEFTX) / 32767.0
                        raw_stick_left[1] = c_first.get_axis(pygame.CONTROLLER_AXIS_LEFTY) / 32767.0
                        raw_stick_right[0] = c_first.get_axis(pygame.CONTROLLER_AXIS_RIGHTX) / 32767.0
                        raw_stick_right[1] = c_first.get_axis(pygame.CONTROLLER_AXIS_RIGHTY) / 32767.0

                        cur_lx, cur_ly = apply_radial_stick(raw_stick_left[0], raw_stick_left[1], stick_deadzone)
                        cur_rx, cur_ry = apply_radial_stick(raw_stick_right[0], raw_stick_right[1], stick_deadzone)

                        if cur_lx == 0.0 and cur_ly == 0.0:
                            if stick_left[0] != 0.0 or stick_left[1] != 0.0:
                                stick_left[0] = stick_left[1] = 0.0
                                controller.stick("left", point=(0.0, 0.0))
                                controller.update_sticks()
                        elif abs(cur_lx - stick_left[0]) > 0.02 or abs(cur_ly - stick_left[1]) > 0.02:
                            stick_left[0], stick_left[1] = cur_lx, cur_ly
                            controller.stick("left", point=(cur_lx, cur_ly))

                        if cur_rx == 0.0 and cur_ry == 0.0:
                            if stick_right[0] != 0.0 or stick_right[1] != 0.0:
                                stick_right[0] = stick_right[1] = 0.0
                                controller.stick("right", point=(0.0, 0.0))
                                controller.update_sticks()
                        elif abs(cur_rx - stick_right[0]) > 0.02 or abs(cur_ry - stick_right[1]) > 0.02:
                            stick_right[0], stick_right[1] = cur_rx, cur_ry
                            controller.stick("right", point=(cur_rx, cur_ry))
                except Exception:
                    pass

            # Detección y migración automática de salida de audio (auriculares / altavoces)
            if (now_time - last_audio_check > 0.8) or getattr(receiver, "_audio_device_changed", False):
                last_audio_check = now_time
                receiver.check_audio_device()

            try:
                pygame.display.flip()
            except pygame.error as flip_err:
                logger.warning(f"Aviso en pygame.display.flip (posible cambio de pantalla/lentes): {flip_err}")
                try:
                    screen = pygame.display.get_surface()
                    if screen is None or screen.get_width() <= 10 or screen.get_height() <= 10:
                        screen = pygame.display.set_mode(mode_size, flags)
                        configure_cocoa_window()
                except Exception:
                    pass
            # Ritmo de 125Hz sin colisionar con el VSync nativo de CAMetalLayer (60Hz / 120Hz ProMotion)
            clock.tick(125)

    except Exception as loop_err:
        logger.error(f"Error inesperado en bucle de streaming: {loop_err}", exc_info=True)
    finally:
        logger.info("Cerrando sesión de pantalla remota...")
        # 1. Asegurar visibilidad del ratón y cerrar display de Pygame de inmediato
        try:
            pygame.mouse.set_visible(True)
            pygame.display.quit()
            pygame.quit()
        except Exception:
            pass
        configure_cocoa_app_identity()

        # 2. Desconexión segura en segundo plano con timeout para no bloquear el hilo principal
        def _safe_cleanup():
            try:
                receiver.close()
            except Exception:
                pass
            try:
                controller.stop()
                controller.disconnect()
            except Exception:
                pass
            try:
                session.stop()
            except Exception:
                pass
            if session_loop and session_loop.is_running():
                try:
                    session_loop.call_soon_threadsafe(session_loop.stop)
                except Exception:
                    pass

        t = threading.Thread(target=_safe_cleanup, daemon=True)
        t.start()
        t.join(timeout=1.5)

        if sys.platform == "darwin" and app_nap_activity is not None:
            try:
                import AppKit
                AppKit.NSProcessInfo.processInfo().endActivity_(app_nap_activity)
                logger.debug("🛡️ macOS App Nap activity finalizada.")
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass

        logger.info("Sesión finalizada limpiamente.")

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    log_dir = Path.home() / ".drps5"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "stream.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    parser = argparse.ArgumentParser(description="DRPS5 Pantalla Remota PS5")
    parser.add_argument("--ip", dest="ip", default="", help="IP de la consola PS5")
    parser.add_argument("--regist-key", dest="regist_key", default="", help="RegistKey de vinculación")
    parser.add_argument("--rp-key", dest="rp_key", default="", help="RP-Key de emparejamiento")
    parser.add_argument("--mac", dest="mac", default="AA:BB:CC:DD:EE:FF", help="MAC / Host ID")
    parser.add_argument("--account-id", dest="account_id", default="AAAAAAAAAAAAAAAAAAAAAA==", help="PSN Account ID")
    parser.add_argument("--resolution", dest="resolution", default="1080p", choices=["360p", "540p", "720p", "1080p", "1440p", "2160p"], help="Resolución")
    parser.add_argument("--fps", dest="fps", type=int, default=60, choices=[30, 60], help="FPS")
    parser.add_argument("--codec", dest="codec", default="hevc", choices=["hevc", "h264"], help="Códec")
    parser.add_argument("--hdr", dest="hdr", action="store_true", default=False, help="Activar HDR de 10 bits (HEVC)")
    parser.add_argument("--audio", dest="audio", action="store_true", default=True, help="Audio habilitado")
    parser.add_argument("--no-audio", dest="audio", action="store_false", help="Audio deshabilitado")
    parser.add_argument("--fullscreen", dest="fullscreen", action="store_true", default=False, help="Pantalla completa")
    parser.add_argument("--hud", dest="hud", action="store_true", default=True, help="Mostrar superposición HUD")
    parser.add_argument("--no-hud", dest="hud", action="store_false", help="Ocultar superposición HUD")

    # Si se pasan argumentos posicionales antiguos
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        ip_arg = sys.argv[1]
        reg_key_arg = sys.argv[2] if len(sys.argv) > 2 else ""
        rp_key_arg = sys.argv[3] if len(sys.argv) > 3 else ""
        mac_arg = sys.argv[4] if len(sys.argv) > 4 else "AA:BB:CC:DD:EE:FF"
        acc_id_arg = sys.argv[5] if len(sys.argv) > 5 else "AAAAAAAAAAAAAAAAAAAAAA=="
        run_drps5_stream(
            host_ip=ip_arg,
            regist_key=reg_key_arg,
            rp_key=rp_key_arg,
            mac_address=mac_arg,
            account_id=acc_id_arg
        )
    else:
        args = parser.parse_args()
        if not args.ip or not args.rp_key:
            print("Error: Se requiere al menos --ip y --rp-key")
            sys.exit(1)
        run_drps5_stream(
            host_ip=args.ip,
            regist_key=args.regist_key,
            rp_key=args.rp_key,
            mac_address=args.mac,
            account_id=args.account_id,
            resolution_str=args.resolution,
            fps_val=args.fps,
            codec_str=args.codec,
            hdr=args.hdr,
            audio_enabled=args.audio,
            fullscreen=args.fullscreen,
            show_hud=args.hud
        )
