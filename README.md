<div align="center">
  <img src="WEBOS/V2/assets/drps5_icon.png" width="128" alt="DRPS5 Logo" />
  <h1>DRPS5 Remote Play</h1>
  <p><strong>Cliente multiplataforma de PlayStation Remote Play (PS5 / PS4) de ultra baja latencia, con reescalado GPU 2K/4K a 60 FPS, HDR10 y soporte completo para red local e Internet.</strong></p>

  <p>
    <img src="https://img.shields.io/badge/LG_webOS-2.0.15-0284c7?style=for-the-badge&logo=lg&logoColor=white" alt="webOS" />
    <img src="https://img.shields.io/badge/Android_TV_%26_Mobile-2.0.0-22c55e?style=for-the-badge&logo=android&logoColor=white" alt="Android" />
    <img src="https://img.shields.io/badge/macOS_Universal-2.0.0-38bdf8?style=for-the-badge&logo=apple&logoColor=white" alt="macOS" />
    <img src="https://img.shields.io/badge/Windows_x64_%2F_ARM64-2.0.0-0369a1?style=for-the-badge&logo=windows&logoColor=white" alt="Windows" />
    <a href="LICENSE"><img src="https://img.shields.io/badge/Licencia-Uso_Personal_Exclusivo_(All_Rights_Reserved)-ef4444?style=for-the-badge" alt="Licencia" /></a>
  </p>

  <p>
    <a href="https://ko-fi.com/robb004" target="_blank">
      <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Apoya el proyecto en Ko-fi" />
    </a>
  </p>
</div>

---

## Características Principales

- **Interfaz Unificada Estilo Consola:** Diseño limpio inspirado en la experiencia de consola, navegable con mando (DualSense, DualShock 4, Xbox), control remoto de TV, teclado/ratón o pantalla táctil.
- **Conexión Local y Remota Sin Cortes:** Detección automática en red local (DDP) y conmutación inteligente **Auto (`Local → Remoto`)** con ajuste de `MTU 1200` para jugar sin fragmentación a través de Tailscale, VPN o IP pública.
- **Reescalado por Hardware a 2K y 4K @ 60 FPS:** Decodificación acelerada por GPU y reescalado en tiempo real sin sobrecargar la CPU, diseñado para rendir fluidamente incluso en TV Sticks y portátiles.
- **Recuperación Activa de Video (Anti-Congelamiento):** Solicitud inteligente de fotogramas clave (IDR), corrección de errores Cauchy Reed-Solomon (FEC) y suavizado adaptativo de red para evitar microcortes.
- **Audio Estéreo de Baja Latencia y DualSense:** Decodificación Opus 48 kHz, soporte de vibración, panel táctil y emparejamiento directo por PIN o cuenta PSN.

---

## ¿Cómo funciona en cada Sistema Operativo?

### 1. LG webOS (Smart TVs) — `WEBOS/V2`
- **Arquitectura:** Aplicación nativa compilada en C (`LVGL 8.3` + `SDL2` + `libchiaki` + `NDL DirectMedia v2`).
- **Pipeline de Video y Audio:** Entrega directa de tramas H.264 / H.265 al decodificador hardware del televisor mediante `NDL_DirectVideoPlay` y audio PCM 48 kHz estéreo, inyectando metadatos **HDR10 (SMPTE ST 2084 / BT.2020)** cuando el perfil HDR está activo.
- **Gestión inteligente de códec:** En `540p` y `720p` (30/60 fps) habilita H.264, H.265 y H.265 HDR; en `1080p`, `2K` y `4K` escalado selecciona automáticamente `H.264` para máxima estabilidad y fluidez en el decodificador hardware del televisor.
- **Control:** Soporta emparejamiento Bluetooth nativo con DualSense / DualShock 4 / Xbox y control remoto Magic Remote de LG.

### 2. Android (TV, TV Sticks y Celulares) — `APK/V2`
- **Arquitectura:** Interfaz 100% nativa en Java (sin WebView en memoria, consumiendo menos de 15 MB de RAM en menú) + motor de protocolo Takion v12 en Java puro con FEC Cauchy Reed-Solomon.
- **Pipeline de Video 2K / 4K @ 60 FPS:** Decodifica la señal de PS5 a 1080p con `MediaCodec` en modo de baja latencia (`KEY_LOW_LATENCY`, `KEY_OPERATING_RATE`, claves específicas Allwinner/Qualcomm/HiSilicon) y escala en una sola pasada con un **shader OpenGL ES 2.0 CAS (Contrast Adaptive Sharpening) de 5 muestras** hacia `2560×1440` (2K) o `3840×2160` (4K).
- **Protección Adaptativa 60 FPS:** Mide el tiempo de renderizado de la GPU por cuadro; en TV Sticks con GPU limitada cambia automáticamente a filtrado bilineal rápido o modo **Directo Zero-Copy** para mantener los 60 FPS constantes.
- **Móvil y TV:** Incluye controles táctiles virtuales en pantalla (auto-ocultables si hay mando físico) y flujo de vinculación PSN OAuth integrado.

### 3. macOS (Apple Silicon M1–M4 e Intel + GPU) — `MacOS/V2`
- **Arquitectura:** Binario **Universal Mach-O (`arm64` + `x86_64`)** empaquetado en `.dmg` con carga aislada de dependencias nativas según la arquitectura detectada al iniciar.
- **Pipeline de Video:** Aceleración gráfica con **Metal** (`SDL_RENDER_DRIVER=metal`) y **VideoToolbox**, utilizando `pygame.SCALED` + `SDL_RENDER_SCALE_QUALITY=2` para escalar 1080p → 2K / 4K directamente en la GPU sin carga de CPU.
- **Estabilidad:** Desactiva App Nap (`NSActivityLatencyCritical`) durante la transmisión y soporta mandos DualSense / Xbox por USB o Bluetooth.

### 4. Windows (x86_64 y ARM64 + GPU) — `Windows/V2`
- **Arquitectura:** Ejecutable nativo compilado en C + núcleo empaquetado en memoria (`core.pak`) e instalador NSIS con soporte para **PCs x86_64** y dispositivos **Windows on ARM64** (vía Prism + GPU).
- **Pipeline de Video:** Renderizado hardware **Direct3D 11** (`SDL_RENDER_DRIVER=direct3d11`) compatible con tarjetas NVIDIA, AMD, Intel y Qualcomm Adreno, exportando `NvOptimusEnablement` y `AmdPowerXpressRequestHighPerformance` para priorizar la GPU dedicada en portátiles.
- **Red:** Sondeo TCP rápido para ruta automática Local/Remota y optimización de paquetes para túneles VPN / Tailscale.

---

## Historial de Versiones y Correcciones

Consulta el detalle completo en [CHANGELOG.md](CHANGELOG.md). Resumen reciente:

| Plataforma | Versión | Cambios y correcciones principales |
|---|---|---|
| **LG webOS** | **2.0.15** | Soporte de resoluciones **2K** y **4K** escaladas; retención de cabeceras HEVC VPS/SPS/PPS (sin envío aislado) y prepending en cada IDR; selección automática de **H.264** en 1080p/2K/4K para garantizar fluidez sin congelamientos; acabado visual unificado. |
| **LG webOS** | **2.0.14** | Cacheo y anteposición de parameter sets HEVC en el primer cuadro de acceso aleatorio; ajuste de opciones de diagnóstico. |
| **LG webOS** | **2.0.13** | Instrumentación detallada por muestra NAL (`probe: hevc:`) para análisis de flujos H.265 y HDR en TV. |
| **LG webOS** | **2.0.0 – 2.0.12** | Interfaz PS5 en LVGL, audio PCM 48 kHz, suavizado adaptativo de red, HDR10 SEI, menú rápido en juego, watchdog anti-congelamiento y emparejamiento Bluetooth de mandos. |
| **Android** | **2.0.0** | Rediseño nativo estilo WebOS V2 sin WebView, motor GPU OpenGL ES CAS 5-tap para 2K/4K a 60 FPS con modo adaptativo para Sticks, ruta automática Local/Remota y OAuth PSN bajo demanda. |
| **macOS** | **2.0.0** | Nueva interfaz gráfica unificada, binario Universal (`arm64` + `x86_64` para Apple Silicon e Intel), escalado GPU Metal 2K/4K a 60 FPS y empaquetado `.dmg`. |
| **Windows** | **2.0.0** | Nueva interfaz gráfica unificada, soporte x86_64 y Windows ARM64, escalado GPU Direct3D 11 2K/4K a 60 FPS, prioridad de GPU dedicada e instaladores NSIS. |

---

## Estructura del Repositorio

```text
PXPLAY/
├── WEBOS/V2/       # Código fuente C, CMake y scripts de empaquetado .ipk para LG webOS
├── APK/V2/         # Código fuente Java y generador de APKs firmados para Android
├── MacOS/V2/       # Generador Universal (arm64 + x86_64) e instaladores .dmg para macOS
├── Windows/V2/     # Lanzador nativo C y compilador de instaladores NSIS .exe para Windows
├── DRPS5/          # Motor compartido de streaming (v2_core/) e interfaz desktop (gui_v2/)
├── CHANGELOG.md    # Registro detallado de versiones y mejoras
└── README.md       # Documentación principal del proyecto
```

---

## Compilación Rápida

- **LG webOS:** `cd WEBOS/V2 && ./build.sh`
- **Android:** `python3 APK/V2/build_v2.py`
- **macOS Universal:** `python3 MacOS/V2/build_macos_v2.py`
- **Windows:** `python3 Windows/V2/build_windows_v2.py`

---

## Licencia

**Uso Personal Exclusivo (All Rights Reserved)** — Consulta [LICENSE](LICENSE).  
Se autoriza descargar y usar la aplicación únicamente para fines personales no comerciales. Queda prohibida su venta, redistribución o creación de derivados comerciales.

---

<div align="center">
  <p>Si DRPS5 te resulta útil en tu TV, Stick, PC o Mac, puedes apoyar su desarrollo continuo:</p>
  <a href="https://ko-fi.com/robb004" target="_blank">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Invítame un café en Ko-fi" />
  </a>
</div>
