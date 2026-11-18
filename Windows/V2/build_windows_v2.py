#!/usr/bin/env python3
"""
Constructor de instaladores Windows V2 (x86_64 y Windows ARM64 via Prism + D3D11 GPU) para DRPS5:
1. /Users/rleon/Documents/PXPLAY/Windows/V2/DRPS5_V2_Setup_Personal.exe
2. /Users/rleon/Documents/PXPLAY/Windows/V2/DRPS5_V2_Setup_Publico.exe
"""

from __future__ import annotations
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import zlib
from pathlib import Path

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
WIN_V1_DIR = WORKSPACE_DIR / "Windows"
WIN_V2_DIR = WIN_V1_DIR / "V2"
SRC_V1_DIR = WIN_V1_DIR / "DRPS5"
LAUNCHER_SRC_DIR = WIN_V1_DIR / "launcher_src"
V2_CORE_DIR = WORKSPACE_DIR / "DRPS5" / "v2_core"
GUI_V2_DIR = WORKSPACE_DIR / "DRPS5" / "gui_v2"
PYREMOTEPLAY_DIR = WORKSPACE_DIR / "DRPS5" / "pyremoteplay"

PERSONAL_SEED_CONFIG = {
    "version": "2.0.0",
    "last_used_ip": "192.168.1.100",
    "resolution": "1080p",
    "upscale_mode": "auto",
    "fps": 60,
    "bitrate_kbps": 0,
    "codec": "hevc",
    "hdr": False,
    "audio_enabled": True,
    "fullscreen": False,
    "connection_mode": "auto",
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "Mi PS5",
            "local_ip": "192.168.1.100",
            "remote_ip": "",
            "connection_mode": "auto",
            "host_id": "",
            "host_name": "PS5",
            "host_type": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada",
            "resolution": "1080p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False
        }
    }
}

PUBLIC_SEED_CONFIG = {
    "version": "2.0.0",
    "last_used_ip": "",
    "resolution": "1080p",
    "upscale_mode": "auto",
    "fps": 60,
    "bitrate_kbps": 0,
    "codec": "hevc",
    "hdr": False,
    "audio_enabled": True,
    "fullscreen": False,
    "connection_mode": "auto",
    "active_profile_id": "",
    "profiles": {}
}



_PSEED = WORKSPACE_DIR / "personal_seed.json"
if _PSEED.exists():
    PERSONAL_SEED_CONFIG = json.loads(_PSEED.read_text(encoding="utf-8"))
    PERSONAL_CONFIG = PERSONAL_SEED_CONFIG

def build_core_pak(out_pak: Path, seed_cfg: dict) -> bytes:
    key = secrets.token_bytes(32)
    modules = {}
    for py_file in V2_CORE_DIR.glob("*.py"):
        mod_name = py_file.stem
        text = py_file.read_text(encoding="utf-8")
        if mod_name == "drps5_config":
            seed_json = json.dumps(seed_cfg, ensure_ascii=False)
            text = text + f"\n\n_SEED_FALLBACK_JSON = {repr(seed_json)}\n"
        modules[mod_name] = text

    for py_file in PYREMOTEPLAY_DIR.rglob("*.py"):
        rel = py_file.relative_to(PYREMOTEPLAY_DIR)
        parts = list(rel.with_suffix("").parts)
        mod_name = ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)
        if mod_name:
            modules[mod_name] = py_file.read_text(encoding="utf-8")

    raw_json = json.dumps(modules, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw_json, level=9)
    encrypted = bytearray(len(compressed))
    block_idx = 0
    pos = 0
    while pos < len(compressed):
        ks = hashlib.sha256(key + block_idx.to_bytes(4, "little")).digest()
        chunk = min(32, len(compressed) - pos)
        for i in range(chunk):
            encrypted[pos + i] = compressed[pos + i] ^ ks[i]
        pos += chunk
        block_idx += 1
    out_pak.write_bytes(bytes(encrypted))
    return key


def compile_win_exe(out_exe: Path, pak_key: bytes, is_personal: bool):
    xor_mask = secrets.token_bytes(32)
    enc_key = bytes(pak_key[i] ^ xor_mask[i] for i in range(32))

    def c_arr(b: bytes) -> str:
        return ", ".join(f"0x{x:02x}" for x in b)

    edition = "personal" if is_personal else "public"
    c_src = f"""
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

__declspec(dllexport) DWORD NvOptimusEnablement = 0x00000001;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;

typedef void (*Py_SetProgramName_t)(const wchar_t *);
typedef void (*Py_SetPythonHome_t)(const wchar_t *);
typedef void (*Py_Initialize_t)(void);
typedef int  (*PyRun_SimpleString_t)(const char *);
typedef void (*Py_Finalize_t)(void);

static const unsigned char ENC_KEY[32] = {{ {c_arr(enc_key)} }};
static const unsigned char XOR_MASK[32] = {{ {c_arr(xor_mask)} }};

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmdLine, int showCmd) {{
    (void)hInst; (void)hPrev; (void)cmdLine; (void)showCmd;
    wchar_t exePath[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exePath, MAX_PATH)) return 1;
    wchar_t baseDir[MAX_PATH];
    wcscpy(baseDir, exePath);
    wchar_t *slash = wcsrchr(baseDir, L'\\\\');
    if (slash) *slash = L'\\0';
    SetCurrentDirectoryW(baseDir);

    SetEnvironmentVariableW(L"DRPS5_EDITION", L"{edition}");
    SetEnvironmentVariableW(L"SDL_RENDER_DRIVER", L"direct3d11");
    SetEnvironmentVariableW(L"SDL_RENDER_SCALE_QUALITY", L"2");
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");

    wchar_t runtimeDir[MAX_PATH];
    swprintf(runtimeDir, MAX_PATH, L"%ls\\\\runtime", baseDir);
    SetDllDirectoryW(runtimeDir);

    wchar_t pyDll[MAX_PATH];
    swprintf(pyDll, MAX_PATH, L"%ls\\\\python311.dll", runtimeDir);
    HMODULE hPy = LoadLibraryW(pyDll);
    if (!hPy) {{
        MessageBoxW(NULL, L"No se pudo cargar python311.dll", L"DRPS5 V2", MB_ICONERROR | MB_OK);
        return 2;
    }}

    Py_SetProgramName_t pSetName = (Py_SetProgramName_t)GetProcAddress(hPy, "Py_SetProgramName");
    Py_SetPythonHome_t  pSetHome = (Py_SetPythonHome_t)GetProcAddress(hPy, "Py_SetPythonHome");
    Py_Initialize_t     pInit    = (Py_Initialize_t)GetProcAddress(hPy, "Py_Initialize");
    PyRun_SimpleString_t pRun    = (PyRun_SimpleString_t)GetProcAddress(hPy, "PyRun_SimpleString");
    Py_Finalize_t       pFin     = (Py_Finalize_t)GetProcAddress(hPy, "Py_Finalize");

    if (!pInit || !pRun) return 3;
    if (pSetName) pSetName(exePath);
    if (pSetHome) pSetHome(runtimeDir);

    unsigned char key[32];
    char hex_key[65];
    for (int i = 0; i < 32; i++) {{
        key[i] = ENC_KEY[i] ^ XOR_MASK[i];
        snprintf(hex_key + i * 2, 3, "%02x", key[i]);
    }}

    pInit();
    char boot[8192];
    snprintf(boot, sizeof(boot),
        "import os, sys, json, zlib, hashlib, importlib.abc, importlib.util\\n"
        "pak = open('core.pak', 'rb').read()\\n"
        "key = bytes.fromhex('%s')\\n"
        "dec = bytearray(len(pak))\\n"
        "idx = 0; pos = 0\\n"
        "while pos < len(pak):\\n"
        "    ks = hashlib.sha256(key + idx.to_bytes(4, 'little')).digest()\\n"
        "    n = min(32, len(pak) - pos)\\n"
        "    for i in range(n): dec[pos + i] = pak[pos + i] ^ ks[i]\\n"
        "    pos += n; idx += 1\\n"
        "mods = json.loads(zlib.decompress(bytes(dec)).decode('utf-8'))\\n"
        "res = os.getcwd()\\n"
        "class _VaultLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):\\n"
        "    def find_spec(self, name, path=None, target=None):\\n"
        "        if name in mods:\\n"
        "            is_pkg = (name=='pyremoteplay' or any(k.startswith(name+'.') for k in mods))\\n"
        "            spec = importlib.util.spec_from_loader(name, self, is_package=is_pkg)\\n"
        "            spec.origin = os.path.join(res, name.replace('.', os.sep) + '.py')\\n"
        "            return spec\\n"
        "        return None\\n"
        "    def create_module(self, spec): return None\\n"
        "    def exec_module(self, mod):\\n"
        "        mod.__file__ = os.path.join(res, mod.__name__.replace('.', os.sep) + '.py')\\n"
        "        if hasattr(mod, '__spec__') and mod.__spec__ and mod.__spec__.submodule_search_locations is not None:\\n"
        "            mod.__path__ = [os.path.join(res, *mod.__name__.split('.'))]\\n"
        "        exec(compile(mods[mod.__name__], '<vault:' + mod.__name__ + '>', 'exec'), mod.__dict__)\\n"
        "sys.meta_path.insert(0, _VaultLoader())\\n"
        "if not getattr(sys, 'argv', None): sys.argv = [os.path.join(res, 'drps5.py')]\\n"
        "import drps5\\n"
        "drps5.main()\\n",
        hex_key
    );
    int rc = pRun(boot);
    SecureZeroMemory(boot, sizeof(boot));
    SecureZeroMemory(key, sizeof(key));
    if (pFin) pFin();
    return rc;
}}
"""
    c_file = out_exe.parent / "launcher_v2.c"
    c_file.write_text(c_src, encoding="utf-8")
    subprocess.run([
        "/opt/homebrew/bin/x86_64-w64-mingw32-gcc",
        "-O3", "-municode", "-mwindows", "-s",
        str(c_file),
        str(LAUNCHER_SRC_DIR / "resource.o"),
        "-o", str(out_exe),
    ], check=True)
    c_file.unlink()


def build_edition(is_personal: bool):
    tag = "Personal" if is_personal else "Publico"
    staging = WIN_V2_DIR / f"_stage_{tag}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    shutil.copy2(SRC_V1_DIR / "app_icon.ico", staging / "app_icon.ico")
    shutil.copy2(SRC_V1_DIR / "gamecontrollerdb.txt", staging / "gamecontrollerdb.txt")
    shutil.copytree(GUI_V2_DIR, staging / "gui", dirs_exist_ok=True)
    shutil.copytree(SRC_V1_DIR / "assets", staging / "assets", dirs_exist_ok=True)
    shutil.copytree(SRC_V1_DIR / "runtime", staging / "runtime", dirs_exist_ok=True)

    seed = PERSONAL_SEED_CONFIG if is_personal else PUBLIC_SEED_CONFIG
    pak_key = build_core_pak(staging / "core.pak", seed)
    compile_win_exe(staging / "DRPS5.exe", pak_key, is_personal)

    out_exe = WIN_V2_DIR / f"DRPS5_V2_Setup_{tag}.exe"
    if out_exe.exists():
        out_exe.unlink()

    nsi_content = f"""
Unicode True
!include "MUI2.nsh"

Name "DRPS5 Remote Play V2 ({tag})"
OutFile "{out_exe}"
InstallDir "$PROGRAMFILES64\\DRPS5"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ICON "{staging}\\app_icon.ico"
!define MUI_UNICON "{staging}\\app_icon.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\\DRPS5.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Section "DRPS5 V2" SecMain
  SetOutPath "$INSTDIR"
  File /r "{staging}\\*.*"
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\\DRPS5"
  CreateShortcut "$SMPROGRAMS\\DRPS5\\DRPS5.lnk" "$INSTDIR\\DRPS5.exe" "" "$INSTDIR\\app_icon.ico"
  CreateShortcut "$SMPROGRAMS\\DRPS5\\Desinstalar DRPS5.lnk" "$INSTDIR\\Uninstall.exe" "" "$INSTDIR\\app_icon.ico"
  CreateShortcut "$DESKTOP\\DRPS5.lnk" "$INSTDIR\\DRPS5.exe" "" "$INSTDIR\\app_icon.ico"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\\DRPS5.lnk"
  Delete "$SMPROGRAMS\\DRPS5\\DRPS5.lnk"
  Delete "$SMPROGRAMS\\DRPS5\\Desinstalar DRPS5.lnk"
  RMDir "$SMPROGRAMS\\DRPS5"
  RMDir /r "$INSTDIR"
SectionEnd
"""
    nsi_path = WIN_V2_DIR / f"_setup_{tag}.nsi"
    nsi_path.write_text(nsi_content, encoding="utf-8")
    subprocess.run(["/opt/homebrew/bin/makensis", str(nsi_path)], check=True)
    nsi_path.unlink()
    shutil.rmtree(staging)
    print(f"Built Windows Installer [{tag}]: {out_exe} ({out_exe.stat().st_size} bytes)")


def main():
    WIN_V2_DIR.mkdir(parents=True, exist_ok=True)
    build_edition(True)
    build_edition(False)


if __name__ == "__main__":
    main()
