#!/usr/bin/env python3
"""
DRPS5 - Módulo Central de Comunicación con PS5
Maneja descubrimiento, encendido (wake-up), emparejamiento (PIN) y conexión de streaming.
No requiere servicios externos ni inicio de sesión en PSN.
"""

import asyncio
import logging
import base64
import struct
from typing import List, Dict, Any, Optional

from pyremoteplay.ddp import async_search, async_get_status, wakeup, STATUS_OK, STATUS_STANDBY
from pyremoteplay.const import TYPE_PS5, TYPE_PS4, Resolution, FPS
from pyremoteplay.register import async_register
from pyremoteplay.session import Session
from pyremoteplay.profile import UserProfile
from pyremoteplay.util import format_regist_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DRPS5.Core")

# Fallback default account ID base64 si el usuario no especifica uno
DEFAULT_LOCAL_ACCOUNT_ID = "AAAAAAAAAAAAAAAAAAAAAA=="

def clean_ip_target(ip_str: str) -> str:
    """Limpia cadenas de IP que incluyan comas, IPv6 secundarias o espacios (ej. Tailscale GUI)."""
    if not ip_str:
        return ""
    part = str(ip_str).split(",")[0].strip()
    part = part.split()[0].strip()
    return part

def format_account_id(acc_input: str) -> str:
    """
    Convierte el Account ID de PlayStation (entero decimal, hexadecimal o Base64)
    al formato exacto requerido por el protocolo de Sony (8 bytes unsigned little-endian en Base64).
    """
    s = str(acc_input).strip()
    if not s:
        return DEFAULT_LOCAL_ACCOUNT_ID
    
    # Si es numérico (entero decimal, ej: 1234567890123456789)
    if s.isdigit():
        val = int(s)
        return base64.b64encode(struct.pack("<Q", val)).decode("utf-8")
        
    # Si es hexadecimal (ej: 0x450ef65e41731305 o 450ef65e41731305)
    if s.lower().startswith("0x") or (len(s) == 16 and all(c in "0123456789abcdefABCDEF" for c in s)):
        val = int(s, 16)
        return base64.b64encode(struct.pack("<Q", val)).decode("utf-8")
        
    # Si ya es un Base64 válido de 8 bytes (11 o 12 caracteres terminados en =)
    try:
        raw = base64.b64decode(s)
        if len(raw) == 8:
            return s
    except Exception:
        pass
        
    # Fallback
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")

async def discover_ps5(timeout: int = 3) -> List[Dict[str, Any]]:
    """Descubre consolas PS5 en la red local mediante broadcast UDP (puerto 987)."""
    try:
        hosts = await async_search(timeout=timeout)
        consoles = []
        for h in hosts:
            device_type = h.get("host-type", "PS5")
            consoles.append({
                "host_id": h.get("host-id", ""),
                "host_name": h.get("host-name", "PS5 Console"),
                "host_ip": h.get("host-ip", ""),
                "host_type": device_type,
                "status_code": h.get("status-code", 0),
                "status": "Encendida" if h.get("status-code") == STATUS_OK else "Modo Reposo" if h.get("status-code") == STATUS_STANDBY else "Desconocido",
                "system_version": h.get("system-version", "")
            })
        return consoles
    except Exception as e:
        logger.error(f"Error descubriendo PS5: {e}")
        return []

async def check_ps5_ip(ip: str) -> Optional[Dict[str, Any]]:
    """Verifica directamente el estado de una PS5 por IP."""
    clean_ip = clean_ip_target(ip)
    try:
        status = await async_get_status(clean_ip)
        if status:
            return {
                "host_id": status.get("host-id", ""),
                "host_name": status.get("host-name", "PS5 Console"),
                "host_ip": clean_ip,
                "host_type": status.get("host-type", "PS5"),
                "status_code": status.get("status-code", 0),
                "status": "Encendida" if status.get("status-code") == STATUS_OK else "Modo Reposo",
                "system_version": status.get("system-version", "")
            }
    except Exception as e:
        logger.error(f"Error consultando IP {clean_ip}: {e}")
    return None

def wakeup_ps5(ip: str, regist_key: str = "", console_type: str = "PS5"):
    """Envía el paquete Wake-on-LAN/DDP para encender la PS5 o PS4 desde Modo Reposo."""
    clean_ip = clean_ip_target(ip)
    try:
        key = format_regist_key(regist_key) if regist_key else ""
        ht = TYPE_PS4 if str(console_type).upper() == "PS4" else TYPE_PS5
        wakeup(clean_ip, key, host_type=ht)
        logger.info(f"Comando de encendido ({ht}) enviado a {clean_ip}")
        return True
    except Exception as e:
        logger.error(f"Error encendiendo {console_type} {clean_ip}: {e}")
        return False

async def pair_ps5(ip: str, pin: str, account_id: str = "", console_type: str = "PS5") -> Optional[Dict[str, Any]]:
    """
    Empareja con la consola (PS5 o PS4) usando el PIN de 8 dígitos de pantalla.
    No requiere navegar en web ni login de PSN con contraseñas.
    """
    clean_ip = clean_ip_target(ip)
    try:
        clean_pin = pin.strip().replace(" ", "").replace("-", "")
        if len(clean_pin) != 8 or not clean_pin.isdigit():
            raise ValueError("El PIN debe contener exactamente 8 dígitos numéricos.")

        # Formatear el Account ID correctamente
        acc_id = format_account_id(account_id)

        target_ht = TYPE_PS4 if str(console_type).upper() == "PS4" else TYPE_PS5
        logger.info(f"Iniciando emparejamiento con {target_ht} en {clean_ip} (PIN: {clean_pin}, Account ID: {acc_id})...")
        regist_data = await async_register(clean_ip, acc_id, clean_pin, timeout=5.0, host_type=target_ht)

        if regist_data and "RP-Key" in regist_data:
            logger.info(f"¡Emparejamiento exitoso con {target_ht}!")
            reg_key = (
                regist_data.get("RegistKey")
                or regist_data.get("PS5-RegistKey")
                or regist_data.get("PS4-RegistKey")
                or regist_data.get("RP-RegistKey")
                or ""
            )
            mac_addr = (
                regist_data.get("Mac")
                or regist_data.get("PS5-Mac")
                or regist_data.get("PS4-Mac")
                or regist_data.get("host-id")
                or ""
            )
            host_name = (
                regist_data.get("Nickname")
                or regist_data.get("PS5-Nickname")
                or regist_data.get("PS4-Nickname")
                or f"{target_ht} Vinculada"
            )
            return {
                "host_id": mac_addr or ip,
                "host_name": host_name,
                "host_ip": ip,
                "mac": mac_addr,
                "rp_key": regist_data.get("RP-Key"),
                "regist_key": reg_key,
                "account_id": acc_id,
                "console_type": target_ht
            }
        else:
            reason = regist_data.get("error_reason") if isinstance(regist_data, dict) else None
            logger.warning(f"La consola ({target_ht}) rechazó el emparejamiento (motivo: {reason}): {regist_data}")
            return {"error_reason": reason}
    except Exception as e:
        logger.error(f"Error en pair_ps5: {e}")
        return None

def create_stream_session(
    host_ip: str,
    mac_address: str,
    regist_key: str,
    rp_key: str,
    account_id: str = DEFAULT_LOCAL_ACCOUNT_ID,
    receiver=None,
    resolution: str = "720p",
    fps: int = 60,
    codec: str = "hevc",
    console_type: str = "PS5"
) -> Session:
    """Crea una sesión directa de pantalla remota con la PS5 o PS4."""
    res_enum = Resolution.parse(resolution)
    fps_enum = FPS.FPS_60 if fps == 60 else FPS.FPS_30

    mac = mac_address if mac_address else "AA:BB:CC:DD:EE:FF"
    ht = TYPE_PS4 if str(console_type).upper() == "PS4" else TYPE_PS5

    user_profile = UserProfile("DRPS5_User", {
        "id": account_id if account_id else DEFAULT_LOCAL_ACCOUNT_ID,
        "hosts": {
            mac: {
                "type": ht,
                "data": {
                    "RegistKey": regist_key,
                    "RP-Key": rp_key
                }
            }
        }
    })

    session = Session(
        host=host_ip,
        profile=user_profile,
        receiver=receiver,
        resolution=res_enum,
        fps=fps_enum,
        codec=codec
    )
    return session
