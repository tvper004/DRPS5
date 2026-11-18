# Historial de Versiones — DRPS5 Remote Play

## LG webOS (`WEBOS/V2`)

### v2.0.15
- **Soporte 2K y 4K Escalado:** Añadidas opciones `2K (2560×1440)` y `4K (3840×2160)` en Ajustes y en el menú rápido en juego, manteniendo negociación 1080p hacia la consola y escalado hardware hacia la pantalla del televisor.
- **Estabilidad 1080p / 2K / 4K:** Selección automática de **H.264** para resoluciones `>= 1080p` (desactivando H.265 y HDR en esas resoluciones para evitar congelamientos de decodificador en TVs afectadas), manteniendo `H.264`, `H.265` y `HDR` completos en `540p` y `720p`.
- **Corrección de flujo HEVC en NDL:** Retención de paquetes compuestos únicamente por cabeceras (VPS/SPS/PPS) sin envío aislado a `NDL_DirectVideoPlay()`, y anteposición automática en cada fotograma clave (IDR/CRA).
- **Control NDL:** Configuración explícita de `NDL_DirectVideoSetFrameDropThreshold(0)` y registro del resultado de `NDL_DirectVideoSetArea`.

### v2.0.14
- **Prepending HEVC:** Cacheo de parameter sets (VPS/SPS/PPS) y anteposición al primer cuadro de acceso aleatorio en 1080p.
- **Unificación de marca y diagnóstico:** Estandarización del identificador de diagnóstico `/tmp/drps5-probe` y limpieza integral de etiquetas heredadas.

### v2.0.13
- **Diagnóstico NAL HEVC:** Instrumentación detallada por muestra (`probe: hevc:`) con tamaños de VPS, SPS, PPS, tipos de slice y estado de cola NDL.

### v2.0.0 – v2.0.12
- Interfaz nativa en LVGL inspirada en consola, soporte de `libchiaki`, audio PCM 48 kHz, inyección de metadatos HDR10 SEI, suavizado de red, menú overlay en sesión (`Share + Options`), recuperación automática por IDR y emparejamiento Bluetooth de mandos.

---

## Android (`APK/V2`)

### v2.0.0
- **Interfaz 100% Nativa (Sin WebView):** Rediseño completo estilo WebOS V2 con navegación fluida por D-Pad (Android TV / Sticks) y pantalla táctil (celulares/tablets), reduciendo el uso de memoria a < 15 MB.
- **Motor GPU 2K y 4K a 60 FPS:** Renderizador `UpscaleRenderer` sobre OpenGL ES 2.0 con shader **CAS (Contrast Adaptive Sharpening) de 5 muestras**, decodificación `MediaCodec` a 1080p de baja latencia y protección adaptativa para mantener 60 FPS en TV Sticks.
- **Conexión Remota Inteligente:** Modo `Auto` (sondeo local rápido con conmutación automática a IP remota/Tailscale y `MTU 1200`), Wakeup dual y vinculación PSN OAuth bajo demanda.
- **Ediciones Personal y Pública:** Generación independiente de `DRPS5_V2_Personal.apk` y `DRPS5_V2_Publico.apk`.

---

## macOS (`MacOS/V2`)

### v2.0.0
- **Binario Universal (`arm64` + `x86_64`):** Soporte nativo tanto para Apple Silicon (M1/M2/M3/M4) como para Mac Intel con GPU dedicada o integrada.
- **Interfaz WebOS V2 y Escalado GPU Metal:** Nueva UI oscura translúcida, aceleración gráfica Metal (`SDL_RENDER_DRIVER=metal`) con escalado GPU `2K/4K @ 60 FPS`, prevención de App Nap e instaladores `.dmg` Personal y Público.

---

## Windows (`Windows/V2`)

### v2.0.0
- **Compatibilidad x86_64 y Windows ARM64:** Soporte para equipos Intel/AMD y dispositivos Windows on ARM64 (Prism + GPU).
- **Aceleración Direct3D 11 y GPU Dedicada:** Renderizado hardware `direct3d11` para escalado `2K/4K @ 60 FPS`, prioridad automática de GPU dedicada (`NvOptimus` / `AmdPowerXpress`), nueva interfaz WebOS V2 e instaladores NSIS Personal y Público.
