#!/usr/bin/env python3
"""
Constructor de instaladores macOS Universal (Apple Silicon M + Intel x86_64 + Metal/GPU) para DRPS5 V2:
1. /Users/rleon/Documents/PXPLAY/MacOS/V2/DRPS5_V2_Personal.dmg
2. /Users/rleon/Documents/PXPLAY/MacOS/V2/DRPS5_V2_Publico.dmg
"""

from __future__ import annotations
import ast
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import zipfile
import zlib
from pathlib import Path

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
MAC_V1_APP = WORKSPACE_DIR / "MacOS" / "DRPS5.app"
MAC_V2_DIR = WORKSPACE_DIR / "MacOS" / "V2"
V2_CORE_DIR = WORKSPACE_DIR / "DRPS5" / "v2_core"
GUI_V2_DIR = WORKSPACE_DIR / "DRPS5" / "gui_v2"
PYREMOTEPLAY_DIR = WORKSPACE_DIR / "DRPS5" / "pyremoteplay"
X86_WHEELS_DIR = Path("/tmp/test_x86_wheels")

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


def strip_docstrings(src: str) -> str:
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    node.body[0].value.value = ""
        return ast.unparse(tree)
    except Exception:
        return src



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
        modules[mod_name] = strip_docstrings(text)

    for py_file in PYREMOTEPLAY_DIR.rglob("*.py"):
        rel = py_file.relative_to(PYREMOTEPLAY_DIR)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            mod_name = ".".join(parts[:-1])
        else:
            mod_name = ".".join(parts)
        if mod_name:
            modules[mod_name] = strip_docstrings(py_file.read_text(encoding="utf-8"))

    raw_json = json.dumps(modules, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw_json, level=9)

    # SHA-256 stream cipher
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


def compile_cas_dylib(out_dylib: Path):
    c_src = """
#include <stdint.h>
#include <string.h>

void drps5_cas_rgb24(const uint8_t * __restrict src, uint8_t * __restrict dst, int w, int h, int stride, int strength_q8) {
    if (w < 3 || h < 3 || strength_q8 <= 0) {
        for (int y = 0; y < h; y++) memcpy(dst + y * w * 3, src + y * stride, w * 3);
        return;
    }
    memcpy(dst, src, w * 3);
    memcpy(dst + (h - 1) * w * 3, src + (h - 1) * stride, w * 3);
    for (int y = 1; y < h - 1; y++) {
        const uint8_t *row_u = src + (y - 1) * stride;
        const uint8_t *row_c = src + y * stride;
        const uint8_t *row_d = src + (y + 1) * stride;
        uint8_t *out = dst + y * w * 3;
        out[0] = row_c[0]; out[1] = row_c[1]; out[2] = row_c[2];
        for (int x = 1; x < w - 1; x++) {
            int i = x * 3;
            for (int c = 0; c < 3; c++) {
                int v_u = row_u[i + c];
                int v_d = row_d[i + c];
                int v_l = row_c[i - 3 + c];
                int v_r = row_c[i + 3 + c];
                int v_c = row_c[i + c];
                int mn = v_c;
                if (v_u < mn) mn = v_u; if (v_d < mn) mn = v_d; if (v_l < mn) mn = v_l; if (v_r < mn) mn = v_r;
                int mx = v_c;
                if (v_u > mx) mx = v_u; if (v_d > mx) mx = v_d; if (v_l > mx) mx = v_l; if (v_r > mx) mx = v_r;
                int amp = (mn < (255 - mx)) ? mn : (255 - mx);
                int w_q8 = (amp * strength_q8) >> 8;
                int lap = (4 * v_c) - (v_u + v_d + v_l + v_r);
                int res = v_c + ((lap * w_q8) >> 9);
                out[i + c] = (uint8_t)(res < 0 ? 0 : (res > 255 ? 255 : res));
            }
        }
        int last = (w - 1) * 3;
        out[last] = row_c[last]; out[last + 1] = row_c[last + 1]; out[last + 2] = row_c[last + 2];
    }
}
"""
    c_file = out_dylib.parent / "drps5_cas.c"
    c_file.write_text(c_src, encoding="utf-8")
    subprocess.run([
        "clang", "-O3", "-arch", "arm64", "-arch", "x86_64",
        "-mmacosx-version-min=11.0", "-dynamiclib",
        str(c_file), "-o", str(out_dylib)
    ], check=True)
    c_file.unlink()


def compile_universal_launcher(out_bin: Path, pak_key: bytes, is_personal: bool):
    xor_mask = secrets.token_bytes(32)
    enc_key = bytes(pak_key[i] ^ xor_mask[i] for i in range(32))

    def c_arr(b: bytes) -> str:
        return ", ".join(f"0x{x:02x}" for x in b)

    edition_val = "personal" if is_personal else "public"
    c_src = f"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <unistd.h>

typedef void (*py_init_fn)(void);
typedef int (*py_run_fn)(const char *);
typedef void (*py_fin_fn)(void);

static const unsigned char ENC_KEY[32] = {{ {c_arr(enc_key)} }};
static const unsigned char XOR_MASK[32] = {{ {c_arr(xor_mask)} }};

int main(int argc, char **argv) {{
    char exe_path[4096];
    uint32_t sz = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &sz) != 0) return 1;
    char *real = realpath(exe_path, NULL);
    char bin_copy[4096];
    snprintf(bin_copy, sizeof(bin_copy), "%s", real ? real : exe_path);
    char *dir = dirname(real ? real : exe_path);
    char res_ref[4096];
    snprintf(res_ref, sizeof(res_ref), "%s/../Resources", dir);
    char *res_real = realpath(res_ref, NULL);
    const char *res_dir = res_real ? res_real : res_ref;

    char site_dir[4096];
#if defined(__arm64__) || defined(__aarch64__)
    snprintf(site_dir, sizeof(site_dir), "%s/.venv_arm64/site-packages", res_dir);
#else
    snprintf(site_dir, sizeof(site_dir), "%s/.venv_x86_64/site-packages", res_dir);
#endif
    setenv("PYTHONPATH", site_dir, 1);
    setenv("DRPS5_RESOURCES_DIR", res_dir, 1);
    setenv("RESOURCEPATH", res_dir, 1);
    setenv("DRPS5_BIN", bin_copy, 1);
    setenv("DRPS5_EDITION", "{edition_val}", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    chdir(res_dir);

    const char *fw_candidates[] = {{
        "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Python3",
        "/Library/Frameworks/Python.framework/Versions/3.9/Python",
        "/Library/Frameworks/Python.framework/Versions/3.11/Python",
        "/usr/local/Frameworks/Python.framework/Versions/3.9/Python",
        NULL
    }};
    void *py_lib = NULL;
    for (int i = 0; fw_candidates[i]; i++) {{
        py_lib = dlopen(fw_candidates[i], RTLD_NOW | RTLD_GLOBAL);
        if (py_lib) break;
    }}
    if (!py_lib) {{
        fprintf(stderr, "DRPS5: Python3.framework no encontrado\\n");
        return 2;
    }}

    py_init_fn Py_Initialize = (py_init_fn)dlsym(py_lib, "Py_Initialize");
    py_run_fn PyRun_SimpleString = (py_run_fn)dlsym(py_lib, "PyRun_SimpleString");
    py_fin_fn Py_Finalize = (py_fin_fn)dlsym(py_lib, "Py_Finalize");
    if (!Py_Initialize || !PyRun_SimpleString) return 3;

    unsigned char key[32];
    char hex_key[65];
    for (int i = 0; i < 32; i++) {{
        key[i] = ENC_KEY[i] ^ XOR_MASK[i];
        snprintf(hex_key + i * 2, 3, "%02x", key[i]);
    }}

    Py_Initialize();
    char boot[8192];
    snprintf(boot, sizeof(boot),
        "import os, sys, json, zlib, hashlib, importlib.abc, importlib.util\\n"
        "res = os.environ['DRPS5_RESOURCES_DIR']\\n"
        "os.chdir(res)\\n"
        "sys.argv = [os.path.join(res, 'drps5.py')] + [a for a in getattr(sys, 'argv', [])[1:] if a]\\n"
        "pak = open(os.path.join(res, 'core.pak'), 'rb').read()\\n"
        "key = bytes.fromhex('%s')\\n"
        "dec = bytearray(len(pak))\\n"
        "idx = 0\\n"
        "pos = 0\\n"
        "while pos < len(pak):\\n"
        "    ks = hashlib.sha256(key + idx.to_bytes(4, 'little')).digest()\\n"
        "    n = min(32, len(pak) - pos)\\n"
        "    for i in range(n): dec[pos + i] = pak[pos + i] ^ ks[i]\\n"
        "    pos += n; idx += 1\\n"
        "mods = json.loads(zlib.decompress(bytes(dec)).decode('utf-8'))\\n"
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
        "import drps5\\n"
        "drps5.main()\\n",
        hex_key
    );
    int rc = PyRun_SimpleString(boot);
    memset(boot, 0, sizeof(boot));
    memset(key, 0, sizeof(key));
    if (Py_Finalize) Py_Finalize();
    return rc;
}}
"""
    c_file = out_bin.parent / "launcher.c"
    c_file.write_text(c_src, encoding="utf-8")
    subprocess.run([
        "clang", "-O3", "-arch", "arm64", "-arch", "x86_64",
        "-mmacosx-version-min=11.0",
        str(c_file), "-o", str(out_bin)
    ], check=True)
    c_file.unlink()


def populate_venvs(res_dir: Path):
    # 1. arm64 site-packages from V1 .venv
    arm_dst = res_dir / ".venv_arm64" / "site-packages"
    arm_dst.mkdir(parents=True, exist_ok=True)
    arm_src = next((MAC_V1_APP / "Contents" / "Resources" / ".venv" / "lib").glob("python*/site-packages"))
    shutil.copytree(arm_src, arm_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

    # 2. x86_64 site-packages from downloaded wheels
    x86_dst = res_dir / ".venv_x86_64" / "site-packages"
    x86_dst.mkdir(parents=True, exist_ok=True)
    if X86_WHEELS_DIR.exists():
        for whl in X86_WHEELS_DIR.glob("*.whl"):
            with zipfile.ZipFile(whl, "r") as zf:
                zf.extractall(x86_dst)


def build_edition(is_personal: bool):
    tag = "Personal" if is_personal else "Publico"
    stage = MAC_V2_DIR / f"_stage_{tag}"
    if stage.exists():
        shutil.rmtree(stage)
    app_dir = stage / "DRPS5.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    res_dir = app_dir / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    res_dir.mkdir(parents=True)

    # Info.plist completo con permisos de red local (ATS WKWebView), GameController y Game Mode de macOS
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>DRPS5</string>
    <key>CFBundleDisplayName</key><string>DRPS5 Remote Play</string>
    <key>CFBundleIdentifier</key><string>com.drps5.remoteplay</string>
    <key>CFBundleVersion</key><string>2.0.17</string>
    <key>CFBundleShortVersionString</key><string>2.0.17</string>
    <key>CFBundleExecutable</key><string>DRPS5</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>GCSupportsGameMode</key><true/>
    <key>LSSupportsGameMode</key><true/>
    <key>GCSupportsControllerUserInteraction</key><true/>
    <key>GCSupportedGameControllers</key>
    <array>
        <dict><key>ProfileName</key><string>ExtendedGamepad</string></dict>
        <dict><key>ProfileName</key><string>DirectionalGamepad</string></dict>
        <dict><key>ProfileName</key><string>MicroGamepad</string></dict>
    </array>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key><true/>
        <key>NSAllowsLocalNetworking</key><true/>
    </dict>
</dict>
</plist>
"""
    (app_dir / "Contents" / "Info.plist").write_text(plist, encoding="utf-8")

    # Copy icons, gamecontrollerdb, V2 GUI
    v1_res = MAC_V1_APP / "Contents" / "Resources"
    for f in ("AppIcon.icns", "app_icon_1024.png", "gamecontrollerdb.txt"):
        if (v1_res / f).exists():
            shutil.copy2(v1_res / f, res_dir / f)
    shutil.copytree(GUI_V2_DIR, res_dir / "gui", dirs_exist_ok=True)

    populate_venvs(res_dir)
    compile_cas_dylib(res_dir / "libdrps5_cas.dylib")
    seed = PERSONAL_SEED_CONFIG if is_personal else PUBLIC_SEED_CONFIG
    pak_key = build_core_pak(res_dir / "core.pak", seed)
    compile_universal_launcher(macos_dir / "DRPS5", pak_key, is_personal)

    # Firma ad-hoc para que macOS GameController / WKWebView / TCC reconozcan la identidad del paquete
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app_dir)], check=False)

    if is_personal:
        installed_app = Path("/Applications/DRPS5.app")
        if installed_app.exists():
            shutil.rmtree(installed_app)
        shutil.copytree(app_dir, installed_app, symlinks=True)
        print(f"Installed Personal edition to {installed_app}")

    # Create symlink to /Applications inside DMG stage
    os.symlink("/Applications", stage / "Applications")

    dmg_out = MAC_V2_DIR / f"DRPS5_V2_{tag}.dmg"
    if dmg_out.exists():
        dmg_out.unlink()
    subprocess.run([
        "hdiutil", "create",
        "-volname", f"DRPS5 V2 {tag}",
        "-srcfolder", str(stage),
        "-ov", "-format", "UDZO",
        str(dmg_out)
    ], check=True)
    shutil.rmtree(stage)
    print(f"Built macOS Universal DMG: {dmg_out} ({dmg_out.stat().st_size} bytes)")


def main():
    MAC_V2_DIR.mkdir(parents=True, exist_ok=True)
    build_edition(True)
    build_edition(False)


if __name__ == "__main__":
    main()
