# DRPS5 - Pantalla Remota de PS5 (Sin Inicio de Sesión ni Licencias)

**DRPS5** es una aplicación completa, optimizada y ligera diseñada exclusivamente para realizar **pantalla remota (streaming de vídeo, audio y control) de la PlayStation 5 en macOS**.

---

## 🚀 Características Principales

1. **Sin Inicio de Sesión ni Cuentas Obligatorias**:
   - No requiere iniciar sesión en PlayStation Network (PSN) mediante navegadores web ni proporcionar contraseñas.
   - No tiene comprobaciones de licencias de terceros ni sistemas DRM. Su función se concentra al 100% en transmitir la pantalla de tu PS5 de forma directa.
2. **Descubrimiento y Encendido Automático**:
   - Detección automática de consolas PS5 en tu red local vía protocolo UDP 987 (DDP).
   - Función para encender la consola desde el **Modo Reposo** con un solo clic.
3. **Vinculación Directa con PIN de 8 Dígitos**:
   - Solo necesitas introducir el código PIN de 8 dígitos que aparece en tu PS5 (*Ajustes > Sistema > Uso a distancia > Vincular dispositivo*).
   - Una vez vinculada, las claves criptográficas quedan guardadas en `~/.drps5/drps5_config.json` y **nunca más vuelve a pedirte el PIN**.
4. **Streaming de Ultra-Baja Latencia**:
   - Renderizado acelerado por hardware a **60 FPS** (720p / 1080p).
   - Códecs de vídeo de alto rendimiento **HEVC (H.265)** y **H.264**.
   - Audio estéreo digital de baja latencia vía **Opus (48 kHz)** directo a CoreAudio.
5. **Soporte Completo de Mandos y Teclado**:
   - Mandos **DualSense (PS5)**, **DualShock 4 (PS4)** y **Xbox** compatibles mediante USB o Bluetooth (Plug & Play con detección analógica de gatillos L2/R2 y sticks).
   - Atajos de teclado completos como alternativa si juegas sin mando.

---

## 🎮 Cómo Iniciar DRPS5

### Método 1: Aplicación Gráfica (macOS App)
- Abre la app haciendo doble clic en:
  **`DRPS5.app`** o ejecutando **`./launch_drps5.sh`**.
- La aplicación escaneará tu red local, detectará tu PS5 y te permitirá iniciar la pantalla remota con un solo clic en **"INICIAR PANTALLA REMOTA DE PS5"**.

### Método 2: Línea de Comandos (CLI)
Dentro de la carpeta `DRPS5`, puedes usar el comando `./drps5`:

```bash
# 1. Buscar consolas PS5 en tu red:
./drps5 discover

# 2. Encender tu PS5 desde Modo Reposo:
./drps5 wakeup --ip 192.168.1.100

# 3. Vincular por primera vez con el PIN de la PS5:
./drps5 pair --ip 192.168.1.100 --pin 12345678

# 4. Iniciar la transmisión de pantalla remota:
./drps5 stream --ip 192.168.1.100
```

---

## ⌨️ Controles Durante la Transmisión

| Acción | Mando Físico | Teclado |
|---|---|---|
| **Moverse / Stick Izquierdo** | Stick Analógico Izquierdo | Teclas `W`, `A`, `S`, `D` |
| **Mirar / Stick Derecho** | Stick Analógico Derecho | - |
| **D-Pad (Cruceta)** | D-Pad Cruceta | Teclas de Flechas (`↑`, `↓`, `←`, `→`) |
| **X (Cruz)** | Botón A / X | `Espacio` o `Enter` |
| **O (Círculo)** | Botón B / Círculo | `Retroceso (Backspace)` |
| **▢ (Cuadrado)** | Botón X / Cuadrado | Tecla `Q` |
| **△ (Triángulo)** | Botón Y / Triángulo | Tecla `E` |
| **L1 / R1** | Bumpers LB / RB | Teclas `1` / `2` |
| **L2 / R2** | Gatillos Analógicos | Teclas `3` / `4` |
| **L3 / R3** | Clic en Sticks | - |
| **Botón PS** | Botón Guía / PS | Tecla `Tab` |
| **Options** | Botón Start / Options | Tecla `Esc` |
| **Share / Create** | Botón Back / Share | Tecla `H` |
| **Pantalla Completa** | - | Tecla `F11` |
| **Mostrar / Ocultar HUD** | - | Tecla `F1` |
| **Salir de Transmisión** | - | `Shift + Esc` o cerrar ventana |

---

## 📁 Estructura del Proyecto en `DRPS5/`

```
DRPS5/
├── DRPS5.app/          # Paquete de aplicación nativa para macOS
├── drps5               # Ejecutable por línea de comandos
├── launch_drps5.sh     # Script lanzador con doble clic
├── drps5.py            # Enrutador principal CLI y GUI
├── drps5_gui.py        # Interfaz gráfica moderna (Tema Oscuro PlayStation)
├── drps5_stream.py     # Motor de streaming en tiempo real (Pygame + PyAV)
├── drps5_core.py       # Lógica de protocolo DDP, emparejamiento y sesión
├── drps5_config.py     # Gestor de configuración local (~/.drps5/)
├── pyremoteplay/       # Módulo del protocolo oficial Remote Play
└── .venv/              # Entorno virtual con todas las dependencias instaladas
```
