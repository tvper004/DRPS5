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
import threading
import queue
import logging
import asyncio
from typing import Optional

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
    """Receptor AV de ultra-baja latencia para la pantalla remota de la PS5 con cambio dinámico de audio."""

    def __init__(self, audio_enabled: bool = True):
        super().__init__()
        self.audio_enabled = audio_enabled
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
                raw_bytes = frame.planes[0]
                w, h = frame.width, frame.height
            else:
                img = frame.to_rgb()
                raw_bytes = img.planes[0]
                w, h = img.width, img.height

            self.frame_width = w
            self.frame_height = h

            surface = pygame.image.frombuffer(raw_bytes, (w, h), "RGB")

            # Descartar fotograma antiguo si la cola está llena para latencia ultra-baja
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self.frame_queue.put_nowait(surface)

            if not hasattr(self, "_logged_first_frame"):
                self._logged_first_frame = True
                logger.info(f"¡Primer fotograma de vídeo decodificado exitosamente! ({w}x{h})")

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
    console_type: str = "PS5"
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
            max_win_w = int(disp_info.current_w * 0.92)
            max_win_h = int(disp_info.current_h * 0.88)
            if target_w > max_win_w or target_h > max_win_h:
                scale = min(max_win_w / float(target_w), max_win_h / float(target_h))
                target_w = max(960, int(target_w * scale))
                target_h = max(540, int(target_h * scale))
    except Exception:
        pass
    flags = pygame.RESIZABLE
    mode_size = (target_w, target_h)

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

    receiver = DRPS5Receiver(audio_enabled=audio_enabled)

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
        hdr=hdr
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

    # Cargar mapeo de botones de mando personalizado o por defecto
    try:
        from drps5_config import DRPS5Config
        gp_map = DRPS5Config.get_gamepad_mapping()
        cfg_ps_btn = int(gp_map.get("ps_button", 5))
        cfg_touch_btn = int(gp_map.get("touchpad_button", 20))
        cfg_opt_btn = int(gp_map.get("options_button", 6))
        cfg_share_btn = int(gp_map.get("share_button", 4))
        cfg_deadzone = float(gp_map.get("stick_deadzone", 0.12))
        logger.info(f"Mapeo de mando activo: PS={cfg_ps_btn}, Touchpad={cfg_touch_btn}, Options={cfg_opt_btn}, Share={cfg_share_btn}, Deadzone={cfg_deadzone}")
    except Exception as e:
        logger.debug(f"Error cargando mapeo de mando: {e}")
        cfg_ps_btn = 5
        cfg_touch_btn = 20
        cfg_opt_btn = 6
        cfg_share_btn = 4
        cfg_deadzone = 0.12

    # Estado de sticks y filtros anti-saturación UDP con respuesta de ultra-baja latencia
    stick_left = [0.0, 0.0]
    stick_right = [0.0, 0.0]
    stick_deadzone = cfg_deadzone
    stick_min_delta = 0.008
    trigger_l2_pressed = False
    trigger_r2_pressed = False

    def apply_stick_filter(raw_val: float, deadzone: float = stick_deadzone) -> float:
        """Aplica zona muerta radial escalada para eliminar drift analógico sin saltos bruscos."""
        if abs(raw_val) <= deadzone:
            return 0.0
        sign = 1.0 if raw_val > 0 else -1.0
        scaled = sign * ((abs(raw_val) - deadzone) / (1.0 - deadzone))
        return max(-1.0, min(1.0, scaled))

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
                        if abs(m_dx) > 6 or abs(m_dy) > 6:
                            last_mouse_activity = time.time()
                            last_mouse_pos = event.pos
                            if not mouse_visible:
                                pygame.mouse.set_visible(True)
                                mouse_visible = True

                    elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                        last_mouse_activity = time.time()
                        last_mouse_pos = event.pos
                        if not mouse_visible:
                            pygame.mouse.set_visible(True)
                            mouse_visible = True

                        # Detección de clic en botón Cerrar translúcido en esquina superior derecha
                        screen_w, _ = screen.get_size()
                        btn_w, btn_h = 96, 34
                        btn_rect = pygame.Rect(screen_w - btn_w - 16, 16, btn_w, btn_h)
                        if event.button == 1 and btn_rect.collidepoint(event.pos):
                            logger.info("Botón Cerrar pulsado con el ratón. Saliendo de la pantalla remota...")
                            running = False
                            break

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
                            target_name = btn_name

                        if target_name:
                            pressed_physical_buttons[event.button] = target_name
                            if target_name not in pressed_buttons:
                                pressed_buttons.add(target_name)
                                controller.button(target_name, action="press")

                    elif event.type == pygame.CONTROLLERBUTTONUP:
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
                            target_name = btn_name

                        if target_name:
                            pressed_physical_buttons.pop(event.button, None)
                            if target_name not in pressed_physical_buttons.values():
                                pressed_buttons.discard(target_name)
                                controller.button(target_name, action="release")

                    # Ejes analógicos y gatillos de GameController (-32768 a 32767) con zona muerta radial escalada
                    elif event.type == pygame.CONTROLLERAXISMOTION:
                        val = max(-1.0, min(1.0, event.value / 32767.0))
                        axis = event.axis
                        if axis == pygame.CONTROLLER_AXIS_LEFTX:
                            filtered = apply_stick_filter(val, stick_deadzone)
                            if abs(filtered - stick_left[0]) >= stick_min_delta or (filtered == 0.0 and stick_left[0] != 0.0):
                                stick_left[0] = filtered
                                controller.stick("left", point=tuple(stick_left))
                                controller.update_sticks()
                        elif axis == pygame.CONTROLLER_AXIS_LEFTY:
                            filtered = apply_stick_filter(val, stick_deadzone)
                            if abs(filtered - stick_left[1]) >= stick_min_delta or (filtered == 0.0 and stick_left[1] != 0.0):
                                stick_left[1] = filtered
                                controller.stick("left", point=tuple(stick_left))
                                controller.update_sticks()
                        elif axis == pygame.CONTROLLER_AXIS_RIGHTX:
                            filtered = apply_stick_filter(val, stick_deadzone)
                            if abs(filtered - stick_right[0]) >= stick_min_delta or (filtered == 0.0 and stick_right[0] != 0.0):
                                stick_right[0] = filtered
                                controller.stick("right", point=tuple(stick_right))
                                controller.update_sticks()
                        elif axis == pygame.CONTROLLER_AXIS_RIGHTY:
                            filtered = apply_stick_filter(val, stick_deadzone)
                            if abs(filtered - stick_right[1]) >= stick_min_delta or (filtered == 0.0 and stick_right[1] != 0.0):
                                stick_right[1] = filtered
                                controller.stick("right", point=tuple(stick_right))
                                controller.update_sticks()
                        elif axis == pygame.CONTROLLER_AXIS_TRIGGERLEFT:
                            is_down = (event.value > 8000)
                            if is_down != trigger_l2_pressed:
                                trigger_l2_pressed = is_down
                                controller.button("L2", action="press" if is_down else "release")
                        elif axis == pygame.CONTROLLER_AXIS_TRIGGERRIGHT:
                            is_down = (event.value > 8000)
                            if is_down != trigger_r2_pressed:
                                trigger_r2_pressed = is_down
                                controller.button("R2", action="press" if is_down else "release")

                    # Soporte para Joysticks genéricos cuando no hay GameController activo
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if active_controllers:
                            continue
                        logger.info(f"🕹️ JOYBUTTONDOWN (Joystick Genérico): button={event.button}")
                        btn_name = RAW_JOYSTICK_BUTTON_MAP.get(event.button)
                        target_name = None
                        if event.button == cfg_ps_btn or btn_name == "PS":
                            logger.info(f"⚡ Pulsación Joystick para Botón PS (botón {event.button}). Enviando press...")
                            target_name = "PS"
                        elif event.button in (cfg_touch_btn, 20, 16, 18, 15) or btn_name == "TOUCHPAD":
                            logger.info(f"📱 Pulsación Joystick para Touchpad (botón {event.button}). Manteniendo presionado...")
                            target_name = "TOUCHPAD"
                        elif btn_name:
                            target_name = btn_name

                        if target_name:
                            pressed_physical_buttons[event.button] = target_name
                            if target_name not in pressed_buttons:
                                pressed_buttons.add(target_name)
                                controller.button(target_name, action="press")

                    elif event.type == pygame.JOYBUTTONUP:
                        if active_controllers:
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
                            target_name = btn_name

                        if target_name:
                            pressed_physical_buttons.pop(event.button, None)
                            if target_name not in pressed_physical_buttons.values():
                                pressed_buttons.discard(target_name)
                                controller.button(target_name, action="release")

                    elif event.type == pygame.JOYAXISMOTION:
                        if not active_controllers:
                            val = max(-1.0, min(1.0, float(event.value)))
                            if event.axis == 0:
                                filtered = apply_stick_filter(val, stick_deadzone)
                                if abs(filtered - stick_left[0]) >= stick_min_delta or (filtered == 0.0 and stick_left[0] != 0.0):
                                    stick_left[0] = filtered
                                    controller.stick("left", point=tuple(stick_left))
                                    controller.update_sticks()
                            elif event.axis == 1:
                                filtered = apply_stick_filter(val, stick_deadzone)
                                if abs(filtered - stick_left[1]) >= stick_min_delta or (filtered == 0.0 and stick_left[1] != 0.0):
                                    stick_left[1] = filtered
                                    controller.stick("left", point=tuple(stick_left))
                                    controller.update_sticks()
                            elif event.axis == 2:
                                filtered = apply_stick_filter(val, stick_deadzone)
                                if abs(filtered - stick_right[0]) >= stick_min_delta or (filtered == 0.0 and stick_right[0] != 0.0):
                                    stick_right[0] = filtered
                                    controller.stick("right", point=tuple(stick_right))
                                    controller.update_sticks()
                            elif event.axis == 3:
                                filtered = apply_stick_filter(val, stick_deadzone)
                                if abs(filtered - stick_right[1]) >= stick_min_delta or (filtered == 0.0 and stick_right[1] != 0.0):
                                    stick_right[1] = filtered
                                    controller.stick("right", point=tuple(stick_right))
                                    controller.update_sticks()
                            elif event.axis in (4, 5):
                                is_down = (val > 0.3)
                                if event.axis == 4 and is_down != trigger_l2_pressed:
                                    trigger_l2_pressed = is_down
                                    controller.button("L2", action="press" if is_down else "release")
                                elif event.axis == 5 and is_down != trigger_r2_pressed:
                                    trigger_r2_pressed = is_down
                                    controller.button("R2", action="press" if is_down else "release")

                    elif event.type == pygame.JOYHATMOTION:
                        if not active_controllers:
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
                        if (event.key in (pygame.K_q, pygame.K_w) and (mods & pygame.KMOD_GUI)) or \
                           (event.key == pygame.K_c and (mods & pygame.KMOD_CTRL)):
                            logger.info("Cmd+Q / Cmd+W / Ctrl+C recibido. Saliendo de DRPS5...")
                            running = False
                            break

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

            # Renderizar en pantalla
            screen_w, screen_h = screen.get_size()
            if screen_w <= 10 or screen_h <= 10:
                clock.tick(fps_val + 5)
                continue

            if current_frame is not None:
                fw, fh = current_frame.get_size()
                if fw > 0 and fh > 0:
                    if fw == screen_w and fh == screen_h:
                        screen.blit(current_frame, (0, 0))
                    else:
                        scale = min(screen_w / fw, screen_h / fh)
                        scaled_w = max(1, int(fw * scale))
                        scaled_h = max(1, int(fh * scale))
                        if scaled_w == fw and scaled_h == fh:
                            scaled_surf = current_frame
                        else:
                            scaled_surf = pygame.transform.scale(current_frame, (scaled_w, scaled_h))

                        if scaled_w < screen_w or scaled_h < screen_h:
                            screen.fill((10, 14, 23))  # Fondo oscuro solo si hay franjas
                        pos_x = (screen_w - scaled_w) // 2
                        pos_y = (screen_h - scaled_h) // 2
                        screen.blit(scaled_surf, (pos_x, pos_y))
            else:
                # Pantalla de espera o error de conexión
                screen.fill((15, 23, 42))
                err = session_state.get("error")
                if err:
                    err_txt = font.render("Aviso de Conexión PS5:", True, (239, 68, 68))
                    screen.blit(err_txt, (screen_w // 2 - err_txt.get_width() // 2, screen_h // 2 - 40))
                    
                    err_msg_str = str(err).strip()
                    if not err_msg_str or err_msg_str == "''" or err_msg_str == '""':
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

            # HUD informativo en esquina superior
            if show_hud:
                hud_bg = pygame.Surface((380, 92), pygame.SRCALPHA)
                hud_bg.fill((15, 23, 42, 195))
                screen.blit(hud_bg, (10, 10))

                hdr_badge = " | HDR" if hdr else ""
                res_labels = {
                    "2160p": "4K ULTRA HD (3840x2160)",
                    "1440p": "2K QHD (2560x1440)",
                    "1080p": "1080P FULL HD",
                    "720p": "720P HD",
                    "540p": "540P",
                    "360p": "360P",
                }
                res_label_hud = res_labels.get(resolution_str, resolution_str.upper())
                hud_status = f"{receiver.fps_displayed} FPS | {res_label_hud}{hdr_badge}"
                if session_state.get("error"):
                    hud_status = "ERROR DE CONEXIÓN"
                fps_text = font.render(f"DRPS5 | {hud_status}", True, (56, 189, 248) if not session_state.get("error") else (239, 68, 68))
                screen.blit(fps_text, (20, 14))

                is_gamepad = (connected_controller_name != "Teclado Activo")
                ctrl_color = (52, 211, 153) if is_gamepad else (148, 163, 184)
                ctrl_text = small_font.render(f"🎮 {connected_controller_name}", True, ctrl_color)
                screen.blit(ctrl_text, (20, 34))

                audio_dev_name = getattr(receiver, "_current_audio_device_name", "Predeterminado")
                audio_text = small_font.render(f"🔊 {audio_dev_name[:34]}", True, (148, 163, 184))
                screen.blit(audio_text, (20, 52))

                help_text = small_font.render("F11: Pantalla completa | F1: HUD | Shift+Esc: Salir", True, (203, 213, 225))
                screen.blit(help_text, (20, 70))

            # Botón translúcido de Salir en esquina superior derecha (aparece por proximidad del ratón o con HUD)
            btn_w, btn_h = 96, 34
            btn_x = screen_w - btn_w - 16
            btn_y = 16
            btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

            in_proximity = (curr_mouse_pos[0] >= screen_w - 240 and curr_mouse_pos[1] <= 110)
            is_hover = btn_rect.collidepoint(curr_mouse_pos)

            if in_proximity or is_hover or show_hud:
                btn_surface = pygame.Surface((btn_w, btn_h), pygame.SRCALPHA)
                if is_hover:
                    pygame.draw.rect(btn_surface, (225, 29, 72, 225), (0, 0, btn_w, btn_h), border_radius=8)
                    pygame.draw.rect(btn_surface, (255, 255, 255, 230), (0, 0, btn_w, btn_h), width=2, border_radius=8)
                    btn_txt = small_font.render("✕ Salir", True, (255, 255, 255))
                else:
                    pygame.draw.rect(btn_surface, (15, 23, 42, 185), (0, 0, btn_w, btn_h), border_radius=8)
                    pygame.draw.rect(btn_surface, (148, 163, 184, 160), (0, 0, btn_w, btn_h), width=1, border_radius=8)
                    btn_txt = small_font.render("✕ Salir", True, (226, 232, 240))

                btn_surface.blit(btn_txt, (btn_w // 2 - btn_txt.get_width() // 2, btn_h // 2 - btn_txt.get_height() // 2))
                screen.blit(btn_surface, (btn_x, btn_y))

            # Toast visual de conexión/desconexión de mando (visible 3.5 segundos con estilo elegante)
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

            # Auto-ocultar cursor de ratón tras 2.5 segundos de inactividad sólo si está lejos del botón de salir
            if mouse_visible and not in_proximity and not is_hover and (time.time() - last_mouse_activity > 2.5):
                pygame.mouse.set_visible(False)
                mouse_visible = False

            # Watchdog de reconexión periódica de mandos si no hay ninguno activo (hotplug background polling cada 0.5s)
            now_time = time.time()
            if not active_controllers and not active_joysticks and (now_time - last_hotplug_check > 0.5):
                last_hotplug_check = now_time
                pygame.event.pump()
                if pygame.joystick.get_count() > 0 or sdl2_controller.get_count() > 0:
                    refresh_all_controllers(force=True)

            # Watchdog de sticks y botones para reconciliar posición física y evitar botones pegados o drift
            if (now_time - last_stick_watchdog > 0.050) and active_controllers:
                last_stick_watchdog = now_time
                try:
                    c_first = next(iter(active_controllers.values()))
                    if c_first and c_first.attached():
                        # 1. Reconciliador de seguridad para botones / D-Pad: asegurar que ningún botón quede
                        # registrado como presionado si físicamente ya fue soltado en el mando
                        for b_code in list(pressed_physical_buttons.keys()):
                            try:
                                if hasattr(c_first, "get_button") and not c_first.get_button(b_code):
                                    b_name = pressed_physical_buttons.pop(b_code, None)
                                    if b_name and b_name not in pressed_physical_buttons.values():
                                        logger.info(f"⚡ Reconciliador de seguridad: {b_name} (botón físico {b_code}) liberado. Sincronizando con PS5...")
                                        pressed_buttons.discard(b_name)
                                        controller.button(b_name, action="release")
                            except Exception:
                                pass

                        # 2. Reconciliación independiente de cada eje de stick analógico
                        cur_lx = apply_stick_filter(c_first.get_axis(pygame.CONTROLLER_AXIS_LEFTX) / 32767.0, stick_deadzone)
                        cur_ly = apply_stick_filter(c_first.get_axis(pygame.CONTROLLER_AXIS_LEFTY) / 32767.0, stick_deadzone)
                        cur_rx = apply_stick_filter(c_first.get_axis(pygame.CONTROLLER_AXIS_RIGHTX) / 32767.0, stick_deadzone)
                        cur_ry = apply_stick_filter(c_first.get_axis(pygame.CONTROLLER_AXIS_RIGHTY) / 32767.0, stick_deadzone)

                        # En reposo/centro (0, 0), forzar neutralización garantizada de inmediato
                        if cur_lx == 0.0 and cur_ly == 0.0:
                            if stick_left[0] != 0.0 or stick_left[1] != 0.0:
                                stick_left[0] = 0.0
                                stick_left[1] = 0.0
                                controller.stick("left", point=(0.0, 0.0))
                                controller.update_sticks()
                        else:
                            changed_l = False
                            if abs(cur_lx - stick_left[0]) > 0.02:
                                stick_left[0] = cur_lx
                                changed_l = True
                            if abs(cur_ly - stick_left[1]) > 0.02:
                                stick_left[1] = cur_ly
                                changed_l = True
                            if changed_l:
                                controller.stick("left", point=tuple(stick_left))
                                controller.update_sticks()

                        # En reposo/centro (0, 0), forzar neutralización garantizada de inmediato
                        if cur_rx == 0.0 and cur_ry == 0.0:
                            if stick_right[0] != 0.0 or stick_right[1] != 0.0:
                                stick_right[0] = 0.0
                                stick_right[1] = 0.0
                                controller.stick("right", point=(0.0, 0.0))
                                controller.update_sticks()
                        else:
                            changed_r = False
                            if abs(cur_rx - stick_right[0]) > 0.02:
                                stick_right[0] = cur_rx
                                changed_r = True
                            if abs(cur_ry - stick_right[1]) > 0.02:
                                stick_right[1] = cur_ry
                                changed_r = True
                            if changed_r:
                                controller.stick("right", point=tuple(stick_right))
                                controller.update_sticks()
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
                        screen = pygame.display.set_mode((target_w, target_h), flags)
                        configure_cocoa_window()
                except Exception:
                    pass
            clock.tick(fps_val + 5)

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
