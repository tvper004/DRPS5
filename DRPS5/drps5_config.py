#!/usr/bin/env python3
"""
DRPS5 - Configuración y Perfiles de Conexión (Red Local e Internet Remoto)
Gestión avanzada de múltiples perfiles de PS5, IPs locales, IPs públicas/DDNS y claves criptográficas.
Sin inicio de sesión en PSN ni servicios externos de telemetría.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

CONFIG_DIR = Path.home() / ".drps5"
CONFIG_FILE = CONFIG_DIR / "drps5_config.json"

DEFAULT_GAMEPAD_MAPPING: Dict[str, Any] = {
    "ps_button": 5,           # Guía estándar SDL2 (botón PS en DualSense / Xbox / MFi)
    "touchpad_button": 20,    # Touchpad estándar SDL2 en DualSense
    "options_button": 6,      # Start / Options
    "share_button": 4,        # Back / Share / Create
    "stick_deadzone": 0.12    # Zona muerta radial re-escalada (12%) para prevenir drift analógico
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.1.0",
    "active_profile_id": "profile_default",
    "resolution": "720p",      # "720p", "1080p", "540p"
    "fps": 60,                 # 30, 60
    "bitrate": "standard",     # "low", "standard", "high", "ultra"
    "codec": "hevc",           # "hevc" (H.265) o "h264"
    "hdr": False,              # HDR (High Dynamic Range - 10 bits, requiere HEVC)
    "audio_enabled": True,
    "fullscreen": False,
    "show_hud": True,          # Mostrar superposición de estado (FPS, Mando, Atajos)
    "gamepad_mapping": DEFAULT_GAMEPAD_MAPPING.copy(),
    "profiles": {},            # ID del perfil -> dict con datos
    "consoles": {}             # Retrocompatibilidad
}

def create_empty_profile(name="PS5 Principal", local_ip="", remote_ip="") -> Dict[str, Any]:
    prof_id = f"prof_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    return {
        "id": prof_id,
        "name": name,
        "local_ip": local_ip,
        "remote_ip": remote_ip,
        "connection_mode": "local",   # "local" o "remote"
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

class DRPS5Config:
    @staticmethod
    def _ensure_dir():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> Dict[str, Any]:
        cls._ensure_dir()
        if not CONFIG_FILE.exists():
            # Buscar si existe una configuración empaquetada inicial junto a la aplicación (seed)
            bundled_cfg = Path(__file__).resolve().parent / "drps5_config.json"
            if bundled_cfg.exists():
                try:
                    with open(bundled_cfg, "r", encoding="utf-8") as bf:
                        data = json.load(bf)
                    cls.save(data)
                    return data
                except Exception:
                    pass

            default_data = DEFAULT_CONFIG.copy()
            default_prof = create_empty_profile(name="PS5 Principal", local_ip="")
            default_data["profiles"] = {default_prof["id"]: default_prof}
            default_data["active_profile_id"] = default_prof["id"]
            cls.save(default_data)
            return default_data

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Fusionar con claves por defecto
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v

            # Sincronizar perfiles y credenciales preconfiguradas desde el paquete de la app
            bundled_cfg = Path(__file__).resolve().parent / "drps5_config.json"
            if bundled_cfg.exists():
                try:
                    with open(bundled_cfg, "r", encoding="utf-8") as bf:
                        b_data = json.load(bf)
                    b_profiles = b_data.get("profiles", {})
                    b_consoles = b_data.get("consoles", {})
                    updated = False
                    for b_id, b_prof in b_profiles.items():
                        curr_prof = data.get("profiles", {}).get(b_id)
                        if not curr_prof:
                            data.setdefault("profiles", {})[b_id] = b_prof
                            updated = True
                        elif b_prof.get("rp_key") and (not curr_prof.get("rp_key") or not curr_prof.get("remote_ip")):
                            if not curr_prof.get("rp_key"):
                                curr_prof["rp_key"] = b_prof.get("rp_key", "")
                            if not curr_prof.get("regist_key"):
                                curr_prof["regist_key"] = b_prof.get("regist_key", "")
                            if not curr_prof.get("account_id"):
                                curr_prof["account_id"] = b_prof.get("account_id", "")
                            if not curr_prof.get("remote_ip"):
                                curr_prof["remote_ip"] = b_prof.get("remote_ip", "")
                            updated = True
                    for c_id, c_val in b_consoles.items():
                        if c_id not in data.get("consoles", {}):
                            data.setdefault("consoles", {})[c_id] = c_val
                            updated = True
                    if updated:
                        if "prof_ps5_main" in data.get("profiles", {}):
                            data["active_profile_id"] = "prof_ps5_main"
                        cls.save(data)
                except Exception:
                    pass

            # Migración: Si no hay perfiles pero hay consolas previas en `consoles`
            if not data.get("profiles") and data.get("consoles"):
                profiles = {}
                for host_key, c in data["consoles"].items():
                    pid = f"prof_{host_key.replace('.', '_')}"
                    p = {
                        "id": pid,
                        "name": c.get("host_name") or "PS5 Principal",
                        "local_ip": c.get("host_ip") or "",
                        "remote_ip": "",
                        "connection_mode": "local",
                        "host_id": c.get("host_id") or "",
                        "host_name": c.get("host_name") or "PS5",
                        "regist_key": c.get("regist_key") or "",
                        "rp_key": c.get("rp_key") or "",
                        "account_id": c.get("account_id") or "",
                        "status": c.get("status") or "Vinculada",
                        "resolution": data.get("resolution", "720p"),
                        "fps": data.get("fps", 60),
                        "codec": data.get("codec", "hevc"),
                        "hdr": data.get("hdr", False)
                    }
                    profiles[pid] = p

                data["profiles"] = profiles
                if profiles:
                    data["active_profile_id"] = next(iter(profiles.keys()))
                cls.save(data)

            # Si aún está vacío, crear un perfil predeterminado
            if not data.get("profiles"):
                default_prof = create_empty_profile(name="PS5 Principal", local_ip="")
                data["profiles"] = {default_prof["id"]: default_prof}
                data["active_profile_id"] = default_prof["id"]
                cls.save(data)

            return data
        except Exception:
            return DEFAULT_CONFIG.copy()

    @classmethod
    def save(cls, config: Dict[str, Any]):
        cls._ensure_dir()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    @classmethod
    def get_profiles(cls) -> List[Dict[str, Any]]:
        cfg = cls.load()
        profiles_dict = cfg.get("profiles", {})
        return list(profiles_dict.values())

    @classmethod
    def get_profile(cls, profile_id: str) -> Optional[Dict[str, Any]]:
        cfg = cls.load()
        return cfg.get("profiles", {}).get(profile_id)

    @classmethod
    def get_active_profile(cls) -> Dict[str, Any]:
        cfg = cls.load()
        profiles = cfg.get("profiles", {})
        active_id = cfg.get("active_profile_id")

        if active_id and active_id in profiles:
            return profiles[active_id]

        if profiles:
            first_id = next(iter(profiles.keys()))
            cfg["active_profile_id"] = first_id
            cls.save(cfg)
            return profiles[first_id]

        new_p = create_empty_profile()
        cfg["profiles"] = {new_p["id"]: new_p}
        cfg["active_profile_id"] = new_p["id"]
        cls.save(cfg)
        return new_p

    @classmethod
    def save_profile(cls, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        cfg = cls.load()
        if "profiles" not in cfg:
            cfg["profiles"] = {}

        prof_id = profile_data.get("id")
        if not prof_id:
            prof_id = f"prof_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            profile_data["id"] = prof_id

        # Preservar o actualizar
        existing = cfg["profiles"].get(prof_id, {})
        existing.update(profile_data)

        # Cada perfil de consola PS5/PS4 debe registrarse independientemente con su propio PIN
        if not existing.get("rp_key") or not existing.get("regist_key"):
            existing["regist_key"] = existing.get("regist_key", "")
            existing["rp_key"] = existing.get("rp_key", "")
            existing["status"] = "Vinculada" if (existing.get("rp_key") and existing.get("regist_key")) else "Pendiente"

        cfg["profiles"][prof_id] = existing

        # Sincronizar en `consoles` por retrocompatibilidad
        local_ip = existing.get("local_ip", "")
        if local_ip:
            if "consoles" not in cfg:
                cfg["consoles"] = {}
            cfg["consoles"][local_ip] = {
                "host_id": existing.get("host_id", local_ip),
                "host_name": existing.get("name", "PS5"),
                "host_ip": local_ip,
                "regist_key": existing.get("regist_key"),
                "rp_key": existing.get("rp_key"),
                "account_id": existing.get("account_id"),
                "status": existing.get("status", "Vinculada")
            }

        cfg["active_profile_id"] = prof_id
        cfg["last_used_ip"] = existing.get("local_ip", "")
        cls.save(cfg)
        return existing

    @classmethod
    def delete_profile(cls, profile_id: str) -> bool:
        cfg = cls.load()
        profiles = cfg.get("profiles", {})
        if profile_id in profiles:
            del profiles[profile_id]
            # Si se eliminó el activo, reasignar
            if cfg.get("active_profile_id") == profile_id:
                cfg["active_profile_id"] = next(iter(profiles.keys())) if profiles else ""
            cls.save(cfg)
            return True
        return False

    @classmethod
    def set_active_profile(cls, profile_id: str) -> Optional[Dict[str, Any]]:
        cfg = cls.load()
        if profile_id in cfg.get("profiles", {}):
            cfg["active_profile_id"] = profile_id
            cls.save(cfg)
            return cfg["profiles"][profile_id]
        return None

    @classmethod
    def set_connection_mode(cls, profile_id: str, mode: str) -> bool:
        cfg = cls.load()
        if profile_id in cfg.get("profiles", {}):
            cfg["profiles"][profile_id]["connection_mode"] = mode
            cls.save(cfg)
            return True
        return False

    # Métodos legacy para retrocompatibilidad
    @classmethod
    def get_console(cls, identifier: str) -> Optional[Dict[str, Any]]:
        cfg = cls.load()
        # Buscar primero en perfiles
        for p in cfg.get("profiles", {}).values():
            if p.get("local_ip") == identifier or p.get("remote_ip") == identifier or p.get("host_id") == identifier or p.get("id") == identifier:
                return {
                    "host_id": p.get("host_id") or identifier,
                    "host_name": p.get("name") or "PS5",
                    "host_ip": p.get("local_ip"),
                    "regist_key": p.get("regist_key"),
                    "rp_key": p.get("rp_key"),
                    "account_id": p.get("account_id"),
                    "mac": p.get("host_id"),
                    "status": p.get("status", "Vinculada")
                }
        consoles = cfg.get("consoles", {})
        if identifier in consoles:
            return consoles[identifier]
        for host_id, c in consoles.items():
            if c.get("host_ip") == identifier:
                return c
        return None

    @classmethod
    def save_console(cls, host_id: str, console_data: Dict[str, Any]):
        cfg = cls.load()
        if "consoles" not in cfg:
            cfg["consoles"] = {}
        cfg["consoles"][host_id] = console_data
        
        # También reflejar en perfil activo
        active_p = cls.get_active_profile()
        if active_p:
            active_p["host_id"] = host_id
            active_p["local_ip"] = console_data.get("host_ip", active_p.get("local_ip"))
            active_p["regist_key"] = console_data.get("regist_key") or active_p.get("regist_key")
            active_p["rp_key"] = console_data.get("rp_key") or active_p.get("rp_key")
            active_p["account_id"] = console_data.get("account_id") or active_p.get("account_id")
            active_p["status"] = console_data.get("status", "Vinculada")
            cfg["profiles"][active_p["id"]] = active_p

        cls.save(cfg)

    @classmethod
    def set(cls, key: str, value: Any):
        cfg = cls.load()
        cfg[key] = value
        cls.save(cfg)

    @classmethod
    def get_gamepad_mapping(cls) -> Dict[str, Any]:
        cfg = cls.load()
        mapping = cfg.get("gamepad_mapping") or {}
        res = DEFAULT_GAMEPAD_MAPPING.copy()
        res.update(mapping)
        return res

    @classmethod
    def save_gamepad_mapping(cls, mapping: Dict[str, Any]):
        cfg = cls.load()
        cfg["gamepad_mapping"] = mapping
        cls.save(cfg)
        return cfg["gamepad_mapping"]
