#!/usr/bin/env python3
"""
DRPS5 - Entrada Principal de la Aplicación
Permite ejecutar tanto la interfaz gráfica (GUI) como comandos directos por CLI.
"""

import sys
import os
import warnings

# Identidad estricta de proceso macOS
if sys.platform == "darwin":
    try:
        import Foundation
        Foundation.NSProcessInfo.processInfo().setProcessName_("DRPS5")
    except Exception:
        pass

os.environ["TK_SILENCE_DEPRECATION"] = "1"
warnings.filterwarnings("ignore")

import argparse
import asyncio
from pathlib import Path

# Añadir directorio actual al path
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

from drps5_config import DRPS5Config
from drps5_core import discover_ps5, check_ps5_ip, wakeup_ps5, pair_ps5
from drps5_stream import run_drps5_stream

def cli_discover(args):
    print("\n🔍 Escaneando red local en busca de consolas PS5 (UDP 987)...")
    loop = asyncio.new_event_loop()
    consoles = loop.run_until_complete(discover_ps5(timeout=args.timeout))
    loop.close()

    if not consoles:
        print("❌ No se encontraron consolas PS5 respondiendo en la red local.")
        return

    print(f"\n✅ Se encontraron {len(consoles)} consola(s) PS5:")
    print("-" * 65)
    for c in consoles:
        print(f"  • {c['host_name']} ({c['host_type']})")
        print(f"    IP: {c['host_ip']}  |  Estado: {c['status']} (Código: {c['status_code']})")
        print(f"    Host-ID: {c['host_id']}  |  Firmware: {c['system_version']}")
        print("-" * 65)

def cli_wakeup(args):
    ip = args.ip
    ctype = getattr(args, "console_type", "PS5") or "PS5"
    print(f"\n⚡ Enviando comando de encendido a la {ctype} en {ip}...")
    console = DRPS5Config.get_console(ip)
    reg_key = console.get("regist_key", "") if console else ""
    if wakeup_ps5(ip, reg_key, console_type=ctype):
        print(f"✅ Paquete de encendido transmitido con éxito a {ip}.")
        print("   Espera ~15 segundos mientras la consola inicia desde el modo reposo.")
    else:
        print(f"❌ Error al enviar el paquete de encendido.")

def cli_pair(args):
    ip = args.ip
    pin = args.pin
    acc = args.account_id or "AAAAAAAAAAAAAAAAAAAAAA=="
    ctype = getattr(args, "console_type", "PS5") or "PS5"
    print(f"\n🔗 Iniciando emparejamiento con {ctype} en {ip} usando PIN {pin}...")
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(pair_ps5(ip, pin, acc, console_type=ctype))
    loop.close()

    if result and "rp_key" in result:
        host_id = result.get("host_id", ip)
        console_data = {
            "host_id": host_id,
            "host_name": result.get("host_name", f"{ctype} Vinculada"),
            "host_ip": ip,
            "regist_key": result["regist_key"],
            "rp_key": result["rp_key"],
            "account_id": result["account_id"],
            "status": "Vinculada",
            "console_type": result.get("console_type", ctype)
        }
        DRPS5Config.save_console(host_id, console_data)
        print(f"\n🎉 ¡Consola {ctype} vinculada exitosamente!")
        print(f"   IP: {ip}")
        print(f"   Claves guardadas en ~/.drps5/drps5_config.json")
        print("   Ya puedes iniciar la pantalla remota sin volver a usar el PIN.")
    else:
        print("\n❌ Error en el emparejamiento.")
        print(f"   Verifica que la {ctype} esté encendida en la pantalla de 'Vincular dispositivo'.")

def cli_stream(args):
    ip = args.ip
    console = DRPS5Config.get_console(ip)
    if not console or not console.get("rp_key"):
        print(f"\n❌ La consola {ip} no está vinculada.")
        print(f"   Ejecuta primero: drps5 pair --ip {ip} --pin <PIN_8_DIGITOS>")
        return

    cfg = DRPS5Config.load()
    res = args.resolution or cfg.get("resolution", "720p")
    fps = args.fps or cfg.get("fps", 60)
    codec = args.codec or cfg.get("codec", "hevc")
    hdr = args.hdr or cfg.get("hdr", False)
    ctype = console.get("console_type") or console.get("host_type") or "PS5"

    print(f"\n🎮 Iniciando Pantalla Remota de {ctype} en {ip} ({res} @ {fps}fps, códec: {codec}, HDR: {hdr})...")
    print("   Presiona F11 para Pantalla Completa, F1 para alternar HUD, Shift+Esc para Salir.")

    run_drps5_stream(
        host_ip=ip,
        regist_key=console["regist_key"],
        rp_key=console["rp_key"],
        mac_address=console.get("mac", "AA:BB:CC:DD:EE:FF"),
        account_id=console.get("account_id", "AAAAAAAAAAAAAAAAAAAAAA=="),
        resolution_str=res,
        fps_val=fps,
        codec_str=codec,
        hdr=hdr,
        audio_enabled=not args.no_audio,
        fullscreen=args.fullscreen,
        show_hud=not getattr(args, "no_hud", False) if hasattr(args, "no_hud") else cfg.get("show_hud", True),
        console_type=ctype
    )

def main():
    parser = argparse.ArgumentParser(
        description="DRPS5 - Pantalla Remota de PS5 sin login de PSN ni licencias",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  drps5                        # Abre la interfaz gráfica (GUI)
  drps5 discover               # Busca consolas PS5 en tu red local
  drps5 wakeup --ip 192.168.1.50 # Enciende la PS5 desde reposo
  drps5 pair --ip 192.168.1.50 --pin 12345678 # Vincula con el PIN de pantalla
  drps5 stream --ip 192.168.1.50 # Inicia la pantalla remota
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # discover
    p_disc = subparsers.add_parser("discover", help="Buscar consolas PS5 en la red local")
    p_disc.add_argument("--timeout", type=int, default=3, help="Tiempo de espera en segundos (def: 3)")

    # wakeup
    p_wake = subparsers.add_parser("wakeup", help="Encender consola desde modo reposo")
    p_wake.add_argument("--ip", required=True, help="IP de la consola")
    p_wake.add_argument("--console-type", choices=["PS5", "PS4"], default="PS5", help="Tipo de consola (PS5 o PS4)")

    # pair
    p_pair = subparsers.add_parser("pair", help="Vincular con la consola mediante PIN de 8 dígitos")
    p_pair.add_argument("--ip", required=True, help="IP de la consola")
    p_pair.add_argument("--pin", required=True, help="PIN de 8 dígitos generado en Ajustes de la consola")
    p_pair.add_argument("--account-id", help="Account ID base64 opcional")
    p_pair.add_argument("--console-type", choices=["PS5", "PS4"], default="PS5", help="Tipo de consola (PS5 o PS4)")

    # stream
    p_stream = subparsers.add_parser("stream", help="Iniciar transmisión de pantalla remota")
    p_stream.add_argument("--ip", required=True, help="IP de la consola PS5")
    p_stream.add_argument("--resolution", choices=["360p", "540p", "720p", "1080p", "1440p", "2160p"], help="Resolución")
    p_stream.add_argument("--fps", type=int, choices=[30, 60], help="Fotogramas por segundo")
    p_stream.add_argument("--codec", choices=["hevc", "h264"], help="Códec de vídeo")
    p_stream.add_argument("--hdr", action="store_true", help="Activar HDR (High Dynamic Range - 10 bits)")
    p_stream.add_argument("--fullscreen", action="store_true", help="Iniciar en pantalla completa")
    p_stream.add_argument("--no-audio", action="store_true", help="Desactivar audio")
    p_stream.add_argument("--no-hud", action="store_true", help="Ocultar HUD informativo")

    # Filtrar argumentos del sistema macOS (-psn_...) y redundancias de script
    clean_argv = [a for a in sys.argv[1:] if not a.startswith("-psn") and not a.endswith("drps5.py") and not a.endswith(".app")]
    args, _ = parser.parse_known_args(clean_argv)

    if args.command == "discover":
        cli_discover(args)
    elif args.command == "wakeup":
        cli_wakeup(args)
    elif args.command == "pair":
        cli_pair(args)
    elif args.command == "stream":
        cli_stream(args)
    else:
        # Por defecto abre la interfaz gráfica
        from drps5_gui import main as gui_main
        gui_main()

if __name__ == "__main__":
    main()
