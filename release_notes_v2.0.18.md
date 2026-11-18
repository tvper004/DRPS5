## DRPS5 Remote Play V2 (v2.0.18) — Edición Pública

Cliente multiplataforma de Remote Play para PS5 / PS4 de ultra-baja latencia (720p / 1080p / 2K / 4K @ 60 FPS), libre de credenciales, tokens o vinculaciones predeterminadas (Edición Pública limpia para emparejamiento manual por PIN local o remoto vía Tailscale/DDNS).

---

### Descargas por Plataforma (Archivos Públicos)

| Plataforma | Archivo | Descripción |
| :--- | :--- | :--- |
| **macOS (Universal)** | `DRPS5_V2_Publico.dmg` | Instalador Universal para Apple Silicon (M1/M2/M3/M4) e Intel con renderizado Metal GPU y filtro CAS nativo |
| **Android / Android TV / TV Stick** | `DRPS5_V2_Publico.apk` | APK universal compatible con móviles, tablets, Android TV y TV Sticks de bajos recursos |
| **LG webOS TV** | `com.drps5.remoteplay_1.3.1_publico_all.ipk` | Instalador IPK nativo para televisores LG webOS |
| **Windows (x64 / ARM64)** | `DRPS5_V2_Setup_Publico.exe` | Instalador ejecutable para Windows 10/11 con aceleración Direct3D 11 |

---

### Cambios y Mejoras frente a la Versión Anterior

#### 1. Versión macOS (Rendimiento, Escalado GPU y Jugabilidad)
- **Renderizado Metal GPU y Escalado Retina/2K/4K (`pygame.SCALED`)**:
  - Eliminación total de la interpolación Nearest-Neighbor por CPU (`pygame.transform.scale`) que generaba cuellos de botella y picos térmicos.
  - Escalado por hardware directo mediante Metal a resolución nativa de pantalla (Retina, 1440p QHD y 2160p 4K) en ~0.2 ms por fotograma.
  - Integración de biblioteca dinámica universal C/SIMD (`libdrps5_cas.dylib`) con filtro Contrast Adaptive Sharpening (CAS) de alto rendimiento (~2 ms a 1080p).
  - Caching inteligente de HUD y botones en pantalla: actualización de texturas únicamente ante cambios de estado o FPS (0 asignaciones de memoria por fotograma).
- **Decodificación de Video con Latencia Cero (0-Frame Slice Decoding)**:
  - Transición del decodificador H.264/HEVC en PyAV de `ThreadType.AUTO` (que acumulaba 4–8 fotogramas / 66–133 ms de retardo por frame-threading) a `ThreadType.SLICE` con 4 hilos de corte, logrando decodificación inmediata en tiempo real.
- **Ventana de Reordenamiento Multi-Slot (6 Fotogramas) y Recuperación FEC**:
  - Sustitución del búfer de 1 solo frame por una ventana deslizante de 6 slots y un anillo de 96 fotogramas entregados (`_delivered_ring`), eliminando falsas caídas por paquetes UDP fuera de orden o paquetes de paridad FEC tardíos.
- **Jugabilidad y Respuesta de Mandos en macOS**:
  - **Zona Muerta Radial 2D Real**: sustitución del filtrado axial independiente por cálculo vectorial euclidiano (`hypot(lx, ly)`) con curva híbrida de precisión (85% lineal + 15% cúbica) para micro-apuntado suave sin saltos.
  - **Superficie Táctil Capacitiva DualSense**: soporte nativo de eventos táctiles (`CONTROLLERTOUCHPADDOWN`, `CONTROLLERTOUCHPADMOTION`, `CONTROLLERTOUCHPADUP`) mapeados al protocolo Takion de PS5 (5 bytes: `0xD0`/`0xC0`, coordenadas 0..1919 x 0..941).
  - **Desacople de Sticks a 125 Hz**: transmisión asíncrona de estado analógico sin bloquear el bucle de renderizado ni colisionar con VSync.
  - **Detección IOKit HID y Permisos ATS**: integración de `NSAppTransportSecurity` y `GCSupportedGameControllers` en `Info.plist` de macOS, evitando bloqueos de red local en WKWebView y permitiendo detección inmediata de mandos conectados.

#### 2. Versión Android y TV Sticks
- **Motor de Mandos Físicos y Crucetas (D-Pad)**:
  - Eliminación del envío redundante de gatillos L2/R2 en `ACTION_MOVE` mediante histéresis de umbral (`>0.30f` / `<0.15f`).
  - Soporte de ejes `AXIS_HAT_X` / `AXIS_HAT_Y` y navegación analógica en menús.
  - Detección y remapeo en tiempo real (`isRawSonyHidLayout`) para mandos DualSense/DualShock 4 en TV Sticks con kernels Android antiguos sin keylayout oficial.
- **Modo Directo Zero-Copy para TV Sticks de Bajos Recursos**:
  - Activación automática de renderizado `SurfaceView` directo (0 copias GPU/CPU) en dispositivos ligeros (Allwinner H313, Rockchip, etc.) alcanzando 60 FPS estables sin saturación de memoria.
  - Corrección de paquetes perdidos (`VideoSlot.delivered`) pasando de miles de pérdidas a 0 fotogramas descartados en pruebas de red local.
- **Navegación y UX en TV**:
  - Navegación hacia las pestañas superiores (Consolas / Ajustes) usando únicamente la flecha superior (`↑`) sin depender de gatillos `L1/R1`.
  - Persistencia de foco en Ajustes al alternar opciones sin que el cursor salte a la primera pestaña.
  - Ícono y banner Android TV HD (`640x360`) centrados sobre fondo negro puro (`#000000`).

#### 3. Núcleo Común y Seguridad (ISO/IEC 27017)
- Aislamiento estricto de configuraciones: la Edición Pública opera sobre configuraciones limpias sin perfiles ni credenciales empaquetadas.
- Soporte de contador de paquetes criptográficos de 64 bits para evitar desincronización de cifrado tras sesiones continuas de más de 4 GB de transferencia.
- Gestión segura de puertos locales de interfaz gráfica por encima del rango privilegiado (`>18000`).
