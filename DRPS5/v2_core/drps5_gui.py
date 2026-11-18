#!/usr/bin/env python3
"""
DRPS5 - Interfaz Gráfica de Usuario (GUI)
Aplicación moderna y elegante para el control y visualización de Pantalla Remota de PS5.
Soporte completo de múltiples perfiles, IPs locales, IPs públicas/remotas, emparejamiento por PIN y streaming nativo.
Sin inicio de sesión en PSN ni restricciones de licencia.
Arquitectura nativa WKWebView (pywebview) con soporte de Metal y aceleración gráfica.
"""

import sys
import os

# Identidad estricta de proceso macOS
if sys.platform == "darwin":
    try:
        import Foundation
        Foundation.NSProcessInfo.processInfo().setProcessName_("DRPS5")
    except Exception:
        pass

import asyncio
import threading
import subprocess
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import webview

from drps5_config import DRPS5Config, create_empty_profile
from drps5_core import discover_ps5, wakeup_ps5, pair_ps5, clean_ip_target

def purge_old_logs_files(days: int = 30) -> dict:
    """Elimina archivos .log y líneas de registro con antigüedad mayor a `days` días."""
    removed_files = 0
    removed_lines = 0
    cutoff_dt = datetime.now() - timedelta(days=days)
    cutoff_ts = time.time() - (days * 86400)
    try:
        log_dir = Path.home() / ".drps5"
        if not log_dir.exists():
            return {"removed_files": 0, "removed_lines": 0}
        for log_file in log_dir.glob("*.log*"):
            try:
                if not log_file.is_file():
                    continue
                # Si el archivo completo no se ha modificado en > days días y no es el log activo principal
                if log_file.stat().st_mtime < cutoff_ts and log_file.name not in ("launcher.log", "stream.log"):
                    log_file.unlink()
                    removed_files += 1
                    continue
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                kept = []
                keep_continuation = True
                for line in lines:
                    if len(line) >= 19 and line[4:5] == "-" and line[7:8] == "-" and line[10:11] == " ":
                        try:
                            line_dt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                            if line_dt < cutoff_dt:
                                removed_lines += 1
                                keep_continuation = False
                                continue
                            else:
                                keep_continuation = True
                        except ValueError:
                            pass
                    if keep_continuation:
                        kept.append(line)
                    else:
                        removed_lines += 1
                if len(kept) != len(lines):
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.writelines(kept)
            except Exception:
                pass
    except Exception:
        pass
    return {"removed_files": removed_files, "removed_lines": removed_lines}

# Asegurar persistencia de logs en ~/.drps5/ y autolimpieza >30 días
try:
    log_dir = Path.home() / ".drps5"
    log_dir.mkdir(parents=True, exist_ok=True)
    purge_old_logs_files(30)
    _root_log = logging.getLogger()
    _root_log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("launcher.log") for h in _root_log.handlers):
        _fh = logging.FileHandler(log_dir / "launcher.log", encoding="utf-8")
        _fh.setFormatter(_fmt)
        _root_log.addHandler(_fh)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in _root_log.handlers):
        _sh = logging.StreamHandler(sys.stdout)
        _sh.setFormatter(_fmt)
        _root_log.addHandler(_sh)
except Exception:
    logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("drps5_gui")

# Evitar puertos privilegiados (<1024) en el servidor HTTP local de pywebview
try:
    import random as _rnd
    import socket as _wvsock
    import webview.http as _wvhttp

    def _safe_random_port() -> int:
        for _ in range(64):
            port = _rnd.randint(18000, 60000)
            with _wvsock.socket(_wvsock.AF_INET, _wvsock.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        return 28955

    _wvhttp._get_random_port = _safe_random_port
except Exception:
    pass

class DRPS5Api:
    def __init__(self):
        self._config_data = DRPS5Config.load()
        self._window = None
        self._stream_process = None
        self._pending_stream = None

    def _set_window(self, window):
        self._window = window

    def get_initial_data(self):
        self._config_data = DRPS5Config.load()
        profiles = DRPS5Config.get_profiles()
        active_p = DRPS5Config.get_active_profile()
        return {
            "config": self._config_data,
            "profiles": profiles,
            "active_profile": active_p,
            "active_profile_id": self._config_data.get("active_profile_id", active_p.get("id")),
            "consoles": self._config_data.get("consoles", {}),
            "last_used_ip": active_p.get("local_ip", "")
        }

    def get_system_info(self):
        import platform
        mach = platform.machine().lower()
        edition = "Personal" if os.environ.get("DRPS5_EDITION", "personal").lower() == "personal" else "Publica"
        if sys.platform == "darwin":
            arch_label = "Apple Silicon (M)" if ("arm" in mach or "aarch64" in mach) else "Intel (x86_64)"
            gpu_label = "Metal / VideoToolbox"
            hwaccel = "VideoToolbox"
        elif sys.platform == "win32":
            proc_id = (os.environ.get("PROCESSOR_IDENTIFIER", "") + " " + os.environ.get("PROCESSOR_ARCHITEW6432", "")).lower()
            is_arm = "arm" in mach or "aarch64" in mach or "arm" in proc_id or "qualcomm" in proc_id or "snapdragon" in proc_id
            arch_label = "Windows ARM64" if is_arm else "Windows x86_64"
            gpu_label = "Direct3D 11 / GPU"
            hwaccel = "D3D11VA"
        else:
            arch_label = mach
            gpu_label = "OpenGL"
            hwaccel = "Auto"
        return {
            "os": sys.platform,
            "arch": arch_label,
            "gpu": gpu_label,
            "hwaccel": hwaccel,
            "edition": edition
        }

    def start_psn_oauth(self):
        try:
            import urllib.parse
            import urllib.request
            import json as _json
            import base64
            import struct
            import webbrowser
            # For desktop: open PSN login URL or return guidance if manual code needed
            auth_url = (
                "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
                "?access_type=offline"
                "&client_id=09515159-7237-4370-9b40-3806e67c0891"
                "&redirect_uri=com.playstation.remoteplay://redirect"
                "&response_type=code"
                "&scope=psn:clientapp%20user:account.get%20kamaji:get_account_hash%20oauth:manage_user_auth_sessions"
            )
            webbrowser.open(auth_url)
            return {"success": False, "error": "Inicia sesion en el navegador y pega tu Account ID en Editar Consola si es necesario."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Gestión de Perfiles (Múltiples PS5, IP Local e IP Pública)
    # -------------------------------------------------------------------------
    def get_profiles(self):
        return {
            "success": True,
            "profiles": DRPS5Config.get_profiles(),
            "active_profile_id": DRPS5Config.load().get("active_profile_id")
        }

    def save_profile(self, profile_data):
        try:
            saved = DRPS5Config.save_profile(profile_data)
            self._config_data = DRPS5Config.load()
            return {"success": True, "profile": saved}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_profile(self, profile_id):
        try:
            ok = DRPS5Config.delete_profile(profile_id)
            self._config_data = DRPS5Config.load()
            active_p = DRPS5Config.get_active_profile()
            return {
                "success": ok,
                "profiles": DRPS5Config.get_profiles(),
                "active_profile": active_p
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def select_profile(self, profile_id):
        p = DRPS5Config.set_active_profile(profile_id)
        if p:
            self._config_data = DRPS5Config.load()
            return {"success": True, "profile": p}
        return {"success": False, "error": "Perfil no encontrado"}

    def set_profile_mode(self, profile_id, mode):
        ok = DRPS5Config.set_connection_mode(profile_id, mode)
        self._config_data = DRPS5Config.load()
        return {"success": ok}

    def update_profile_remote_ip(self, profile_id, remote_ip):
        try:
            p = DRPS5Config.get_profile(profile_id) if profile_id else DRPS5Config.get_active_profile()
            if not p:
                return {"success": False, "error": "Perfil no encontrado"}
            p["remote_ip"] = clean_ip_target(remote_ip)
            saved = DRPS5Config.save_profile(p)
            self._config_data = DRPS5Config.load()
            return {"success": True, "profile": saved}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Acciones de Red y Consola
    # -------------------------------------------------------------------------
    def discover_consoles(self, timeout=3):
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(discover_ps5(timeout=timeout))
            return {"success": True, "consoles": results}
        except Exception as e:
            logger.error(f"Error en discover: {e}")
            return {"success": False, "error": str(e), "consoles": []}
        finally:
            loop.close()

    def wakeup_console(self, ip=None, profile_id=None):
        reg_key = ""
        target_ip = ip
        console_type = "PS5"

        if profile_id:
            p = DRPS5Config.get_profile(profile_id)
            if p:
                conn_mode = p.get("connection_mode", "local")
                target_ip = p.get("remote_ip") if conn_mode == "remote" else p.get("local_ip")
                reg_key = p.get("regist_key", "")
                console_type = p.get("console_type") or p.get("host_type") or "PS5"
        elif not target_ip:
            p = DRPS5Config.get_active_profile()
            if p:
                conn_mode = p.get("connection_mode", "local")
                target_ip = p.get("remote_ip") if conn_mode == "remote" else p.get("local_ip")
                reg_key = p.get("regist_key", "")
                console_type = p.get("console_type") or p.get("host_type") or "PS5"

        if not target_ip:
            return {"success": False, "error": "No hay IP especificada."}

        console = DRPS5Config.get_console(target_ip)
        if not reg_key and console:
            reg_key = console.get("regist_key", "")
            if not console_type or console_type == "PS5":
                console_type = console.get("host_type") or console.get("console_type") or "PS5"

        ok = wakeup_ps5(target_ip, reg_key, console_type=console_type)
        return {"success": ok, "ip": target_ip}

    # Alias para compatibilidad con llamadas frontend
    wakeup_ps5 = wakeup_console

    def pair_console(self, ip, pin, account_id="", profile_id=None, console_type="PS5"):
        loop = asyncio.new_event_loop()
        try:
            target_type = str(console_type or "PS5").upper()
            res = loop.run_until_complete(pair_ps5(ip, pin, account_id, target_type))
            if res and "rp_key" in res:
                host_id = res.get("host_id", ip)
                host_name = res.get("host_name", f"{target_type} Vinculada")
                reg_key = res.get("regist_key", "")
                rp_key = res.get("rp_key", "")
                acc = res.get("account_id", account_id)
                ctype = res.get("console_type", target_type)

                # Obtener o crear perfil a actualizar
                p = DRPS5Config.get_profile(profile_id) if profile_id else DRPS5Config.get_active_profile()
                if not p:
                    p = create_empty_profile(name=host_name, local_ip=ip)
                
                p["local_ip"] = ip
                p["host_id"] = host_id
                p["host_name"] = host_name
                p["regist_key"] = reg_key
                p["rp_key"] = rp_key
                p["account_id"] = acc
                p["status"] = "Vinculada"
                p["console_type"] = ctype

                saved = DRPS5Config.save_profile(p)
                self._config_data = DRPS5Config.load()
                return {"success": True, "profile": saved, "console": saved}
            else:
                reason = res.get("error_reason") if isinstance(res, dict) else None
                if reason == "80108b09":
                    err_msg = "El código PIN de 8 dígitos es incorrecto o ha caducado en la consola."
                elif reason == "80108bff":
                    err_msg = f"La consola ({target_type}) rechazó la solicitud (0x80108bff). Asegúrate de que el código PIN siga visible en tu TV o genera uno nuevo en Ajustes de Uso a distancia."
                elif reason == "80108b02":
                    err_msg = "El Account ID de PlayStation Network no coincide con el perfil activo en la consola."
                else:
                    err_msg = f"No se pudo vincular con la {target_type}. Verifica que la pantalla 'Vincular dispositivo' siga abierta en tu consola con un PIN vigente."
                return {"success": False, "error": err_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            loop.close()

    def save_settings(self, settings):
        try:
            cfg = DRPS5Config.load()
            for k, v in settings.items():
                if k not in ("profiles", "consoles"):
                    cfg[k] = v
            active_id = cfg.get("active_profile_id")
            if active_id and active_id in cfg.get("profiles", {}):
                active_p = cfg["profiles"][active_id]
                for k in ("resolution", "fps", "codec", "hdr"):
                    if k in settings:
                        active_p[k] = settings[k]
            DRPS5Config.save(cfg)
            self._config_data = cfg
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Calibración y Mapeo de Mandos (Backbone One / DualSense / etc.)
    # -------------------------------------------------------------------------
    def get_gamepad_mapping(self):
        try:
            return {"success": True, "mapping": DRPS5Config.get_gamepad_mapping()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_gamepad_mapping(self, mapping):
        try:
            saved = DRPS5Config.save_gamepad_mapping(mapping)
            self._config_data = DRPS5Config.load()
            return {"success": True, "mapping": saved}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_connected_controllers(self):
        """Verifica en tiempo real mandos USB y Bluetooth conectados (GameController + IOKit HID)."""
        if sys.platform == "darwin":
            c_list = []
            seen_names = set()
            try:
                import objc
                if "GCController" not in globals():
                    objc.loadBundle('GameController', globals(), bundle_path='/System/Library/Frameworks/GameController.framework')
                try:
                    GCController.setShouldMonitorBackgroundEvents_(True)
                except Exception:
                    pass
                controllers = GCController.controllers() or []
                for i, c in enumerate(controllers):
                    name = str(c.vendorName() or "Mando Compatible").strip()
                    if name and name not in seen_names:
                        seen_names.add(name)
                        c_list.append({"index": i, "name": name, "is_controller": True})
            except Exception:
                pass

            if not c_list:
                try:
                    out = subprocess.check_output(
                        ["ioreg", "-r", "-c", "IOHIDDevice", "-d", "2"],
                        text=True, timeout=0.8, stderr=subprocess.DEVNULL
                    )
                    ignore_words = ("keyboard", "teclado", "mouse", "ratón", "trackpad", "headset", "audio", "video", "btm", "wakehint")
                    known_vids = ("= 1356\n", "= 1118\n", "= 1406\n", "= 13866\n", "= 10462\n")  # Sony, MS, Nintendo, Backbone, 8BitDo
                    for blk in out.split("+-o "):
                        has_gamepad_usage = ('"PrimaryUsagePage" = 1\n' in blk and ('"PrimaryUsage" = 5\n' in blk or '"PrimaryUsage" = 4\n' in blk))
                        has_known_vid = any(v in blk for v in known_vids)
                        has_pad_kw = any(k in blk for k in ("DualSense", "DualShock", "Wireless Controller", "Xbox", "Backbone", "Gamepad", "Pro Controller"))
                        if not (has_gamepad_usage or has_known_vid or has_pad_kw):
                            continue
                        prod_name = None
                        for line in blk.splitlines():
                            if '"Product" =' in line:
                                prod_name = line.split('"Product" =', 1)[1].strip().strip('"')
                                break
                        if not prod_name and '"VendorID" = 1356\n' in blk:
                            prod_name = "DualSense Wireless Controller"
                        if prod_name:
                            low = prod_name.lower()
                            if not any(w in low for w in ignore_words) and prod_name not in seen_names:
                                seen_names.add(prod_name)
                                c_list.append({"index": len(c_list), "name": prod_name, "is_controller": True})
                except Exception:
                    pass

            first_name = c_list[0]["name"] if c_list else None
            return {
                "success": True,
                "connected": len(c_list) > 0,
                "count": len(c_list),
                "name": first_name or "Ningún mando detectado",
                "controllers": c_list
            }
        elif sys.platform == "win32":
            try:
                import ctypes
                for dll in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
                    try:
                        xi = ctypes.windll.LoadLibrary(dll)
                        class XINPUT_STATE(ctypes.Structure):
                            _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", ctypes.c_byte * 12)]
                        st = XINPUT_STATE()
                        for idx in range(4):
                            if xi.XInputGetState(idx, ctypes.byref(st)) == 0:
                                return {
                                    "success": True,
                                    "connected": True,
                                    "count": 1,
                                    "name": "Mando Xbox / DualSense (XInput)",
                                    "controllers": [{"index": idx, "name": "Mando XInput", "is_controller": True}]
                                }
                        return {"success": True, "connected": False, "count": 0, "name": "Ningún mando detectado", "controllers": []}
                    except Exception:
                        continue
            except Exception:
                pass
            return {"success": True, "connected": False, "count": 0, "name": "Ningún mando detectado", "controllers": []}
        return {"success": True, "connected": False, "count": 0, "name": "Ningún mando detectado", "controllers": []}

    def open_game_controller_settings(self):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "settings-navigation://com.apple.Settings.GameControllers/?path=shortcuts"], check=False)
            elif sys.platform == "win32":
                subprocess.Popen(["control", "joy.cpl"], shell=True)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Lanzar Streaming de Pantalla Remota
    # -------------------------------------------------------------------------
    def launch_stream(self, target_identifier=None, custom_settings=None):
        # Determinar perfil objetivo
        profile = None
        if target_identifier and target_identifier in self._config_data.get("profiles", {}):
            profile = self._config_data["profiles"][target_identifier]
        else:
            profile = DRPS5Config.get_active_profile()

        # Determinar IP objetivo según el modo activo (Auto vs Local vs Remoto)
        conn_mode = (custom_settings or {}).get("connection_mode") or profile.get("connection_mode", "auto")
        local_ip = clean_ip_target(profile.get("local_ip") or "")
        remote_ip = clean_ip_target(profile.get("remote_ip") or "")

        if conn_mode == "remote":
            if not remote_ip:
                return {
                    "success": False,
                    "error": "missing_remote_ip",
                    "message": "Falta configurar la IP Remota / Tailscale."
                }
            connect_ip = remote_ip
        elif conn_mode == "local":
            if not local_ip:
                return {
                    "success": False,
                    "error": "missing_local_ip",
                    "message": "Por favor introduce la IP Local de tu PS5 antes de conectar."
                }
            connect_ip = local_ip
        else:
            # Modo Auto: probar TCP 9295 local rápido (1.1s), si no responde usar IP Remota
            connect_ip = local_ip or remote_ip
            if local_ip and remote_ip:
                import socket as _sock
                try:
                    with _sock.create_connection((local_ip, 9295), timeout=1.1):
                        connect_ip = local_ip
                except Exception:
                    connect_ip = remote_ip
                    conn_mode = "remote"
            if not connect_ip:
                return {
                    "success": False,
                    "error": "missing_ip",
                    "message": "Configura una IP Local o Remota antes de conectar."
                }

        # Verificar claves de vinculación
        rp_key = profile.get("rp_key")
        regist_key = profile.get("regist_key") or ""
        host_id = profile.get("host_id") or "AA:BB:CC:DD:EE:FF"
        account_id = profile.get("account_id") or "AAAAAAAAAAAAAAAAAAAAAA=="

        # Auto-herencia de claves desde otros perfiles vinculados si faltan en este
        if not regist_key or not rp_key:
            for p in self._config_data.get("profiles", {}).values():
                if p.get("rp_key") and (p.get("host_id") == host_id or p.get("local_ip") == local_ip):
                    if not rp_key:
                        rp_key = p.get("rp_key")
                    if not regist_key and p.get("regist_key"):
                        regist_key = p.get("regist_key")
                    if rp_key:
                        profile["rp_key"] = rp_key
                    if regist_key:
                        profile["regist_key"] = regist_key
                    DRPS5Config.save_profile(profile)
                    break

        if not rp_key or not regist_key:
            return {
                "success": False,
                "error": "not_paired",
                "message": f"El perfil '{profile.get('name')}' requiere completar su vinculación con el PIN de 8 dígitos de tu pantalla de PS5 para autorizar la conexión.",
                "profile_id": profile.get("id"),
                "local_ip": local_ip
            }

        cfg = self._config_data
        res = custom_settings.get("resolution") if custom_settings else profile.get("resolution", cfg.get("resolution", "720p"))
        fps = custom_settings.get("fps") if custom_settings else profile.get("fps", cfg.get("fps", 60))
        codec = custom_settings.get("codec") if custom_settings else profile.get("codec", cfg.get("codec", "hevc"))
        hdr = custom_settings.get("hdr", False) if custom_settings else profile.get("hdr", cfg.get("hdr", False))
        audio = custom_settings.get("audio_enabled", True) if custom_settings else cfg.get("audio_enabled", True)
        fs = custom_settings.get("fullscreen", False) if custom_settings else cfg.get("fullscreen", False)
        hud = custom_settings.get("show_hud", True) if custom_settings else cfg.get("show_hud", True)

        console_type = profile.get("console_type") or profile.get("host_type") or "PS5"
        logger.info(f"Preparando pantalla remota integrada hacia {connect_ip} ({console_type}, Modo: {conn_mode.upper()}, Res: {res}, FPS: {fps}, Codec: {codec}, HDR: {hdr}, HUD: {hud})")

        upscale_mode = (custom_settings or {}).get("upscale_mode") or cfg.get("upscale_mode", "auto")
        bitrate_kbps = (custom_settings or {}).get("bitrate_kbps") if custom_settings and "bitrate_kbps" in custom_settings else cfg.get("bitrate_kbps", 0)

        # Configurar parámetros para streaming en el hilo principal del MISMO proceso DRPS5
        self._pending_stream = {
            "host_ip": connect_ip,
            "regist_key": regist_key,
            "rp_key": rp_key,
            "mac_address": host_id,
            "account_id": account_id,
            "resolution_str": res,
            "fps_val": fps,
            "codec_str": codec,
            "hdr": hdr,
            "audio_enabled": audio,
            "fullscreen": fs,
            "show_hud": hud,
            "console_type": console_type,
            "bitrate_kbps": int(bitrate_kbps or 0),
            "upscale_mode": upscale_mode,
        }

        # Cerrar ventana webview para que webview.start() termine y devuelva el control al hilo principal
        if hasattr(self, "_window") and self._window:
            try:
                self._window.destroy()
            except Exception as e:
                logger.debug(f"Error cerrando ventana launcher: {e}")

        return {
            "success": True,
            "ip": connect_ip,
            "mode": conn_mode
        }

    def get_stream_status(self):
        return {"running": bool(self._pending_stream)}

    # -------------------------------------------------------------------------
    # Visualizador de Registros y Diagnóstico
    # -------------------------------------------------------------------------
    def get_logs(self, log_type="launcher", max_lines=350):
        try:
            log_dir = Path.home() / ".drps5"
            # launcher.log concentra todos los eventos del launcher, Pygame, pyremoteplay y la GUI
            log_file = log_dir / "launcher.log"
            if not log_file.exists() or log_file.stat().st_size == 0:
                stream_file = log_dir / "stream.log"
                if stream_file.exists() and stream_file.stat().st_size > 0:
                    log_file = stream_file

            if not log_file.exists():
                return {
                    "success": True,
                    "logs": "No hay eventos registrados aún.",
                    "file_path": str(log_file),
                    "diagnosis": {
                        "status": "ok",
                        "title": "Sin Registros",
                        "detail": "Aún no se han generado registros para esta sesión."
                    }
                }

            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            tail_lines = lines[-max_lines:]
            content = "".join(tail_lines)

            # Diagnóstico inteligente de errores
            diag_status = "ok"
            diag_title = "Sistema Estable"
            diag_detail = "Los registros no muestran errores críticos recientes."

            lower_content = content.lower()
            if "host" in lower_content and ("not reachable" in lower_content or "no responde" in lower_content or "could not detect" in lower_content):
                diag_status = "warning"
                diag_title = "Consola No Alcanzable"
                diag_detail = "La consola PS5 no respondió en la IP configurada. Verifica que esté encendida y la IP sea correcta."
            elif "corrupt frame notification from 65536" in lower_content or "65536 to 0" in lower_content:
                diag_status = "info"
                diag_title = "Desbordamiento 16-bit Detectado (Corregido)"
                diag_detail = "Se detectó el reinicio de fotograma 65535->0 que causaba cuelgues tras ~36 min. Ha sido solucionado en el motor AV."
            elif "keyerror" in lower_content or "error de conexión" in lower_content:
                diag_status = "error"
                diag_title = "Error de Negociación de Sesión"
                diag_detail = "Ocurrió un fallo en el apretón de manos con la consola. Claves de vinculación o formato de versión."
            elif "backbone" in lower_content:
                diag_status = "ok"
                diag_title = "Mando Backbone Conectado"
                diag_detail = "Mando Backbone One detectado. Botón Backbone mapeado a PS y Captura a Touchpad."
            elif "dualsense" in lower_content:
                diag_status = "ok"
                diag_title = "Mando DualSense Activo"
                diag_detail = "Mando DualSense PS5 conectado en modo directo de ultra-baja latencia."

            return {
                "success": True,
                "logs": content,
                "file_path": str(log_file),
                "diagnosis": {
                    "status": diag_status,
                    "title": diag_title,
                    "detail": diag_detail
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e), "logs": f"Error leyendo logs: {e}"}

    def clear_logs(self, log_type="launcher"):
        try:
            log_dir = Path.home() / ".drps5"
            for name in ["launcher.log", "stream.log"]:
                p = log_dir / name
                if p.exists():
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(f"=== Registro DRPS5 iniciado ===\n")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def purge_old_logs(self, days=30):
        try:
            days_val = int(days) if days else 30
            stats = purge_old_logs_files(days_val)
            removed_total = stats.get("removed_lines", 0) + stats.get("removed_files", 0)
            msg = f"Limpieza (> {days_val} días) completada: {stats.get('removed_lines', 0)} entradas y {stats.get('removed_files', 0)} archivos antiguos eliminados."
            logger.info(msg)
            return {
                "success": True,
                "removed_lines": stats.get("removed_lines", 0),
                "removed_files": stats.get("removed_files", 0),
                "removed_total": removed_total,
                "message": msg
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_log_folder(self):
        try:
            log_dir = Path.home() / ".drps5"
            log_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.run(["open", str(log_dir)], check=False)
            elif sys.platform == "win32":
                os.startfile(str(log_dir))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

def main():
    try:
        import AppKit
        ns_app = AppKit.NSApplication.sharedApplication()
        ns_app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        ns_app.activateIgnoringOtherApps_(True)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for icon_cand in ["AppIcon.icns", "app_icon_1024.png"]:
            ipath = os.path.join(base_dir, icon_cand)
            if not os.path.exists(ipath):
                ipath = os.path.join(base_dir, "Resources", icon_cand)
            if not os.path.exists(ipath):
                ipath = os.path.join("/Applications/DRPS5.app/Contents/Resources", icon_cand)
            if os.path.exists(ipath):
                ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(ipath)
                if ns_img:
                    ns_app.setApplicationIconImage_(ns_img)
                    ns_app.dockTile().display()
                    break
    except Exception as e:
        logger.debug(f"Error setting activation policy or icon: {e}")

    api = DRPS5Api()
    res_env = os.environ.get("DRPS5_RESOURCES_DIR", "")
    base_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    html_candidates = [
        os.path.join(res_env, "gui", "index.html") if res_env else "",
        os.path.join(base_dir, "gui", "index.html"),
        os.path.join(base_dir, "Resources", "gui", "index.html"),
        os.path.join(os.path.dirname(sys.executable), "..", "Resources", "gui", "index.html"),
        os.path.join(os.path.dirname(sys.executable), "gui", "index.html"),
    ]
    html_path = next((p for p in html_candidates if p and os.path.exists(p)), os.path.join(base_dir, "gui", "index.html"))

    while True:
        api._pending_stream = None
        window = webview.create_window(
            title="DRPS5 - Pantalla Remota PS5",
            url=html_path,
            js_api=api,
            width=1040,
            height=880,
            min_size=(920, 720),
            background_color="#06080F"
        )
        api._set_window(window)
        webview.start(debug=False)

        # Si no hay streaming pendiente, significa que el usuario cerró la ventana normalmente para salir
        if not api._pending_stream:
            logger.info("Aplicación DRPS5 cerrada por el usuario. Finalizando proceso...")
            os._exit(0)

        # Ejecutar streaming directamente en el hilo principal del MISMO proceso DRPS5
        stream_params = api._pending_stream
        api._pending_stream = None
        try:
            logger.info(f"Iniciando streaming integrado en proceso principal DRPS5 hacia {stream_params.get('host_ip')}...")
            from drps5_stream import run_drps5_stream
            run_drps5_stream(**stream_params)
        except Exception as e:
            logger.error(f"Error en sesión de streaming: {e}", exc_info=True)
        finally:
            logger.info("Sesión de streaming finalizada. Reiniciando launcher DRPS5 para restaurar panel de control...")
            app_bin = os.environ.get("DRPS5_BIN") or "/Applications/DRPS5.app/Contents/MacOS/DRPS5"
            try:
                if sys.platform == "darwin" and os.path.exists(app_bin) and os.access(app_bin, os.X_OK):
                    os.execv(app_bin, [app_bin])
                elif sys.platform == "win32":
                    target_exe = os.path.join(base_dir, "DRPS5.exe")
                    if os.path.exists(target_exe):
                        subprocess.Popen([target_exe])
                    else:
                        target_script = sys.argv[0] if sys.argv[0].endswith(".py") else os.path.join(base_dir, "drps5.py")
                        subprocess.Popen([sys.executable, target_script])
                    os._exit(0)
                else:
                    target_script = sys.argv[0] if sys.argv[0].endswith(".py") else os.path.join(base_dir, "drps5.py")
                    os.execv(sys.executable, [sys.executable, target_script])
            except Exception as ex_err:
                logger.error(f"Error reiniciando launcher: {ex_err}")
                os._exit(0)

if __name__ == "__main__":
    main()
