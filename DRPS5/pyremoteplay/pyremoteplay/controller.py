"""Controller methods."""
from __future__ import annotations
import logging
import threading
import sys
import traceback
from typing import Iterable, Union
from collections import deque
from enum import IntEnum, auto
import time
import asyncio

from .stream_packets import FeedbackEvent, FeedbackHeader, ControllerState, StickState
from .errors import RemotePlayError
from .session import Session

_LOGGER = logging.getLogger(__name__)


class Controller:
    """Controller Interface. Sends user input to Remote Play Session."""

    class ButtonAction(IntEnum):
        """Button Action Types."""

        PRESS = auto()
        RELEASE = auto()
        TAP = auto()

    MAX_EVENTS = 5
    STATE_INTERVAL_MAX_MS = 0.064
    STATE_INTERVAL_MIN_MS = 0.0075

    @staticmethod
    def buttons() -> list:
        """Return list of valid buttons."""
        return [button.name for button in FeedbackEvent.Type]

    def __init__(self, session=None):
        self._session = session
        self._sequence_event = 0
        self._sequence_state = 0
        self._last_state_time = 0.0
        self._event_buf = deque([], Controller.MAX_EVENTS)
        self._last_state = ControllerState()
        self._stick_state = ControllerState()
        self._stick_lock = threading.Lock()

        self._should_send = threading.Semaphore()
        self._stop_event = threading.Event()
        self._thread: threading.Thread = None

    def __del__(self):
        self.disconnect()

    def __reset_session(self):
        self._sequence_event = 0
        self._sequence_state = 0
        self._last_state_time = 0.0
        self._event_buf = deque([], Controller.MAX_EVENTS)
        self._last_state = ControllerState()
        self._stick_state = ControllerState()

    def __reset_worker(self):
        self._should_send = threading.Semaphore()
        self._stop_event = threading.Event()
        self._thread = None

    def __worker(self):
        """Worker for sending feedback packets. Run in thread."""
        self._should_send.acquire(timeout=1)
        while self.running:
            try:
                self._should_send.acquire(timeout=Controller.STATE_INTERVAL_MAX_MS)
                if self.ready:
                    self.update_sticks()
            except Exception as error:  # pylint: disable=broad-except
                _LOGGER.error("Error in controller thread: %s", error)
                if _LOGGER.level == logging.DEBUG:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    traceback.print_exception(
                        exc_type, exc_value, exc_traceback, file=sys.stdout
                    )
        self.__reset_worker()
        _LOGGER.info("Controller stopped")

    def connect(self, session: Session):
        """Connect controller to session."""
        if self._session is not None:
            _LOGGER.warning("Controller already connected. Call `disconnect()` first")
            return

        if session is not None:
            if not isinstance(session, Session):
                raise TypeError(f"Expected {Session}. Got {type(session)}")
            if session.is_running:
                raise RemotePlayError("Cannot set a running session")
            if session.is_stopped:
                raise RemotePlayError("Cannot set a stopped session")

        self.__reset_session()
        self.__reset_worker()
        self._session = session

    def start(self):
        """Start Controller.

        This starts the controller worker which listens for when the sticks move
        and sends the state to the host. If this is not called, the
        :meth:`update_sticks() <pyremoteplay.controller.Controller.update_sticks>`
        method needs to be called for the host to receive the state.
        """
        if self._thread is not None:
            _LOGGER.warning("Controller is running. Call `stop()` first")
            return
        if self._session is None:
            _LOGGER.warning("Controller has no session. Call `connect()` first")
            return
        self._thread = threading.Thread(target=self.__worker, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop Controller."""
        self._stop_event.set()

    def disconnect(self):
        """Stop and Disconnect Controller. Must be called to change session."""
        self.stop()
        self.__reset_session()
        self._session = None

    def update_sticks(self):
        """Send controller stick state to host con ritmo de hasta ~125Hz y tolerancia a pérdidas UDP."""
        try:
            if not self._check_session() or not getattr(self._session, "stream", None):
                return
            with self._stick_lock:
                now = time.time()
                state_changed = (self.stick_state != self._last_state)
                is_centered = (self.stick_state.left.x == 0 and self.stick_state.left.y == 0 and
                               self.stick_state.right.x == 0 and self.stick_state.right.y == 0)
                if not state_changed and (now - self._last_state_time < 0.064):
                    return
                if state_changed and not is_centered and (now - self._last_state_time < self.STATE_INTERVAL_MIN_MS):
                    return
                self._last_state_time = now
                self._last_state.left = StickState(self.stick_state.left.x, self.stick_state.left.y)
                self._last_state.right = StickState(self.stick_state.right.x, self.stick_state.right.y)

                repeats = 3 if (state_changed and is_centered) else 1
                for _ in range(repeats):
                    self._session.stream.send_feedback(
                        FeedbackHeader.Type.STATE, self._sequence_state, state=self.stick_state
                    )
                    self._sequence_state = (self._sequence_state + 1) & 0xFFFF
        except Exception as error:
            _LOGGER.debug("Error enviando estado de sticks: %s", error)

    def touchpad(self, down: bool, pointer_id: int = 0, x: int = 960, y: int = 470, repeats: int = 1):
        """Send 5-byte PS5 Takion touchpad coordinate event (0..1919, 0..941)."""
        try:
            if not self._check_session() or not getattr(self._session, "stream", None):
                return
            cx = max(0, min(1919, int(x)))
            cy = max(0, min(941, int(y)))
            data = bytes([
                0xD0 if down else 0xC0,
                pointer_id & 0x7F,
                (cx >> 4) & 0xFF,
                ((cx & 0x0F) << 4) | ((cy >> 8) & 0x0F),
                cy & 0xFF,
            ])
            for _ in range(max(1, repeats)):
                self._session.stream.send_feedback(
                    FeedbackHeader.Type.EVENT, self._sequence_event, data=data, count=1
                )
                self._sequence_event = (self._sequence_event + 1) & 0xFFFF
        except Exception as error:
            _LOGGER.debug("Error enviando touchpad: %s", error)

    def _send_event(self):
        """Send controller button event con triple redundancia UDP limpia sin arrastrar eventos antiguos."""
        try:
            if not self._event_buf or not getattr(self._session, "stream", None):
                return
            # Tomar únicamente el evento más reciente (el que acaba de ocurrir)
            data = bytes(self._event_buf[0])
            if not data:
                return
            # Envío triple inmediato del evento específico para tolerancia a pérdidas UDP en WiFi
            for _ in range(3):
                self._session.stream.send_feedback(
                    FeedbackHeader.Type.EVENT, self._sequence_event, data=data, count=1
                )
                self._sequence_event = (self._sequence_event + 1) & 0xFFFF
            self._last_event_time = time.time()
        except Exception as error:
            _LOGGER.debug("Error enviando evento de mando: %s", error)

    def _add_event_buffer(self, event: FeedbackEvent):
        """Append event to beginning of byte buffer.
        Oldest event is at the end and is removed
        when buffer is full and a new event is added
        """
        buf = bytearray(FeedbackEvent.LENGTH)
        event.pack(buf)
        self._event_buf.appendleft(buf)

    def _button(
        self,
        name: Union[str, FeedbackEvent.Type],
        action: Union[str, ButtonAction],
    ) -> tuple[FeedbackEvent.Type, ButtonAction]:
        if not self._check_session():
            return None
        if isinstance(action, self.ButtonAction):
            _action = action
        else:
            try:
                _action = self.ButtonAction[action.upper()]
            except KeyError:
                _LOGGER.error("Invalid Action: %s", action)
                return None
        if isinstance(name, FeedbackEvent.Type):
            button = name
        else:
            try:
                button = FeedbackEvent.Type[name.upper()]
            except KeyError:
                _LOGGER.error("Invalid button: %s", name)
                return None

        if _action == self.ButtonAction.PRESS:
            self._add_event_buffer(FeedbackEvent(button, is_active=True))
        elif _action == self.ButtonAction.RELEASE:
            self._add_event_buffer(FeedbackEvent(button, is_active=False))
        elif _action == self.ButtonAction.TAP:
            self._add_event_buffer(FeedbackEvent(button, is_active=True))
        self._send_event()
        return button, _action

    def button(
        self,
        name: Union[str, FeedbackEvent.Type],
        action: Union[str, ButtonAction] = "tap",
        delay=0.1,
    ):
        """Emulate pressing or releasing button.

        If action is `tap` this method will block by delay.

        :param name: The name of button. Use buttons() to show valid buttons.
        :param action: One of `press`, `release`, `tap`, or `Controller.ButtonAction`.
        :param delay: Delay between press and release. Only used when action is `tap`.
        """
        data = self._button(name, action)
        if not data:
            return
        button, _action = data
        if _action == self.ButtonAction.TAP:
            time.sleep(delay)
            self.button(button, self.ButtonAction.RELEASE)

    async def async_button(
        self,
        name: Union[str, FeedbackEvent.Type],
        action: Union[str, ButtonAction] = "tap",
        delay=0.1,
    ):
        """Emulate pressing or releasing button. Async.

        If action is `tap` this coroutine will sleep by delay.

        :param name: The name of button. Use buttons() to show valid buttons.
        :param action: One of `press`, `release`, `tap`, or `Controller.ButtonAction`.
        :param delay: Delay between press and release. Only used when action is `tap`.
        """
        data = self._button(name, action)
        if not data:
            return
        button, _action = data
        if _action == self.ButtonAction.TAP:
            await asyncio.sleep(delay)
            await self.async_button(button, self.ButtonAction.RELEASE)

    def stick(
        self,
        stick_name: str,
        axis: str = None,
        value: float = None,
        point: Iterable[float, float] = None,
    ):
        """Set Stick State.

        If controller has not been started with
        :meth:`start() <pyremoteplay.controller.Controller.start>`,
        the :meth:`update_sticks() <pyremoteplay.controller.Controller.update_sticks>`
        method needs to be called manually to send stick state.

        The value param represents how far to push the stick away from center.

        The direction mapping is shown below:

        X Axis: Left -1.0, Right 1.0

        Y Axis: Up -1.0, Down 1.0

        Center 0.0

        :param stick_name: The stick to move. One of 'left' or 'right'
        :param axis: The axis to move. One of 'x' or 'y'
        :param value: The value to move stick to. Must be between -1.0 and 1.0
        :param point: An iterable of two floats, which represent coordinates.
            Point takes precedence over axis and value.
            The first value represents the x axis and the second represents the y axis
        """
        stick_name = stick_name.lower()
        if stick_name == "left":
            stick = self._stick_state.left
        elif stick_name == "right":
            stick = self._stick_state.right
        else:
            raise ValueError("Invalid stick: Expected 'left', 'right'")

        with self._stick_lock:
            if point is not None:
                state = StickState(*point)
                if stick_name == "left":
                    self._stick_state.left = state
                else:
                    self._stick_state.right = state
                self._should_send.release()
                return

            if axis is None or value is None:
                raise ValueError("Axis and Value can not be None")
            axis = axis.lower()
            values = [stick.x, stick.y]
            if axis == "x":
                values[0] = value
            elif axis == "y":
                values[1] = value
            else:
                raise ValueError("Invalid axis: Expected 'x', 'y'")
            state = StickState(*values)
            if stick_name == "left":
                self._stick_state.left = state
            else:
                self._stick_state.right = state
            self._should_send.release()

    def _check_session(self) -> bool:
        if self.session is None:
            _LOGGER.warning("Controller has no session")
            return False
        if self.session.is_stopped:
            _LOGGER.warning("Session is stopped")
            return False
        if not (self.session.is_ready or self.session.is_running):
            _LOGGER.warning("Session is not ready")
            return False
        return True

    @property
    def stick_state(self) -> ControllerState:
        """Return stick state."""
        return self._stick_state

    @property
    def running(self) -> bool:
        """Return True if running."""
        if not self._session:
            return False
        return not self._session.is_stopped and not self._stop_event.is_set()

    @property
    def ready(self) -> bool:
        """Return True if controller can be used"""
        if not self.session:
            return False
        return self.session.is_ready

    @property
    def session(self) -> Session:
        """Return Session."""
        return self._session
