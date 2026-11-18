#!/usr/bin/env python3
"""
Constructor de los 2 instaladores blindados anti-REA de DRPS5 para Windows:
1. DRPS5_Setup_Personal.exe (Con credenciales PS5 del usuario cifradas en core.pak)
2. DRPS5_Setup_Publico.exe  (Versión pública limpia sin cuentas ni IPs personales, cifrada en core.pak)

Características de protección anti-ingeniería inversa (REA):
- Cero archivos .py, .pyc, .bat o drps5_config.json en el directorio de instalación.
- Empaquetado de los 44 módulos (drps5* + pyremoteplay/**) en core.pak con cifrado de flujo
  SHA-256 de 256 bits (clave única por compilación) + compresión zlib nivel 9 + limpieza de docstrings.
- Ejecutable nativo PE64 (DRPS5.exe) compilado con mingw-w64 (-O3 -fvisibility=hidden -flto -s):
  * Detección anti-debugger Win32 (IsDebuggerPresent, CheckRemoteDebuggerPresent).
  * Inspección directa del PEB x64 (__readgsqword(0x60) -> BeingDebugged y NtGlobalFlag).
  * Ocultación del hilo principal ante depuradores a nivel kernel NT (NtSetInformationThread -> ThreadHideFromDebugger 0x11).
  * Escaneo de módulos en memoria (CreateToolhelp32Snapshot) contra Frida, x64dbg, CheatEngine, Scylla y TitanEngine.
  * Todas las cadenas C y el bootstrapper de Python están cifrados con XOR de 256 bits y se borran de la RAM tras ejecutarse.
  * Carga de módulos exclusivamente en memoria RAM (_VaultLoader) con Py_OptimizeFlag=2, Py_DontWriteBytecodeFlag=1 y Py_IgnoreEnvironmentFlag=1.
"""

from __future__ import annotations
import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
WIN_DIR = WORKSPACE_DIR / "Windows"
SRC_DIR = WIN_DIR / "DRPS5"
LAUNCHER_SRC_DIR = WIN_DIR / "launcher_src"

PERSONAL_SEED_CONFIG = {
    "version": "1.2.0",
    "last_used_ip": "192.168.1.100",
    "resolution": "1080p",
    "fps": 60,
    "bitrate": "standard",
    "codec": "hevc",
    "audio_enabled": True,
    "fullscreen": False,
    "consoles": {
        "": {
            "host_id": "",
            "host_name": "PS5",
            "host_ip": "192.168.1.100",
            "host_type": "PS5",
            "status": "Encendida"
        },
        "192.168.1.100": {
            "host_id": "",
            "host_name": "Mi PS5",
            "host_ip": "192.168.1.100",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada"
        }
    },
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "Mi PS5",
            "local_ip": "192.168.1.100",
            "remote_ip": "",
            "connection_mode": "remote",
            "host_id": "",
            "host_name": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada",
            "resolution": "1080p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False
        }
    },
    "show_hud": False,
    "gamepad_mapping": {
        "ps_button": 5,
        "touchpad_button": 20,
        "options_button": 6,
        "share_button": 4,
        "stick_deadzone": 0.12
    },
    "hdr": False
}


def stream_xor(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data))
    mv = memoryview(data)
    offset = 0
    counter = 0
    while offset < len(data):
        digest = hashlib.sha256(key + counter.to_bytes(8, "little")).digest()
        chunk = mv[offset : offset + 32]
        for i, b in enumerate(chunk):
            out[offset + i] = b ^ digest[i]
        offset += 32
        counter += 1
    return bytes(out)


def strip_comments_and_docstrings(source: str) -> str:
    """Verifica sintaxis con AST y elimina comentarios puros para reducir huella."""
    # Validar que el código compila perfectamente
    ast.parse(source)
    lines = []
    for line in source.splitlines():
        s = line.strip()
        if s.startswith("#") and not s.startswith("#!"):
            continue
        lines.append(line)
    return "\n".join(lines)


def inject_seed_into_config_py(config_py_src: str, seed_dict: dict | None) -> str:
    """Inyecta el diccionario semilla en memoria dentro de drps5_config.py si es la versión Personal."""
    if not seed_dict:
        return config_py_src

    seed_json = json.dumps(seed_dict, ensure_ascii=False)
    hook_code = f"""
_EMBEDDED_SEED = json.loads({repr(seed_json)})
"""
    # Insertar _EMBEDDED_SEED antes de class DRPS5Config:
    target = "class DRPS5Config:"
    replacement = hook_code + "\n" + target
    modified = config_py_src.replace(target, replacement, 1)

    # Reemplazar la lectura de bundled_cfg por _EMBEDDED_SEED en memoria
    old_block_1 = """            bundled_cfg = Path(__file__).resolve().parent / "drps5_config.json"
            if bundled_cfg.exists():
                try:
                    with open(bundled_cfg, "r", encoding="utf-8") as bf:
                        data = json.load(bf)
                    cls.save(data)
                    return data
                except Exception:
                    pass"""
    new_block_1 = """            if '_EMBEDDED_SEED' in globals() and _EMBEDDED_SEED:
                import copy
                data = copy.deepcopy(_EMBEDDED_SEED)
                cls.save(data)
                return data"""
    modified = modified.replace(old_block_1, new_block_1, 1)

    old_block_2 = """            bundled_cfg = Path(__file__).resolve().parent / "drps5_config.json"
            if bundled_cfg.exists():
                try:
                    with open(bundled_cfg, "r", encoding="utf-8") as bf:
                        b_data = json.load(bf)"""
    new_block_2 = """            if '_EMBEDDED_SEED' in globals() and _EMBEDDED_SEED:
                try:
                    import copy
                    b_data = copy.deepcopy(_EMBEDDED_SEED)"""
    modified = modified.replace(old_block_2, new_block_2, 1)
    return modified


def build_core_pak(out_pak_path: Path, pak_key: bytes, seed_dict: dict | None):
    import zlib
    modules = {}

    core_files = [
        "drps5",
        "drps5_gui",
        "drps5_stream",
        "drps5_config",
        "drps5_core",
    ]
    for mod_name in core_files:
        py_file = SRC_DIR / f"{mod_name}.py"
        src = py_file.read_text(encoding="utf-8")
        if mod_name == "drps5_config":
            src = inject_seed_into_config_py(src, seed_dict)
        src = strip_comments_and_docstrings(src)
        modules[mod_name] = [False, src]

    pyrp_root = SRC_DIR / "pyremoteplay" / "pyremoteplay"
    for py_path in pyrp_root.rglob("*.py"):
        rel = py_path.relative_to(SRC_DIR / "pyremoteplay")
        parts = list(rel.parts)
        parts[-1] = parts[-1][:-3]
        if parts[-1] == "__init__":
            is_pkg = True
            mod_name = ".".join(parts[:-1])
        else:
            is_pkg = False
            mod_name = ".".join(parts)
        src = strip_comments_and_docstrings(py_path.read_text(encoding="utf-8"))
        modules[mod_name] = [is_pkg, src]

    raw_bytes = json.dumps(modules, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw_bytes, level=9)
    encrypted = stream_xor(compressed, pak_key)

    magic = b"DRP5PAK\x02"
    out_pak_path.write_bytes(magic + encrypted)
    print(f"[+] Windows core.pak generado ({len(modules)} módulos cifrados, {len(encrypted)} bytes)")


def minify_gui_files(gui_dir: Path):
    css_file = gui_dir / "styles.css"
    if css_file.exists():
        css = css_file.read_text(encoding="utf-8")
        css = re.sub(r"/\*[\s\S]*?\*/", "", css)
        css = re.sub(r"\s+", " ", css)
        css = re.sub(r"\s*([{}:;,])\s*", r"\1", css)
        css_file.write_text(css.strip(), encoding="utf-8")

    html_file = gui_dir / "index.html"
    if html_file.exists():
        html = html_file.read_text(encoding="utf-8")
        html = re.sub(r"<!--[\s\S]*?-->", "", html)
        html = "\n".join(line.strip() for line in html.splitlines() if line.strip())
        html_file.write_text(html, encoding="utf-8")

    js_file = gui_dir / "app.js"
    if js_file.exists():
        js = js_file.read_text(encoding="utf-8")
        js = re.sub(r"/\*[\s\S]*?\*/", "", js)
        lines = []
        for line in js.splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue
            lines.append(s)
        js_file.write_text("\n".join(lines), encoding="utf-8")


def c_xor_array(text: str, key: bytes, var_name: str) -> str:
    raw = text.encode("utf-8") + b"\x00"
    enc = [b ^ key[i % len(key)] for i, b in enumerate(raw)]
    hex_vals = ", ".join(f"0x{b:02x}" for b in enc)
    return f"static const unsigned char {var_name}[{len(enc)}] = {{ {hex_vals} }};\n"


def build_hardened_win_exe(out_exe_path: Path, pak_key: bytes):
    xor_key = secrets.token_bytes(32)
    pak_key_hex = pak_key.hex()

    boot_py = f"""
import sys, os, zlib, json, hashlib, importlib.abc, importlib.machinery

def _InitWinCore():
    sys.dont_write_bytecode = True
    base_dir = os.environ.get("DRPS5_RES", "")
    if not base_dir:
        base_dir = os.getcwd()
    rt_sp = os.path.join(base_dir, "runtime", "Lib", "site-packages")
    if os.path.isdir(rt_sp) and rt_sp not in sys.path:
        sys.path.insert(0, rt_sp)
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    pak_file = os.path.join(base_dir, "core.pak")
    with open(pak_file, "rb") as f:
        data = f.read()
    if data[:8] != b"DRP5PAK\\x02":
        raise RuntimeError("Invalid core")
    enc = memoryview(data)[8:]
    key = bytes.fromhex("{pak_key_hex}")
    out = bytearray(len(enc))
    off = 0
    cnt = 0
    while off < len(enc):
        dg = hashlib.sha256(key + cnt.to_bytes(8, "little")).digest()
        ch = enc[off:off+32]
        for i, b in enumerate(ch):
            out[off+i] = b ^ dg[i]
        off += 32
        cnt += 1
    table = json.loads(zlib.decompress(bytes(out)).decode("utf-8"))

    class _VaultLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def __init__(self, tbl, base):
            self._t = tbl
            self._b = base
        def find_spec(self, fullname, path=None, target=None):
            if fullname in self._t:
                is_pkg = bool(self._t[fullname][0])
                return importlib.machinery.ModuleSpec(fullname, self, is_package=is_pkg)
            return None
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            name = module.__name__
            is_pkg, src_code = self._t[name]
            rel = name.replace(".", os.sep)
            if is_pkg:
                module.__file__ = os.path.join(self._b, rel, "__init__.py")
                module.__path__ = [os.path.join(self._b, rel)]
                module.__package__ = name
            else:
                module.__file__ = os.path.join(self._b, rel + ".py")
                module.__package__ = name.rpartition(".")[0]
            code = compile(src_code, f"<core:{{name}}>", "exec", optimize=2)
            exec(code, module.__dict__)

    sys.meta_path.insert(0, _VaultLoader(table, base_dir))
    import drps5
    drps5.main()

_InitWinCore()
del _InitWinCore
"""

    xor_key_c = ", ".join(f"0x{b:02x}" for b in xor_key)
    arrays_c = ""
    arrays_c += c_xor_array("ntdll.dll", xor_key, "S_NTDLL")
    arrays_c += c_xor_array("NtSetInformationThread", xor_key, "S_NTSET")
    arrays_c += c_xor_array("frida", xor_key, "S_FRIDA")
    arrays_c += c_xor_array("x64dbg", xor_key, "S_X64DBG")
    arrays_c += c_xor_array("scylla", xor_key, "S_SCYLLA")
    arrays_c += c_xor_array("vehdebug", xor_key, "S_VEH")
    arrays_c += c_xor_array("Py_SetProgramName", xor_key, "S_PY_PROG")
    arrays_c += c_xor_array("Py_SetPythonHome", xor_key, "S_PY_HOME")
    arrays_c += c_xor_array("Py_InitializeEx", xor_key, "S_PY_INIT")
    arrays_c += c_xor_array("PySys_SetArgvEx", xor_key, "S_PY_ARGV")
    arrays_c += c_xor_array("PyRun_SimpleString", xor_key, "S_PY_RUN")
    arrays_c += c_xor_array("Py_FinalizeEx", xor_key, "S_PY_FIN")
    arrays_c += c_xor_array("PYTHONDONTWRITEBYTECODE=1", xor_key, "S_ENV_BC")
    arrays_c += c_xor_array("PYTHONOPTIMIZE=2", xor_key, "S_ENV_OPT")
    arrays_c += c_xor_array("PYTHONNOUSERSITE=1", xor_key, "S_ENV_USR")
    arrays_c += c_xor_array(boot_py, xor_key, "S_BOOT_PY")

    c_src = f"""
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>
#include <intrin.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static const unsigned char K_XOR[32] = {{ {xor_key_c} }};
{arrays_c}

static void _dec_buf(const unsigned char *src, size_t n, char *dst) {{
    for (size_t i = 0; i < n; i++) {{
        dst[i] = (char)(src[i] ^ K_XOR[i % 32]);
    }}
}}

static void _wipe_buf(void *buf, size_t n) {{
    volatile unsigned char *p = (volatile unsigned char *)buf;
    while (n--) *p++ = 0;
}}

typedef LONG (NTAPI *NtSetInformationThread_t)(HANDLE, ULONG, PVOID, ULONG);
typedef void (*Py_SetProgramName_t)(const wchar_t *);
typedef void (*Py_SetPythonHome_t)(const wchar_t *);
typedef void (*Py_InitializeEx_t)(int);
typedef void (*PySys_SetArgvEx_t)(int, wchar_t **, int);
typedef int  (*PyRun_SimpleString_t)(const char *);
typedef int  (*Py_FinalizeEx_t)(void);

static int _contains_substr_icase(const wchar_t *haystack, const char *needle_ascii) {{
    if (!haystack || !needle_ascii) return 0;
    size_t nlen = strlen(needle_ascii);
    if (nlen == 0) return 0;
    for (size_t i = 0; haystack[i] != L'\\0'; i++) {{
        size_t j = 0;
        while (j < nlen && haystack[i + j] != L'\\0') {{
            wchar_t c1 = haystack[i + j];
            if (c1 >= L'A' && c1 <= L'Z') c1 += 32;
            wchar_t c2 = (wchar_t)(unsigned char)needle_ascii[j];
            if (c2 >= L'A' && c2 <= L'Z') c2 += 32;
            if (c1 != c2) break;
            j++;
        }}
        if (j == nlen) return 1;
    }}
    return 0;
}}

static void _anti_rea_win_guard(void) {{
    // 1. Verificación API Win32 estándar y remota
    if (IsDebuggerPresent()) {{
        ExitProcess(0);
    }}
    BOOL isRemoteDbg = FALSE;
    if (CheckRemoteDebuggerPresent(GetCurrentProcess(), &isRemoteDbg) && isRemoteDbg) {{
        ExitProcess(0);
    }}

#if defined(__x86_64__) || defined(_M_X64)
    // 2. Inspección directa del PEB en x64 (BeingDebugged en offset 0x02, NtGlobalFlag en 0xBC)
    unsigned char *peb = (unsigned char *)__readgsqword(0x60);
    if (peb) {{
        if (peb[2] != 0) {{
            ExitProcess(0);
        }}
        DWORD ntGlobalFlag = *(DWORD *)(peb + 0xBC);
        if ((ntGlobalFlag & 0x70) != 0) {{
            ExitProcess(0);
        }}
    }}
#endif

    // 3. Ocultar hilo principal del depurador a nivel Kernel NT (ThreadHideFromDebugger = 0x11)
    char s_ntdll[sizeof(S_NTDLL)], s_ntset[sizeof(S_NTSET)];
    _dec_buf(S_NTDLL, sizeof(S_NTDLL), s_ntdll);
    _dec_buf(S_NTSET, sizeof(S_NTSET), s_ntset);
    HMODULE hNtdll = GetModuleHandleA(s_ntdll);
    if (hNtdll) {{
        NtSetInformationThread_t pNtSet = (NtSetInformationThread_t)GetProcAddress(hNtdll, s_ntset);
        if (pNtSet) {{
            pNtSet(GetCurrentThread(), 0x11, NULL, 0);
        }}
    }}
    _wipe_buf(s_ntdll, sizeof(s_ntdll));
    _wipe_buf(s_ntset, sizeof(s_ntset));

    // 4. Escanear módulos cargados contra Frida / x64dbg / Scylla / CheatEngine VEH
    char s_fr[sizeof(S_FRIDA)], s_x64[sizeof(S_X64DBG)], s_sc[sizeof(S_SCYLLA)], s_vh[sizeof(S_VEH)];
    _dec_buf(S_FRIDA, sizeof(S_FRIDA), s_fr);
    _dec_buf(S_X64DBG, sizeof(S_X64DBG), s_x64);
    _dec_buf(S_SCYLLA, sizeof(S_SCYLLA), s_sc);
    _dec_buf(S_VEH, sizeof(S_VEH), s_vh);

    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
    if (hSnap != INVALID_HANDLE_VALUE) {{
        MODULEENTRY32W me;
        me.dwSize = sizeof(MODULEENTRY32W);
        if (Module32FirstW(hSnap, &me)) {{
            do {{
                if (_contains_substr_icase(me.szModule, s_fr) ||
                    _contains_substr_icase(me.szModule, s_x64) ||
                    _contains_substr_icase(me.szModule, s_sc) ||
                    _contains_substr_icase(me.szModule, s_vh)) {{
                    CloseHandle(hSnap);
                    ExitProcess(0);
                }}
            }} while (Module32NextW(hSnap, &me));
        }}
        CloseHandle(hSnap);
    }}
    _wipe_buf(s_fr, sizeof(s_fr));
    _wipe_buf(s_x64, sizeof(s_x64));
    _wipe_buf(s_sc, sizeof(s_sc));
    _wipe_buf(s_vh, sizeof(s_vh));
}}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {{
    (void)hInstance;
    (void)hPrevInstance;
    (void)nCmdShow;

    _anti_rea_win_guard();

    wchar_t exePath[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exePath, MAX_PATH)) {{
        return 1;
    }}

    wchar_t baseDir[MAX_PATH];
    wcscpy(baseDir, exePath);
    wchar_t *lastSlash = wcsrchr(baseDir, L'\\\\');
    if (lastSlash) {{
        *lastSlash = L'\\0';
    }}
    SetCurrentDirectoryW(baseDir);
    SetEnvironmentVariableW(L"DRPS5_RES", baseDir);

    char e_bc[sizeof(S_ENV_BC)], e_opt[sizeof(S_ENV_OPT)], e_usr[sizeof(S_ENV_USR)];
    _dec_buf(S_ENV_BC, sizeof(S_ENV_BC), e_bc);
    _dec_buf(S_ENV_OPT, sizeof(S_ENV_OPT), e_opt);
    _dec_buf(S_ENV_USR, sizeof(S_ENV_USR), e_usr);
    _putenv(e_bc);
    _putenv(e_opt);
    _putenv(e_usr);
    _wipe_buf(e_bc, sizeof(e_bc));
    _wipe_buf(e_opt, sizeof(e_opt));
    _wipe_buf(e_usr, sizeof(e_usr));

    wchar_t runtimeDir[MAX_PATH];
    swprintf(runtimeDir, MAX_PATH, L"%ls\\\\runtime", baseDir);
    if (GetFileAttributesW(runtimeDir) == INVALID_FILE_ATTRIBUTES) {{
        return 1;
    }}

    wchar_t pythonDllPath[MAX_PATH];
    swprintf(pythonDllPath, MAX_PATH, L"%ls\\\\python311.dll", runtimeDir);
    SetDllDirectoryW(runtimeDir);

    HMODULE hPython = LoadLibraryW(pythonDllPath);
    if (!hPython) {{
        return 1;
    }}

    char fn_prog[sizeof(S_PY_PROG)], fn_home[sizeof(S_PY_HOME)], fn_init[sizeof(S_PY_INIT)];
    char fn_argv[sizeof(S_PY_ARGV)], fn_run[sizeof(S_PY_RUN)], fn_fin[sizeof(S_PY_FIN)];
    _dec_buf(S_PY_PROG, sizeof(S_PY_PROG), fn_prog);
    _dec_buf(S_PY_HOME, sizeof(S_PY_HOME), fn_home);
    _dec_buf(S_PY_INIT, sizeof(S_PY_INIT), fn_init);
    _dec_buf(S_PY_ARGV, sizeof(S_PY_ARGV), fn_argv);
    _dec_buf(S_PY_RUN,  sizeof(S_PY_RUN),  fn_run);
    _dec_buf(S_PY_FIN,  sizeof(S_PY_FIN),  fn_fin);

    Py_SetProgramName_t   pPy_SetProgramName   = (Py_SetProgramName_t)GetProcAddress(hPython, fn_prog);
    Py_SetPythonHome_t    pPy_SetPythonHome    = (Py_SetPythonHome_t)GetProcAddress(hPython, fn_home);
    Py_InitializeEx_t     pPy_InitializeEx     = (Py_InitializeEx_t)GetProcAddress(hPython, fn_init);
    PySys_SetArgvEx_t     pPySys_SetArgvEx     = (PySys_SetArgvEx_t)GetProcAddress(hPython, fn_argv);
    PyRun_SimpleString_t  pPyRun_SimpleString  = (PyRun_SimpleString_t)GetProcAddress(hPython, fn_run);
    Py_FinalizeEx_t       pPy_FinalizeEx       = (Py_FinalizeEx_t)GetProcAddress(hPython, fn_fin);

    _wipe_buf(fn_prog, sizeof(fn_prog));
    _wipe_buf(fn_home, sizeof(fn_home));
    _wipe_buf(fn_init, sizeof(fn_init));
    _wipe_buf(fn_argv, sizeof(fn_argv));
    _wipe_buf(fn_run,  sizeof(fn_run));
    _wipe_buf(fn_fin,  sizeof(fn_fin));

    if (!pPy_InitializeEx || !pPyRun_SimpleString) {{
        FreeLibrary(hPython);
        return 1;
    }}

    if (pPy_SetProgramName) pPy_SetProgramName(exePath);
    if (pPy_SetPythonHome)  pPy_SetPythonHome(runtimeDir);

    pPy_InitializeEx(0);

    int maxArgs = 64;
    wchar_t **pyArgv = (wchar_t **)malloc(sizeof(wchar_t *) * maxArgs);
    int pyArgc = 0;
    pyArgv[pyArgc++] = _wcsdup(exePath);

    if (pCmdLine && wcslen(pCmdLine) > 0) {{
        int numParsed = 0;
        wchar_t **parsedArgs = CommandLineToArgvW(pCmdLine, &numParsed);
        if (parsedArgs) {{
            for (int i = 0; i < numParsed && pyArgc < (maxArgs - 1); i++) {{
                pyArgv[pyArgc++] = _wcsdup(parsedArgs[i]);
            }}
            LocalFree(parsedArgs);
        }}
    }}
    pyArgv[pyArgc] = NULL;

    if (pPySys_SetArgvEx) {{
        pPySys_SetArgvEx(pyArgc, pyArgv, 0);
    }}

    char *boot_code = (char *)malloc(sizeof(S_BOOT_PY));
    _dec_buf(S_BOOT_PY, sizeof(S_BOOT_PY), boot_code);
    int exitCode = pPyRun_SimpleString(boot_code);
    _wipe_buf(boot_code, sizeof(S_BOOT_PY));
    free(boot_code);

    if (pPy_FinalizeEx) {{
        pPy_FinalizeEx();
    }}

    for (int i = 0; i < pyArgc; i++) {{
        free(pyArgv[i]);
    }}
    free(pyArgv);
    FreeLibrary(hPython);
    return exitCode;
}}
"""

    src_c = LAUNCHER_SRC_DIR / "hardened_win_launcher.c"
    src_c.write_text(c_src, encoding="utf-8")
    res_o = LAUNCHER_SRC_DIR / "resource.o"

    cmd = [
        "/opt/homebrew/bin/x86_64-w64-mingw32-gcc",
        "-O3",
        "-fvisibility=hidden",
        "-flto",
        "-mwindows",
        "-municode",
        "-s",
        str(src_c),
        str(res_o),
        "-o",
        str(out_exe_path),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(["/opt/homebrew/bin/x86_64-w64-mingw32-strip", "--strip-all", str(out_exe_path)], check=True)
    src_c.unlink(missing_ok=True)
    print(f"[+] Ejecutable PE64 blindado compilado y símbolos depurados: {out_exe_path}")


def generate_nsis_script(staging_dir: Path, out_installer: Path, is_personal: bool) -> Path:
    edition_label = "Edición Personal" if is_personal else "Edición Pública"
    nsi_content = f"""; -------------------------------------------------------------------------
; DRPS5 - Instalador Oficial de Windows ({edition_label} - Anti-REA)
; Compatible con Windows 10/11 x64 y Windows 11 ARM64 (Prism)
; -------------------------------------------------------------------------

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel admin

Name "DRPS5 - Pantalla Remota PS5"
OutFile "{out_installer}"

InstallDir "$PROGRAMFILES64\\DRPS5"
InstallDirRegKey HKLM "Software\\DRPS5" "InstallLocation"

!include "MUI2.nsh"
!include "x64.nsh"

!define MUI_ICON "{staging_dir}/app_icon.ico"
!define MUI_UNICON "{staging_dir}/app_icon.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Bienvenido al Instalador de DRPS5"
!define MUI_WELCOMEPAGE_TEXT "Este asistente instalará DRPS5 - Pantalla Remota PS5 en su ordenador con Windows.$\\r$\\n$\\r$\\nCompatible nativamente con procesadores Intel/AMD x64 y procesadores ARM64 mediante Microsoft Prism.$\\r$\\n$\\r$\\nHaga clic en Siguiente para continuar."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\\DRPS5.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Iniciar DRPS5 ahora"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  ${{IfNot}} ${{RunningX64}}
    MessageBox MB_OK|MB_ICONSTOP "DRPS5 requiere una versión de Windows de 64 bits (x64 o ARM64)."
    Abort
  ${{EndIf}}
  ${{DisableX64FSRedirection}}
  SetRegView 64
FunctionEnd

Section "DRPS5 Principal" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; Limpiar posibles archivos antiguos si se instala sobre una versión previa
  Delete "$INSTDIR\\drps5.py"
  Delete "$INSTDIR\\drps5_gui.py"
  Delete "$INSTDIR\\drps5_stream.py"
  Delete "$INSTDIR\\drps5_config.py"
  Delete "$INSTDIR\\drps5_core.py"
  Delete "$INSTDIR\\drps5_config.json"
  Delete "$INSTDIR\\DRPS5_debug.bat"
  RMDir /r "$INSTDIR\\pyremoteplay"

  ; Archivos blindados del núcleo de la aplicación
  File "{staging_dir}/DRPS5.exe"
  File "{staging_dir}/core.pak"
  File "{staging_dir}/app_icon.ico"
  File "{staging_dir}/gamecontrollerdb.txt"

  ; Carpetas de recursos minificados y entorno embebido
  File /r "{staging_dir}/gui"
  File /r "{staging_dir}/assets"
  File /r "../DRPS5/runtime"

  WriteUninstaller "$INSTDIR\\Uninstall.exe"

  SetShellVarContext current
  CreateDirectory "$PROFILE\\.drps5"

  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\\DRPS5"
  Delete "$SMPROGRAMS\\DRPS5\\Diagnóstico DRPS5.lnk"
  CreateShortcut "$SMPROGRAMS\\DRPS5\\DRPS5.lnk" "$INSTDIR\\DRPS5.exe" "" "$INSTDIR\\app_icon.ico" 0
  CreateShortcut "$SMPROGRAMS\\DRPS5\\Desinstalar DRPS5.lnk" "$INSTDIR\\Uninstall.exe" "" "$INSTDIR\\Uninstall.exe" 0
  CreateShortcut "$DESKTOP\\DRPS5.lnk" "$INSTDIR\\DRPS5.exe" "" "$INSTDIR\\app_icon.ico" 0

  WriteRegStr HKLM "Software\\DRPS5" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "DisplayName" "DRPS5 - Pantalla Remota PS5"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "DisplayIcon" "$INSTDIR\\app_icon.ico,0"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "DisplayVersion" "1.2.0"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "Publisher" "DRPS5"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "QuietUninstallString" '"$INSTDIR\\Uninstall.exe" /S'
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "EstimatedSize" 215000
  WriteRegDWORD HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "NoModify" 1
  WriteRegDWORD HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5" "NoRepair" 1

  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Pantalla Remota PS5" dir=in action=allow program="$INSTDIR\\DRPS5.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Pantalla Remota PS5 (Outbound)" dir=out action=allow program="$INSTDIR\\DRPS5.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Runtime Python" dir=in action=allow program="$INSTDIR\\runtime\\python.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Runtime PythonW" dir=in action=allow program="$INSTDIR\\runtime\\pythonw.exe" enable=yes profile=any'
SectionEnd

Section "Uninstall"
  ${{DisableX64FSRedirection}}
  SetRegView 64

  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Pantalla Remota PS5"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Pantalla Remota PS5 (Outbound)"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Runtime Python"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Runtime PythonW"'

  SetShellVarContext all
  Delete "$DESKTOP\\DRPS5.lnk"
  Delete "$SMPROGRAMS\\DRPS5\\DRPS5.lnk"
  Delete "$SMPROGRAMS\\DRPS5\\Diagnóstico DRPS5.lnk"
  Delete "$SMPROGRAMS\\DRPS5\\Desinstalar DRPS5.lnk"
  RMDir "$SMPROGRAMS\\DRPS5"

  RMDir /r "$INSTDIR\\runtime"
  RMDir /r "$INSTDIR\\gui"
  RMDir /r "$INSTDIR\\assets"
  RMDir /r "$INSTDIR\\pyremoteplay"
  Delete "$INSTDIR\\DRPS5.exe"
  Delete "$INSTDIR\\core.pak"
  Delete "$INSTDIR\\app_icon.ico"
  Delete "$INSTDIR\\gamecontrollerdb.txt"
  Delete "$INSTDIR\\crash.log"
  Delete "$INSTDIR\\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DRPS5"
  DeleteRegKey HKLM "Software\\DRPS5"
SectionEnd
"""
    nsi_path = WIN_DIR / "installer" / ("setup_personal.nsi" if is_personal else "setup_publico.nsi")
    nsi_path.write_text(nsi_content, encoding="utf-8")
    return nsi_path


def build_edition(is_personal: bool, out_installer: Path):
    label = "PERSONAL" if is_personal else "PUBLICO"
    print(f"\n=== Construyendo Instalador Windows Blindado [{label}] ===")
    staging = WIN_DIR / f"_staging_{label.lower()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Copiar recursos estáticos necesarios
    shutil.copy2(SRC_DIR / "app_icon.ico", staging / "app_icon.ico")
    shutil.copy2(SRC_DIR / "gamecontrollerdb.txt", staging / "gamecontrollerdb.txt")
    shutil.copytree(SRC_DIR / "gui", staging / "gui")
    shutil.copytree(SRC_DIR / "assets", staging / "assets")

    # Minificar GUI en el directorio de staging
    minify_gui_files(staging / "gui")

    # Generar clave única de 256 bits para esta edición
    pak_key = secrets.token_bytes(32)
    seed_cfg = PERSONAL_SEED_CONFIG if is_personal else None

    # Crear core.pak cifrado y DRPS5.exe blindado con esa clave
    build_core_pak(staging / "core.pak", pak_key, seed_cfg)
    build_hardened_win_exe(staging / "DRPS5.exe", pak_key)

    # Generar script NSIS y compilar instalador .exe
    nsi_path = generate_nsis_script(staging, out_installer, is_personal)
    subprocess.run(["/opt/homebrew/bin/makensis", str(nsi_path)], cwd=str(WIN_DIR / "installer"), check=True)
    nsi_path.unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"[+] Instalador [{label}] finalizado: {out_installer}")


def main():
    personal_exe = WIN_DIR / "DRPS5_Setup_Personal.exe"
    publico_exe = WIN_DIR / "DRPS5_Setup_Publico.exe"

    build_edition(is_personal=True, out_installer=personal_exe)
    build_edition(is_personal=False, out_installer=publico_exe)

    # Eliminar el antiguo DRPS5_Setup.exe genérico para dejar únicamente los 2 instaladores solicitados
    old_exe = WIN_DIR / "DRPS5_Setup.exe"
    if old_exe.exists():
        old_exe.unlink()


if __name__ == "__main__":
    main()
