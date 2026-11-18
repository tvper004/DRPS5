"""AV Receivers for pyremoteplay."""

from __future__ import annotations
import abc
import time
from struct import unpack_from
import warnings
import logging
from collections import deque
from typing import Sequence, TYPE_CHECKING

from pyremoteplay.const import FFMPEG_PADDING

if TYPE_CHECKING:
    from pyremoteplay.session import Session

_LOGGER = logging.getLogger(__name__)

try:
    import av
except ModuleNotFoundError:
    warnings.warn("av not installed")


class AVReceiver(abc.ABC):
    """Base Class for AV Receiver. Abstract. Must use subclass for session.

    This class exposes the audio/video stream of the Remote Play Session.
    The `handle_video` and `handle_audio` methods need to be reimplemented.
    Re-implementing this class provides custom handling of audio and video frames.
    """

    AV_CODEC_OPTIONS_H264 = {
        # "profile": "0",
        # "level": "3.2",
        "tune": "zerolatency",
        "preset": "ultrafast",
    }

    AV_CODEC_OPTIONS_HEVC = {
        "tune": "zerolatency",
        "preset": "ultrafast",
    }

    @staticmethod
    def audio_frame(
        buf: bytes,
        codec_ctx: av.CodecContext,
        resampler: av.audio.resampler.AudioResampler = None,
    ) -> av.AudioFrame:
        """Return decoded audio frame."""
        if not codec_ctx or not buf or len(buf) < 2:
            return None
        frames = None
        packet = av.packet.Packet(buf)
        try:
            frames = codec_ctx.decode(packet)
        except av.error.InvalidDataError as error:
            now = time.time()
            if not hasattr(AVReceiver, "_last_audio_err_log") or now - AVReceiver._last_audio_err_log > 3.0:
                _LOGGER.warning("Error decodificando audio Opus (throttled): %s", error)
                AVReceiver._last_audio_err_log = now
            return None
        except Exception:
            return None

        if not frames:
            return None
        frame = frames[0]
        if getattr(frame, "is_corrupt", False):
            now = time.time()
            if not hasattr(AVReceiver, "_last_audio_corrupt_log") or now - AVReceiver._last_audio_corrupt_log > 3.0:
                _LOGGER.warning("Corrupt audio frame received (throttled)")
                AVReceiver._last_audio_corrupt_log = now
            return None

        if resampler:
            try:
                frames = resampler.resample(frame)
                if not frames:
                    return None

                # For av > 9.0.0
                if isinstance(frames, Sequence):
                    frame = frames[0]
                else:
                    frame = frames
            except Exception:
                return None
        return frame

    @staticmethod
    def video_frame(
        buf: bytes, codec_ctx: av.CodecContext, video_format="rgb24"
    ) -> av.VideoFrame:
        """Decode H264 Frame to raw image.
        Return AV Frame.

        :param buf: Raw Video Packet representing one video frame
        :param codec_ctx: av codec context for decoding
        :param video_format: Format to output frames as.
        """
        if not codec_ctx or not buf or len(buf) < 2:
            return None
        frames = None
        packet = av.packet.Packet(b"".join([buf, bytes(FFMPEG_PADDING)]))
        try:
            frames = codec_ctx.decode(packet)
        except av.error.InvalidDataError as error:
            now = time.time()
            if not hasattr(AVReceiver, "_last_video_err_log") or now - AVReceiver._last_video_err_log > 3.0:
                _LOGGER.warning("Error decodificando vídeo (throttled): %s", error)
                AVReceiver._last_video_err_log = now
            return None
        except Exception:
            return None

        if not frames:
            return None
        frame = frames[0]
        if getattr(frame, "is_corrupt", False):
            now = time.time()
            if not hasattr(AVReceiver, "_last_video_corrupt_log") or now - AVReceiver._last_video_corrupt_log > 5.0:
                _LOGGER.debug("Descartando fotograma corrupto para evitar artefactos verdes/grises en pantalla")
                AVReceiver._last_video_corrupt_log = now
            return None

        if frame.format.name != video_format:
            try:
                frame = frame.reformat(frame.width, frame.height, video_format)
            except Exception:
                return None
        return frame

    @staticmethod
    def video_codec(codec_name: str) -> av.CodecContext:
        """Return Video Codec Context."""
        try:
            codec_ctx = av.codec.Codec(codec_name, "r").create()
        except av.codec.codec.UnknownCodecError:
            _LOGGER.error("Invalid codec: %s", codec_name)
        _LOGGER.info("Using Decoder: %s", codec_name)
        if codec_name.startswith("h264"):
            codec_ctx.options = AVReceiver.AV_CODEC_OPTIONS_H264
            codec_ctx.pix_fmt = "yuv420p"
        elif codec_name.startswith("hevc"):
            codec_ctx.options = AVReceiver.AV_CODEC_OPTIONS_HEVC
        try:
            if hasattr(av.codec.context.Flags, "low_delay"):
                codec_ctx.flags = av.codec.context.Flags.low_delay
            elif hasattr(av.codec.context.Flags, "LOW_DELAY"):
                codec_ctx.flags = av.codec.context.Flags.LOW_DELAY
        except Exception:
            pass

        try:
            if hasattr(av.codec.context.Flags2, "fast"):
                codec_ctx.flags2 = av.codec.context.Flags2.fast
            elif hasattr(av.codec.context.Flags2, "FAST"):
                codec_ctx.flags2 = av.codec.context.Flags2.FAST
        except Exception:
            pass

        try:
            codec_ctx.thread_type = av.codec.context.ThreadType.SLICE
            codec_ctx.thread_count = 4
        except Exception:
            pass
        return codec_ctx

    @staticmethod
    def audio_codec(codec_name: str = "opus") -> av.CodecContext:
        """Return Audio Codec Context."""
        codec_ctx = av.codec.Codec(codec_name, "r").create()
        codec_ctx.format = "s16"
        return codec_ctx

    @staticmethod
    def audio_resampler(
        audio_format: str = "s16", channels=2, rate=48000
    ) -> av.audio.resampler.AudioResampler:
        """Return Audio Resampler."""
        resampler = None
        if isinstance(channels, int):
            layout = "stereo" if channels == 2 else "mono" if channels == 1 else "5.1" if channels == 6 else "7.1" if channels == 8 else "stereo"
        else:
            layout = channels or "stereo"
        try:
            resampler = av.audio.resampler.AudioResampler(
                format=audio_format,
                layout=layout,
                rate=rate,
            )
        except Exception:
            try:
                resampler = av.audio.resampler.AudioResampler(
                    audio_format,
                    layout,
                    rate,
                )
            except Exception as error:
                _LOGGER.error("Error getting audio resampler: %s", error)
        return resampler

    def __init__(self):
        self._session: Session = None
        self._video_format = "rgb24"
        self._video_decoder = None
        self._audio_decoder = None
        self._audio_resampler = None
        self._audio_config = {}
        self._consecutive_audio_errors = 0
        self._last_audio_error_time = 0.0
        self._last_audio_reset_time = 0.0

    def _set_session(self, session: Session):
        self._session = session

    def _get_audio_codec(self, header: bytes):
        """Get Audio config from header. Get Audio codec."""
        self._audio_config = {
            "channels": header[0],
            "bits": header[1],
            "rate": unpack_from("!I", header, 2)[0],
            "frame_size": unpack_from("!I", header, 6)[0],
            "unknown": unpack_from("!I", header, 10)[0],
        }
        self._audio_config["packet_size"] = (
            self._audio_config["channels"]
            * (self._audio_config["bits"] // 8)
            * self._audio_config["frame_size"]
        )
        _LOGGER.info("Audio Config: %s", self._audio_config)

        if not self._audio_decoder:
            self._audio_decoder = AVReceiver.audio_codec()
            try:
                self._audio_decoder.open()
            except Exception as err:
                _LOGGER.debug("Audio decoder open: %s", err)
            # Need format to be s16. Format is float.
            self._audio_resampler = AVReceiver.audio_resampler(
                "s16",
                self._audio_config["channels"],
                self._audio_config["rate"],
            )
            self._session.events.emit("audio_config")

    def _get_video_codec(self):
        """Get Video Codec Context."""
        codec_name = self._session.codec
        self._video_decoder = AVReceiver.video_codec(codec_name)
        try:
            self._video_decoder.open()
        except av.error.ValueError as error:
            if self._session:
                try:
                    msg = error.log[2]
                except Exception:  # pylint: disable=broad-except
                    msg = str(error)
                self._session.error = msg
                self._session.stop()

    def decode_video_frame(self, buf: bytes) -> av.VideoFrame:
        """Return decoded Video Frame."""
        if not self._video_decoder:
            _LOGGER.warning("Video decoder not created.")
            return None
        frame = AVReceiver.video_frame(buf, self._video_decoder, self.video_format)
        return frame

    def decode_audio_frame(self, buf: bytes) -> av.AudioFrame:
        """Return decoded Audio Frame."""
        if not self._audio_config or not self._audio_decoder:
            return None
        return AVReceiver.audio_frame(buf, self._audio_decoder, self._audio_resampler)

    def handle_video_data(self, buf: bytes):
        """Handle video data."""
        frame = self.decode_video_frame(buf)
        if frame is not None:
            self.handle_video(frame)

    def handle_audio_data(self, buf: bytes):
        """Handle audio data."""
        frame = self.decode_audio_frame(buf)
        if frame is not None:
            self.handle_audio(frame)

    def handle_video(self, frame: av.VideoFrame):
        """Handle video frame. Re-implementation required.

        This method is called as soon as a video frame is decoded.
        This method should define what should happen when this frame is received.
        For example the frame can be stored, sent somewhere, processed further, etc.
        """
        raise NotImplementedError

    def handle_audio(self, frame: av.AudioFrame):
        """Handle audio frame. Re-implementation required.

        This method is called as soon as an audio frame is decoded.
        This method should define what should happen when this frame is received.
        For example the frame can be stored, sent somewhere, processed further, etc.
        """
        raise NotImplementedError

    def get_video_frame(self) -> av.VideoFrame:
        """Return Video Frame. Re-implementation optional.

        This method is a placeholder for retrieving a frame from a collection.
        """
        raise NotImplementedError

    def get_audio_frame(self) -> av.AudioFrame:
        """Return Audio Frame. Re-implementation optional.

        This method is a placeholder for retrieving a frame from a collection.
        """
        raise NotImplementedError

    def close(self):
        """Close Receiver."""
        if self._video_decoder is not None:
            self._video_decoder.close()
        if self._audio_decoder is not None:
            self._audio_decoder.close()
        self._video_decoder = self._audio_decoder = None

    @property
    def video_format(self):
        """Return Video Format Name."""
        return self._video_format

    @video_format.setter
    def video_format(self, video_format: str):
        """Set Video Format."""
        self._video_format = video_format

    @property
    def video_decoder(self) -> av.CodecContext:
        """Return Video Codec Context."""
        return self._video_decoder

    @property
    def audio_decoder(self) -> av.CodecContext:
        """Return Audio Codec Context."""
        return self._audio_decoder

    @property
    def audio_config(self) -> dict:
        """Return Audio config."""
        return dict(self._audio_config)


class QueueReceiver(AVReceiver):
    """Receiver which stores decoded frames in queues.
    New Frames are added to the end of queue.
    When queue is full the oldest frame is removed.

    :param max_frames: Maximum number of frames to be stored. Will be at least 1.
    :param max_video_frames: Maximum video frames that can be stored.
        If <= 0, max_frames will be used.
    :param max_audio_frames: Maximum audio frames that can be stored.
        If <= 0, max_frames will be used.
    """

    def __init__(self, max_frames=10, max_video_frames=-1, max_audio_frames=-1):
        super().__init__()
        max_frames = max(1, max_frames)
        max_video_frames = max_frames if max_video_frames <= 0 else max_video_frames
        max_audio_frames = max_frames if max_audio_frames <= 0 else max_audio_frames
        self._v_queue = deque(maxlen=max_video_frames)
        self._a_queue = deque(maxlen=max_audio_frames)

    def close(self):
        """Close Receiver."""
        super().close()
        self._v_queue.clear()
        self._a_queue.clear()

    def get_video_frame(self) -> av.VideoFrame:
        """Return oldest Video Frame from queue."""
        try:
            frame = self._v_queue[0]
            return frame
        except IndexError:
            return None

    def get_audio_frame(self) -> av.AudioFrame:
        """Return oldest Audio Frame from queue."""
        try:
            frame = self._a_queue[0]
            return frame
        except IndexError:
            return None

    def get_latest_video_frame(self) -> av.VideoFrame:
        """Return latest Video Frame from queue."""
        try:
            frame = self._v_queue[-1]
            return frame
        except IndexError:
            return None

    def get_latest_audio_frame(self) -> av.AudioFrame:
        """Return latest Audio Frame from queue."""
        try:
            frame = self._a_queue[-1]
            return frame
        except IndexError:
            return None

    def handle_video(self, frame: av.VideoFrame):
        """Handle video frame. Add to queue."""
        self._v_queue.append(frame)
        self._session.events.emit("video_frame")

    def handle_audio(self, frame: av.AudioFrame):
        """Handle Audio Frame. Add to queue."""
        self._a_queue.append(frame)
        self._session.events.emit("audio_frame")

    @property
    def video_frames(self) -> list[av.VideoFrame]:
        """Return Latest Video Frames."""
        frames = list(self._v_queue)
        return frames

    @property
    def audio_frames(self) -> list[av.AudioFrame]:
        """Return Latest Audio Frames."""
        frames = list(self._a_queue)
        return frames
