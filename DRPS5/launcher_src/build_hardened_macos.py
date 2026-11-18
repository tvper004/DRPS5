#!/usr/bin/env python3
"""
Constructor de DRPS5 para macOS con blindaje anti-REA:
1. /Applications/DRPS5.app -> Versión Personal del usuario con su PS5 vinculada (192.168.1.100 / ).
2. /Users/rleon/Documents/PXPLAY/MacOS/DRPS5.dmg -> Versión Pública limpia sin ninguna PS5 vinculada.
"""

from __future__ import annotations
import hashlib
import json
import marshal
import os
import re
import secrets
import shutil
import subprocess
import zlib
from pathlib import Path

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
SRC_DIR = WORKSPACE_DIR / "DRPS5"
MACOS_OUT_DIR = WORKSPACE_DIR / "MacOS"
PUBLIC_APP_OUT = MACOS_OUT_DIR / "DRPS5.app"
PUBLIC_DMG_OUT = MACOS_OUT_DIR / "DRPS5.dmg"
PERSONAL_APP_OUT = Path("/Applications/DRPS5.app")

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
            "connection_mode": "local",
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


def prepare_config_py(config_py_src: str, is_personal: bool) -> str:
    if not is_personal:
        # La edición pública usa un archivo de configuración limpio independiente para no leer ni alterar credenciales personales
        return config_py_src.replace(
            'CONFIG_FILE = CONFIG_DIR / "drps5_config.json"',
            'CONFIG_FILE = CONFIG_DIR / "drps5_public_config.json"',
            1,
        )

    seed_json = json.dumps(PERSONAL_SEED_CONFIG, ensure_ascii=False)
    hook_code = f"\n_EMBEDDED_SEED = json.loads({repr(seed_json)})\n"
    modified = config_py_src.replace("class DRPS5Config:", hook_code + "class DRPS5Config:", 1)

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


def build_core_pak(resources_dir: Path, pak_key: bytes, is_personal: bool):
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
            src = prepare_config_py(src, is_personal)
        code_obj = compile(src, f"<core:{mod_name}>", "exec", optimize=2)
        modules[mod_name] = (False, marshal.dumps(code_obj))

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
        src = py_path.read_text(encoding="utf-8")
        code_obj = compile(src, f"<core:{mod_name}>", "exec", optimize=2)
        modules[mod_name] = (is_pkg, marshal.dumps(code_obj))

    raw_payload = marshal.dumps(modules)
    compressed = zlib.compress(raw_payload, level=9)
    encrypted = stream_xor(compressed, pak_key)

    pak_path = resources_dir / "core.pak"
    magic = b"DRP5PAK\x01"
    pak_path.write_bytes(magic + encrypted)
    print(f"[+] core.pak generado ({len(modules)} módulos protegidos, {len(encrypted)} bytes, personal={is_personal})")


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


def build_hardened_binary(app_path: Path, pak_key: bytes):
    xor_key = secrets.token_bytes(32)
    pak_key_hex = pak_key.hex()

    boot_py = f"""
import sys, os, zlib, marshal, hashlib, importlib.abc, importlib.machinery

def _InitCore():
    res_dir = os.environ.get("DRPS5_RES", "")
    if not res_dir:
        res_dir = os.getcwd()
    os.environ["RESOURCEPATH"] = res_dir
    if sys.argv:
        sys.argv[0] = os.path.join(res_dir, "drps5.py")
    venv_sp = os.path.join(res_dir, ".venv", "lib", "python3.9", "site-packages")
    if os.path.isdir(venv_sp) and venv_sp not in sys.path:
        sys.path.insert(0, venv_sp)
    if res_dir and res_dir not in sys.path:
        sys.path.insert(0, res_dir)

    pak_file = os.path.join(res_dir, "core.pak")
    with open(pak_file, "rb") as f:
        data = f.read()
    if data[:8] != b"DRP5PAK\\x01":
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
    table = marshal.loads(zlib.decompress(bytes(out)))

    class _VaultLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def __init__(self, tbl, base):
            self._t = tbl
            self._b = base
        def find_spec(self, fullname, path=None, target=None):
            if fullname in self._t:
                is_pkg = self._t[fullname][0]
                return importlib.machinery.ModuleSpec(fullname, self, is_package=is_pkg)
            return None
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            name = module.__name__
            is_pkg, code_bytes = self._t[name]
            rel = name.replace(".", "/")
            if is_pkg:
                module.__file__ = os.path.join(self._b, rel, "__init__.py")
                module.__path__ = [os.path.join(self._b, rel)]
                module.__package__ = name
            else:
                module.__file__ = os.path.join(self._b, rel + ".py")
                module.__package__ = name.rpartition(".")[0]
            code = marshal.loads(code_bytes)
            exec(code, module.__dict__)

    sys.meta_path.insert(0, _VaultLoader(table, res_dir))
    import drps5
    drps5.main()

_InitCore()
del _InitCore
"""

    xor_key_c = ", ".join(f"0x{b:02x}" for b in xor_key)
    arrays_c = ""
    arrays_c += c_xor_array("ptrace", xor_key, "S_PTRACE")
    arrays_c += c_xor_array("DYLD_INSERT_LIBRARIES", xor_key, "S_DYLD_INS")
    arrays_c += c_xor_array("frida", xor_key, "S_FRIDA")
    arrays_c += c_xor_array("cynject", xor_key, "S_CYNJECT")
    arrays_c += c_xor_array("substrate", xor_key, "S_SUBSTRATE")
    arrays_c += c_xor_array("DRPS5", xor_key, "S_APPNAME")
    arrays_c += c_xor_array("DRPS5_RES", xor_key, "S_ENV_RES")
    arrays_c += c_xor_array("DRPS5_BIN", xor_key, "S_ENV_BIN")
    arrays_c += c_xor_array("TK_SILENCE_DEPRECATION", xor_key, "S_ENV_TK")
    arrays_c += c_xor_array("AppIcon.icns", xor_key, "S_ICNS")
    arrays_c += c_xor_array(boot_py, xor_key, "S_BOOT_PY")

    objc_src = f"""
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <sys/types.h>
#include <sys/sysctl.h>
#include <sys/stat.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

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

typedef int (*ptrace_fn_t)(int, pid_t, caddr_t, int);

__attribute__((constructor))
static void _anti_rea_guard(void) {{
    char fn_name[sizeof(S_PTRACE)];
    _dec_buf(S_PTRACE, sizeof(S_PTRACE), fn_name);
    ptrace_fn_t pt = (ptrace_fn_t)dlsym(RTLD_DEFAULT, fn_name);
    _wipe_buf(fn_name, sizeof(fn_name));
    if (pt) {{
        pt(31, 0, 0, 0);
    }}

    int mib[4] = {{ CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid() }};
    struct kinfo_proc info;
    size_t sz = sizeof(info);
    memset(&info, 0, sizeof(info));
    if (sysctl(mib, 4, &info, &sz, NULL, 0) == 0) {{
        if ((info.kp_proc.p_flag & P_TRACED) != 0) {{
            _exit(0);
        }}
    }}

    char dyld_env[sizeof(S_DYLD_INS)];
    _dec_buf(S_DYLD_INS, sizeof(S_DYLD_INS), dyld_env);
    const char *ins = getenv(dyld_env);
    _wipe_buf(dyld_env, sizeof(dyld_env));
    if (ins && ins[0] != '\\0') {{
        _exit(0);
    }}

    char s_fr[sizeof(S_FRIDA)], s_cy[sizeof(S_CYNJECT)], s_su[sizeof(S_SUBSTRATE)];
    _dec_buf(S_FRIDA, sizeof(S_FRIDA), s_fr);
    _dec_buf(S_CYNJECT, sizeof(S_CYNJECT), s_cy);
    _dec_buf(S_SUBSTRATE, sizeof(S_SUBSTRATE), s_su);
    uint32_t count = _dyld_image_count();
    for (uint32_t i = 0; i < count; i++) {{
        const char *img = _dyld_get_image_name(i);
        if (img) {{
            if (strcasestr(img, s_fr) || strcasestr(img, s_cy) || strcasestr(img, s_su)) {{
                _exit(0);
            }}
        }}
    }}
    _wipe_buf(s_fr, sizeof(s_fr));
    _wipe_buf(s_cy, sizeof(s_cy));
    _wipe_buf(s_su, sizeof(s_su));
}}

int main(int argc, char *argv[]) {{
    char app_name[sizeof(S_APPNAME)];
    _dec_buf(S_APPNAME, sizeof(S_APPNAME), app_name);
    setprogname(app_name);
    @autoreleasepool {{
        NSString *nsName = [NSString stringWithUTF8String:app_name];
        [[NSProcessInfo processInfo] setProcessName:nsName];
    }}

    char exec_path[1024];
    uint32_t size = sizeof(exec_path);
    if (_NSGetExecutablePath(exec_path, &size) != 0) {{
        return 1;
    }}

    char real_exec_path[1024];
    if (realpath(exec_path, real_exec_path) == NULL) {{
        strncpy(real_exec_path, exec_path, sizeof(real_exec_path));
    }}

    char macos_dir[1024];
    strncpy(macos_dir, real_exec_path, sizeof(macos_dir));
    char *dir1 = dirname(macos_dir);
    char contents_dir[1024];
    strncpy(contents_dir, dir1, sizeof(contents_dir));
    char *dir2 = dirname(contents_dir);

    char resources_dir[1024];
    snprintf(resources_dir, sizeof(resources_dir), "%s/Resources", dir2);

    const char *home = getenv("HOME");
    if (home) {{
        char log_dir[1024];
        snprintf(log_dir, sizeof(log_dir), "%s/.drps5", home);
        mkdir(log_dir, 0755);
        char log_file[1024];
        snprintf(log_file, sizeof(log_file), "%s/launcher.log", log_dir);
        FILE *flog = freopen(log_file, "a", stdout);
        if (flog) {{
            dup2(fileno(stdout), fileno(stderr));
        }}
    }}

    char k_res[sizeof(S_ENV_RES)], k_bin[sizeof(S_ENV_BIN)], k_tk[sizeof(S_ENV_TK)];
    _dec_buf(S_ENV_RES, sizeof(S_ENV_RES), k_res);
    _dec_buf(S_ENV_BIN, sizeof(S_ENV_BIN), k_bin);
    _dec_buf(S_ENV_TK, sizeof(S_ENV_TK), k_tk);
    setenv(k_res, resources_dir, 1);
    setenv(k_bin, real_exec_path, 1);
    setenv(k_tk, "1", 1);
    _wipe_buf(k_res, sizeof(k_res));
    _wipe_buf(k_bin, sizeof(k_bin));
    _wipe_buf(k_tk, sizeof(k_tk));

    chdir(resources_dir);

    @autoreleasepool {{
        char s_icns[sizeof(S_ICNS)];
        _dec_buf(S_ICNS, sizeof(S_ICNS), s_icns);
        char icns_cand[1024];
        snprintf(icns_cand, sizeof(icns_cand), "%s/%s", resources_dir, s_icns);
        _wipe_buf(s_icns, sizeof(s_icns));
        if (access(icns_cand, F_OK) == 0) {{
            NSString *imgPath = [NSString stringWithUTF8String:icns_cand];
            NSImage *appIcon = [[NSImage alloc] initWithContentsOfFile:imgPath];
            if (appIcon) {{
                [[NSApplication sharedApplication] setApplicationIconImage:appIcon];
                [[[NSApplication sharedApplication] dockTile] display];
            }}
        }}
    }}

    Py_OptimizeFlag = 2;
    Py_DontWriteBytecodeFlag = 1;
    Py_IgnoreEnvironmentFlag = 1;
    Py_NoUserSiteDirectory = 1;

    Py_SetProgramName(L"DRPS5");
    Py_Initialize();

    wchar_t **w_argv = (wchar_t **)malloc((argc + 2) * sizeof(wchar_t *));
    int w_argc = 0;
    w_argv[w_argc++] = Py_DecodeLocale(real_exec_path, NULL);
    for (int i = 1; i < argc; i++) {{
        if (strncmp(argv[i], "-psn", 4) == 0) continue;
        w_argv[w_argc++] = Py_DecodeLocale(argv[i], NULL);
    }}
    w_argv[w_argc] = NULL;
    PySys_SetArgvEx(w_argc, w_argv, 0);

    char *boot_code = (char *)malloc(sizeof(S_BOOT_PY));
    _dec_buf(S_BOOT_PY, sizeof(S_BOOT_PY), boot_code);
    int ret = PyRun_SimpleString(boot_code);
    _wipe_buf(boot_code, sizeof(S_BOOT_PY));
    free(boot_code);
    _wipe_buf(app_name, sizeof(app_name));

    if (Py_FinalizeEx() < 0) {{
        ret = 120;
    }}
    return ret;
}}
"""

    src_m = SRC_DIR / "launcher_src" / "hardened_launcher.m"
    src_m.write_text(objc_src, encoding="utf-8")

    out_bin = app_path / "Contents" / "MacOS" / "DRPS5"
    py_fw = "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9"
    cmd = [
        "clang",
        "-O3",
        "-fvisibility=hidden",
        "-fvisibility-inlines-hidden",
        "-flto",
        "-fobjc-arc",
        f"-I{py_fw}/include/python3.9",
        f"-L{py_fw}/lib",
        "-lpython3.9",
        "-Wl,-rpath,/Library/Developer/CommandLineTools/Library/Frameworks",
        "-Wl,-rpath,/Applications/Xcode.app/Contents/Developer/Library/Frameworks",
        "-framework", "Foundation",
        "-framework", "AppKit",
        "-o", str(out_bin),
        str(src_m),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(["strip", "-S", "-x", str(out_bin)], check=True)
    src_m.unlink(missing_ok=True)


def build_macos_bundle(target_app_path: Path, is_personal: bool):
    ws_app = SRC_DIR / "DRPS5.app"
    ws_res = ws_app / "Contents" / "Resources"
    for f in ["drps5.py", "drps5_gui.py", "drps5_stream.py", "drps5_config.py", "drps5_core.py"]:
        shutil.copy2(SRC_DIR / f, ws_res / f)
    if (ws_res / "gui").exists():
        shutil.rmtree(ws_res / "gui")
    shutil.copytree(SRC_DIR / "gui", ws_res / "gui", dirs_exist_ok=True)
    shutil.copytree(SRC_DIR / "assets", ws_res / "assets", dirs_exist_ok=True)

    if target_app_path.exists():
        shutil.rmtree(target_app_path)
    shutil.copytree(ws_app, target_app_path, symlinks=True)

    out_res = target_app_path / "Contents" / "Resources"
    pak_key = secrets.token_bytes(32)
    build_core_pak(out_res, pak_key, is_personal=is_personal)

    for item in [
        "drps5.py",
        "drps5_gui.py",
        "drps5_stream.py",
        "drps5_config.py",
        "drps5_core.py",
        "drps5",
        "launch_drps5.sh",
        "README.md",
        ".DS_Store",
    ]:
        p = out_res / item
        if p.exists():
            p.unlink()

    if (out_res / "pyremoteplay").exists():
        shutil.rmtree(out_res / "pyremoteplay")

    for ds in target_app_path.rglob(".DS_Store"):
        ds.unlink(missing_ok=True)

    minify_gui_files(out_res / "gui")
    build_hardened_binary(target_app_path, pak_key)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(target_app_path)], check=True)
    print(f"[+] Bundle macOS blindado listo (personal={is_personal}): {target_app_path}")


def main():
    MACOS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Asegurar que ~/.drps5/drps5_config.json en esta Mac tenga el vínculo PS5 intacto
    cfg_dir = Path.home() / ".drps5"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "drps5_config.json").write_text(
        json.dumps(PERSONAL_SEED_CONFIG, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Limpiar posible config pública previa si existe en esta Mac
    pub_cfg = cfg_dir / "drps5_public_config.json"
    if pub_cfg.exists():
        pub_cfg.unlink()

    # 1. Construir la aplicación PERSONAL instalada en /Applications/DRPS5.app (con PS5 vinculada)
    build_macos_bundle(PERSONAL_APP_OUT, is_personal=True)

    # También sincronizar DRPS5/DRPS5.app del workspace con la versión personal
    ws_app_copy = SRC_DIR / "DRPS5_Personal.app"
    if ws_app_copy.exists():
        shutil.rmtree(ws_app_copy)

    # 2. Construir la aplicación PÚBLICA en /Users/rleon/Documents/PXPLAY/MacOS/DRPS5.app y DRPS5.dmg (sin PS5 vinculada)
    build_macos_bundle(PUBLIC_APP_OUT, is_personal=False)

    staging_dir = MACOS_OUT_DIR / "_dmg_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    shutil.copytree(PUBLIC_APP_OUT, staging_dir / "DRPS5.app", symlinks=True)
    os.symlink("/Applications", staging_dir / "Applications")

    if PUBLIC_DMG_OUT.exists():
        PUBLIC_DMG_OUT.unlink()

    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "DRPS5 - Pantalla Remota PS5",
            "-srcfolder",
            str(staging_dir),
            "-ov",
            "-format",
            "UDZO",
            str(PUBLIC_DMG_OUT),
        ],
        check=True,
    )
    shutil.rmtree(staging_dir, ignore_errors=True)
    print(f"[+] DMG Público generado con éxito: {PUBLIC_DMG_OUT}")


if __name__ == "__main__":
    main()
