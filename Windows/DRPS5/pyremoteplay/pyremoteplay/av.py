"""AV for pyremoteplay."""
from __future__ import annotations
import logging
import time
import threading
from collections import deque
from typing import TYPE_CHECKING, Callable

from .stream_packets import AVPacket, Packet
from .const import FFMPEG_PADDING

if TYPE_CHECKING:
    from .session import Session
    from pyremoteplay.receiver import AVReceiver

_LOGGER = logging.getLogger(__name__)


class AVHandler:
    """AV Handler."""

    def __del__(self):
        self._queue.clear()

    def __init__(self, session: Session):
        self._session = session
        self._receiver = None
        self._v_stream = None
        self._a_stream = None
        self._cipher = None
        self._queue = deque(maxlen=5000)
        self._has_packet = threading.Event()
        self._worker = None
        self._last_congestion = 0
        self._last_corrupt_time = 0
        self._waiting = False

    def add_receiver(self, receiver: AVReceiver):
        """Add AV reciever and run."""
        if self._receiver:
            raise RuntimeError("Cannot add Receiver more than once")
        if receiver is not None:
            self._receiver = receiver
            # pylint: disable=protected-access
            self._receiver._set_session(self._session)
            self._receiver._get_video_codec()

    def set_cipher(self, cipher):
        """Set cipher. Schedules handler to run."""
        self._cipher = cipher
        self._session.events.emit("av_ready")

    def set_headers(self, v_header: bytes, a_header: bytes):
        """Set headers."""
        if self._receiver:
            self._v_stream = AVStream(
                "video",
                v_header,
                self._receiver.handle_video_data,
                self._send_corrupt,
                session=self._session,
            )
            self._a_stream = AVStream(
                "audio",
                a_header,
                self._receiver.handle_audio_data,
                self._send_corrupt,
                session=self._session,
            )
            # pylint: disable=protected-access
            self._receiver._get_audio_codec(a_header)
            if v_header:
                try:
                    self._receiver.handle_video_data(v_header)
                except Exception:
                    pass
            # self._schedule_congestion()

    def add_packet(self, msg: bytes):
        """Add Packet."""
        packet = Packet.parse(msg, {"host_type": self._session.type})
        if len(self._queue) >= self._queue.maxlen:
            # Recortar los paquetes acumulados manteniendo los más recientes para no saturar memoria
            while len(self._queue) > 200:
                self._queue.popleft()
            self._waiting = True
            _LOGGER.warning("AV Handler max queue size exceeded - Trimming queue and requesting IDR recovery frame")
            # In real-time streaming, NEVER stop session on jitter/backlog. Request a keyframe to recover.
            if not self._session.is_stopped:
                try:
                    self._session.stream.send_corrupt(0, 0)
                except Exception as exc:
                    _LOGGER.debug("Error sending corrupt frame: %s", exc)
            return
        if packet.type == AVPacket.Type.AUDIO:
            self._queue.append(packet)
            self._has_packet.set()
        else:
            if self._waiting and packet.unit_index == 0:
                self._waiting = False
            if not self._waiting:
                self._queue.append(packet)
                self._has_packet.set()

    def process_packet(self):
        """Process AV Packet."""
        try:
            packet = self._queue.popleft()
        except IndexError:
            self._has_packet.clear()
            self._has_packet.wait(timeout=0.005)
            return
        packet.decrypt(self._cipher)
        self._handle(packet)

    def worker(self):
        """Worker for AV Handler. Run in thread."""
        while not self._session.is_stopped:
            self.process_packet()
        _LOGGER.debug("Closing AV Receiver")
        self._receiver.close()
        self._queue.clear()
        self._has_packet.set()
        _LOGGER.debug("AV Receiver Closed")

    def _handle_audio(self, packet: AVPacket):
        """Procesa paquetes de audio Opus extrayendo las unidades fuente individuales según el protocolo Takion."""
        try:
            units_meta = getattr(packet, "frame_meta", {}).get("units", {})
            unit_size = units_meta.get("size", 0)
            src_count = units_meta.get("src", 0)
            data = packet.data

            if unit_size > 0 and src_count > 0:
                # Decodificar ÚNICAMENTE las unidades fuente (Opus). NUNCA enviar unidades de paridad FEC al decodificador Opus.
                count = min(src_count, len(data) // unit_size)
                for i in range(count):
                    unit_data = data[i * unit_size : (i + 1) * unit_size]
                    if unit_data:
                        self._receiver.handle_audio_data(unit_data)
            elif data:
                self._receiver.handle_audio_data(data)
        except Exception as err:
            _LOGGER.debug("Error procesando paquete de audio: %s", err)

    def _handle(self, packet: AVPacket):
        if not self._receiver:
            return
        if packet.type == AVPacket.Type.VIDEO:
            self._v_stream.handle(packet)
        elif getattr(packet, "is_haptics", False):
            # Paquete de vibración háptica de mando DualSense en PS5 - no decodificar con Opus
            return
        else:
            self._handle_audio(packet)

    def _schedule_congestion(self):
        self._session.loop.call_later(0.5, self._send_congestion)

    def _send_congestion(self):
        # TODO: Use or don't use?
        now = time.time()
        if now - self._last_congestion > 0.2 and not self._session.is_stopped:
            self._session._sync_run_io(  # pylint: disable=protected-access
                self._session.stream.send_congestion, self.received, self.lost
            )
            self._v_stream.reset_counters()
            self._a_stream.reset_counters()
            self._last_congestion = now
            self._schedule_congestion()

    def _send_corrupt(self, last_complete: int, current: int):
        """Handle corrupt frame.

        :param last_complete: The last frame index that was completed
        :param current: The current frame index
        """
        now = time.time()
        # Throttling corto de 80ms para no saturar UDP pero reaccionar inmediatamente en la misma ráfaga
        if hasattr(self, "_last_corrupt_time") and now - self._last_corrupt_time < 0.08:
            return
        self._last_corrupt_time = now
        if not self._session.is_stopped:
            self._session.stream.send_corrupt(last_complete, current)
            # Solicitar inmediatamente un IDR keyframe para restaurar el stream sin artefactos verdes ni grises
            if hasattr(self._session.stream, "send_idr_request"):
                if now - getattr(self, "_last_idr_req_time", 0) > 0.12:
                    self._last_idr_req_time = now
                    self._session.stream.send_idr_request()

    @property
    def has_receiver(self) -> bool:
        """Return True if receiver is not None."""
        return self._receiver is not None

    @property
    def lost(self) -> int:
        """Return Total AV packets lost."""
        return self._v_stream.lost + self._a_stream.lost

    @property
    def received(self) -> int:
        """Return Total AV packets received."""
        return self._v_stream.received + self._a_stream.received


def is_idr_frame(data: bytes, codec: str) -> bool:
    """Detecta si un fotograma de vídeo H.264 o HEVC es un IDR / Keyframe autónomo."""
    if not data or len(data) < 5:
        return False
    pos = 0
    d_len = len(data)
    is_h264 = codec.startswith("h264")
    while pos < d_len - 4:
        if data[pos : pos + 3] == b"\x00\x00\x01":
            nal_byte = data[pos + 3]
            pos += 3
        elif data[pos : pos + 4] == b"\x00\x00\x00\x01":
            nal_byte = data[pos + 4]
            pos += 4
        else:
            pos += 1
            continue

        if is_h264:
            nal_type = nal_byte & 0x1F
            if nal_type in (5, 7, 8):  # 5=IDR, 7=SPS, 8=PPS
                return True
        else:  # hevc
            nal_type = (nal_byte >> 1) & 0x3F
            if (16 <= nal_type <= 21) or nal_type in (32, 33, 34):  # 16-21=IRAP/IDR/CRA/BLA, 32=VPS, 33=SPS, 34=PPS
                return True
    return False


# Precomputed GF(2^8) tables (primitive polynomial 0x11D) for PS5 Cauchy Reed-Solomon FEC
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]

_GF_MUL_TABLE = [bytes([0] * 256)] + [
    bytes([0] + [_GF_EXP[_GF_LOG[a] + _GF_LOG[b]] for b in range(1, 256)])
    for a in range(1, 256)
]


def _gf_inv(a: int) -> int:
    return 0 if a == 0 else _GF_EXP[255 - _GF_LOG[a]]


def _xor_bytes_inplace(dst: bytearray, src: bytes):
    dst_int = int.from_bytes(dst, "big") ^ int.from_bytes(src, "big")
    dst[:] = dst_int.to_bytes(len(dst), "big")


def recover_fec_units(raw_units: dict, k: int, m: int, block_size: int) -> bool:
    """Reconstruct missing source units (0..k-1) in-place in raw_units using Cauchy RS over GF(2^8)."""
    if k <= 0 or m <= 0 or k + m > 256 or block_size <= 2:
        return False
    missing_src = [j for j in range(k) if j not in raw_units]
    r = len(missing_src)
    if r == 0:
        return True
    avail_fec = [f for f in range(m) if (k + f) in raw_units]
    if len(avail_fec) < r:
        return False
    used_fec = avail_fec[:r]
    present_src = [j for j in range(k) if j in raw_units]

    padded_src = {
        j: raw_units[j] + b"\x00" * (block_size - len(raw_units[j]))
        for j in present_src
    }

    syndromes = []
    for f in used_fec:
        fec_pkt = raw_units[k + f]
        syn = bytearray(fec_pkt[:block_size].ljust(block_size, b"\x00"))
        for j in present_src:
            c = _gf_inv(f ^ (j + m))
            if c:
                _xor_bytes_inplace(syn, padded_src[j].translate(_GF_MUL_TABLE[c]))
        syndromes.append(bytes(syn))

    mat = [
        [_gf_inv(used_fec[row] ^ (missing_src[col] + m)) for col in range(r)]
        + [1 if row == col else 0 for col in range(r)]
        for row in range(r)
    ]

    for col in range(r):
        pivot = col
        while pivot < r and mat[pivot][col] == 0:
            pivot += 1
        if pivot == r:
            return False
        mat[col], mat[pivot] = mat[pivot], mat[col]
        inv_p = _gf_inv(mat[col][col])
        inv_tab = _GF_MUL_TABLE[inv_p]
        for c_idx in range(2 * r):
            mat[col][c_idx] = inv_tab[mat[col][c_idx]]
        for row in range(r):
            if row != col and mat[row][col] != 0:
                factor_tab = _GF_MUL_TABLE[mat[row][col]]
                for c_idx in range(2 * r):
                    mat[row][c_idx] ^= factor_tab[mat[col][c_idx]]

    inv_mat = [row[r:] for row in mat]

    for col, j in enumerate(missing_src):
        rec = bytearray(block_size)
        for row in range(r):
            c = inv_mat[col][row]
            if c:
                _xor_bytes_inplace(rec, syndromes[row].translate(_GF_MUL_TABLE[c]))
        pad_len = (rec[0] << 8) | rec[1]
        wire_len = block_size - pad_len
        if wire_len <= 2 or wire_len > block_size:
            return False
        raw_units[j] = bytes(rec[:wire_len])
    return True


class AVStream:
    """AV Stream con reensamblado indexado por unit_index + recuperación FEC Cauchy Reed-Solomon."""

    TYPE_VIDEO = "video"
    TYPE_AUDIO = "audio"

    def __init__(
        self,
        av_type: str,
        header: bytes,
        callback_done: Callable[[bytes], None],
        callback_corrupt: Callable[[int, int], None],
        session: Session = None,
    ):
        self._type = av_type
        self._callback_done = callback_done
        self._callback_corrupt = callback_corrupt
        self._session = session
        self._header = header or b""
        self._units = {}       # {unit_index: bytes (payload without 2-byte pad header)}
        self._raw_units = {}   # {unit_index: bytes (full decrypted unit including 2-byte pad header)}
        self._fec_block_size = 0
        self._frame = -1
        self._frame_length_src = 0
        self._frame_length_fec = 0
        self._last_complete = -1
        self._lost = 0
        self._received = 0
        self._waiting_for_idr = (av_type == AVStream.TYPE_VIDEO)
        self._last_idr_req_time = 0.0

        if self._type not in [AVStream.TYPE_VIDEO, AVStream.TYPE_AUDIO]:
            raise ValueError("Invalid Type")

    def reset_counters(self):
        """Reset packet counters."""
        self._lost = self._received = 0

    def handle(self, packet: AVPacket):
        """Reensambla fotogramas por índice de unidad con soporte FEC Cauchy Reed-Solomon para 60 FPS fluidos."""
        self._received += 1
        if self._received > 65535:
            self._received = 1

        # Ignorar paquetes tardíos o de paridad FEC de un fotograma ya completado
        if self._last_complete >= 0 and ((self._last_complete - packet.frame_index) & 0xFFFF) < 16384:
            return

        # Nuevo fotograma
        if packet.frame_index != self._frame:
            if self._frame >= 0 and self._last_complete != self._frame:
                lost_cnt = max(0, self._frame_length_src - len(self._units))
                self._lost += lost_cnt
                if self._type == AVStream.TYPE_VIDEO and self._last_complete < 0:
                    self._waiting_for_idr = True
                if self._callback_corrupt:
                    expected_next = (self._last_complete + 1) & 0xFFFF
                    self._callback_corrupt(expected_next, (packet.frame_index - 1) & 0xFFFF)

            self._frame = packet.frame_index
            self._frame_length_src = packet.frame_length_src
            self._frame_length_fec = packet.frame_length_fec
            self._units = {}
            self._raw_units = {}
            self._fec_block_size = 0

        if self._last_complete == self._frame:
            return

        if len(packet.data) < 2:
            return

        self._raw_units[packet.unit_index] = packet.data
        if not packet.is_fec and packet.unit_index < packet.frame_length_src:
            self._units[packet.unit_index] = packet.data[2:]
            pad_val = (packet.data[0] << 8) | packet.data[1]
            if pad_val >= 0:
                self._fec_block_size = len(packet.data) + pad_val
        elif packet.is_fec and self._fec_block_size == 0:
            self._fec_block_size = len(packet.data)

        # Intentar recuperación FEC si faltan paquetes fuente pero ya llegaron suficientes paridades FEC
        if (
            len(self._units) < packet.frame_length_src
            and len(self._raw_units) >= packet.frame_length_src
            and self._fec_block_size > 2
        ):
            if recover_fec_units(
                self._raw_units,
                packet.frame_length_src,
                packet.frame_length_fec,
                self._fec_block_size,
            ):
                for idx in range(packet.frame_length_src):
                    if idx not in self._units and idx in self._raw_units:
                        self._units[idx] = self._raw_units[idx][2:]

        # Si se han completado todas las unidades fuente del fotograma
        if len(self._units) == packet.frame_length_src:
            assembled = b"".join(self._units[i] for i in range(packet.frame_length_src))

            if self._type == AVStream.TYPE_VIDEO:
                codec_name = getattr(self._session, "codec", "hevc") if self._session else "hevc"
                is_idr = is_idr_frame(assembled, codec_name)

                if self._waiting_for_idr:
                    if is_idr:
                        _LOGGER.info("🎉 IDR Keyframe recibido y validado (frame %s). Reanudando vídeo...", self._frame)
                        self._waiting_for_idr = False
                        self._last_complete = self._frame
                        frame_data = self._header + assembled if self._header else assembled
                        self._callback_done(frame_data)
                    else:
                        now_t = time.time()
                        if now_t - self._last_idr_req_time > 0.12:
                            self._last_idr_req_time = now_t
                            if self._session and hasattr(self._session, "stream") and hasattr(self._session.stream, "send_idr_request"):
                                self._session.stream.send_idr_request()
                        self._units.clear()
                        self._raw_units.clear()
                        return
                else:
                    self._last_complete = self._frame
                    frame_data = self._header + assembled if self._header else assembled
                    self._callback_done(frame_data)
            else:
                self._last_complete = self._frame
                self._callback_done(assembled)

            self._units.clear()
            self._raw_units.clear()

    @property
    def frame(self) -> int:
        """Return Current Frame Index."""
        return self._frame

    @property
    def last_complete(self) -> int:
        """Return Last Completed Frame Index."""
        return self._last_complete

    @property
    def lost(self) -> int:
        """Return Total AV packets lost."""
        return self._lost

    @property
    def received(self) -> int:
        """Return Total AV packets received."""
        return self._received
