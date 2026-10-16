"""DataUpdateCoordinator for Fermax NOWIFI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import FermaxNowifiApi
from .const import (
    CONF_DOOR_PARAMS,
    CONF_HOUSE_ID,
    CONF_HOUSE_TAG,
    CONF_PANEL_ID,
    CONF_STREAM_DURATION,
    DEFAULT_SIGNALING_URL,
    DEFAULT_STREAM_DURATION,
    DOMAIN,
    DOORBELL_RESET_SECONDS,
    SIGNAL_CALL_ENDED,
    SIGNAL_CAMERA_OFF,
    SIGNAL_CAMERA_ON,
    SIGNAL_DOOR_OPENED,
    SIGNAL_DOORBELL_RING,
)
from .notification import FermaxNotificationListener
from .streaming import FermaxStreamSession

_LOGGER = logging.getLogger(__name__)


class FermaxNowifiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing Fermax NOWIFI cloud connection, FCM push, and streaming."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: FermaxNowifiApi,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get(CONF_HOUSE_ID, 'nowifi')}",
            update_interval=timedelta(minutes=5),
        )
        self.entry = entry
        self.api = api

        self.house_id: str = entry.data[CONF_HOUSE_ID]
        self.panel_id: str = entry.data.get(CONF_PANEL_ID, "203730463032500a006e004c")
        self.house_tag: str = entry.data.get(CONF_HOUSE_TAG, "Casa")
        self.door_params: dict[str, int] = entry.data.get(
            CONF_DOOR_PARAMS, {"block": 0, "subblock": 0, "number": 1}
        )
        self.stream_duration: int = entry.options.get(
            CONF_STREAM_DURATION, DEFAULT_STREAM_DURATION
        )

        self.notification_listener: FermaxNotificationListener | None = None
        self.stream_session: FermaxStreamSession | None = None

        self.is_ringing: bool = False
        self.camera_active: bool = False
        self.panel_state: str = "En reposo"
        self.last_ring_time: str | None = None
        self.last_photo: bytes | None = None
        self.last_photo_time: str | None = None

        self._camera_auto_off_unsub: Any = None
        self._doorbell_reset_unsub: Any = None

    @property
    def is_streaming(self) -> bool:
        """Return True if a Mediasoup video stream is active."""
        return self.stream_session is not None and self.stream_session.is_active

    @property
    def latest_frame(self) -> bytes | None:
        """Return the most recent JPEG video frame."""
        if self.stream_session:
            return self.stream_session.latest_frame
        return self.last_photo

    async def async_setup(self) -> None:
        """Initialize FCM listener and register app token with Fermax."""
        self.notification_listener = FermaxNotificationListener(
            self.hass, self._handle_fcm_notification
        )
        fcm_token = await self.notification_listener.register()
        if fcm_token:
            _LOGGER.info("FCM push token registered: %s...", fcm_token[:20])
            await self.api.register_app_token(fcm_token)
        await self.notification_listener.start()

    async def async_shutdown(self) -> None:
        """Clean up streaming sessions, timers, and listeners on integration unload."""
        await self.stop_camera_preview()
        if self.notification_listener:
            await self.notification_listener.stop()
        await self.api.close()

    def _handle_fcm_notification(
        self, notification: dict[str, Any], persistent_id: str
    ) -> None:
        """Process incoming push notification from Fermax Cloud."""
        data = notification.get("data", {})
        notif_type = data.get("FermaxNotificationType", "")
        room_id = data.get("RoomId")
        socket_url = data.get("SocketUrl", DEFAULT_SIGNALING_URL)
        fermax_token = data.get("FermaxToken", self.api.access_token)
        fcm_msg_id = notification.get("fcmMessageId", persistent_id)

        _LOGGER.info(
            "Fermax push event: type=%s, room=%s (id=%s)",
            notif_type,
            room_id,
            persistent_id,
        )

        # Ignore stale room notifications received during listener reconnect
        if room_id and "_" in room_id:
            try:
                room_ts = int(room_id.split("_")[-1])
                now_ms = time.time() * 1000
                if room_ts < (now_ms - 30000):
                    _LOGGER.info("Ignoring stale room notification: %s", room_id)
                    return
            except Exception:
                pass

        # Confirm receipt
        self.hass.async_create_task(
            self.api.ack_notification(fcm_msg_id, is_call=(notif_type == "Call"))
        )

        # Handle Doorbell Ring
        if notif_type == "Call":
            self.is_ringing = True
            self.panel_state = "Llamando al timbre"
            self.last_ring_time = datetime.now().strftime("%H:%M:%S")

            async_dispatcher_send(
                self.hass, SIGNAL_DOORBELL_RING.format(self.house_id)
            )

            # Timer to reset ringing sensor if not answered
            if self._doorbell_reset_unsub:
                self._doorbell_reset_unsub()

            @callback
            def _reset_doorbell(_now: Any) -> None:
                self.is_ringing = False
                if not self.camera_active:
                    self.panel_state = "En reposo"
                async_dispatcher_send(
                    self.hass, SIGNAL_CALL_ENDED.format(self.house_id)
                )
                self.async_set_updated_data(self._build_coordinator_data())
                self._doorbell_reset_unsub = None

            self._doorbell_reset_unsub = async_call_later(
                self.hass, DOORBELL_RESET_SECONDS, _reset_doorbell
            )

            # USER REQUIREMENT: Automatically start camera stream when doorbell rings!
            if room_id:
                _LOGGER.info("Doorbell ringing: automatically activating camera stream")
                self.camera_active = True
                self._start_camera_auto_off_timer()
                self.hass.async_create_task(
                    self._start_stream_session(room_id, socket_url, fermax_token)
                )

        elif notif_type == "Autoon":
            # If camera auto-on was requested, attach to the room
            if room_id and self.camera_active:
                self.hass.async_create_task(
                    self._start_stream_session(room_id, socket_url, fermax_token)
                )

        elif notif_type == "CallEnd":
            _LOGGER.info("Call ended by outdoor panel")
            self.is_ringing = False
            self.hass.async_create_task(self.stop_camera_preview())
            async_dispatcher_send(self.hass, SIGNAL_CALL_ENDED.format(self.house_id))

        self.async_set_updated_data(self._build_coordinator_data())

    async def _start_stream_session(
        self, room_id: str, socket_url: str, fermax_token: str
    ) -> None:
        """Start Mediasoup WebRTC stream session for the given room."""
        if self.stream_session:
            await self.stream_session.stop()
            self.stream_session = None

        fcm_token = self.notification_listener.fcm_token if self.notification_listener else ""

        def _on_session_end() -> None:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.stop_camera_preview())
            )

        def _on_frame(frame_bytes: bytes) -> None:
            self.last_photo = frame_bytes

        session = FermaxStreamSession(
            signaling_url=socket_url,
            oauth_token=fermax_token,
            fcm_token=fcm_token or "",
            room_id=room_id,
            on_end=_on_session_end,
            on_frame=_on_frame,
        )

        started = await session.start()
        if started:
            self.stream_session = session
            self.panel_state = "Cámara en directo"
            async_dispatcher_send(self.hass, SIGNAL_CAMERA_ON.format(self.house_id))
            _LOGGER.info("Live camera stream active for room %s", room_id)
        else:
            _LOGGER.error("Failed to establish video stream with Mediasoup SFU")
            self.camera_active = False
            self.panel_state = "En reposo"

        self.async_set_updated_data(self._build_coordinator_data())

    def _start_camera_auto_off_timer(self) -> None:
        """Start auto-off timer: turns off camera after stream_duration (default 65s)."""
        if self._camera_auto_off_unsub:
            self._camera_auto_off_unsub()

        @callback
        def _auto_off(_now: Any) -> None:
            _LOGGER.info(
                "Camera auto-off timer (%ds) elapsed: turning off camera",
                self.stream_duration,
            )
            self.hass.async_create_task(self.stop_camera_preview())
            self._camera_auto_off_unsub = None

        self._camera_auto_off_unsub = async_call_later(
            self.hass, self.stream_duration, _auto_off
        )

    async def start_camera_preview(self) -> bool:
        """Turn on the camera via auto-on. Starts the 65s auto-off timer."""
        if not self.notification_listener or not self.notification_listener.fcm_token:
            _LOGGER.error("Cannot turn on camera: FCM push listener not ready")
            return False

        self.camera_active = True
        self.panel_state = "Iniciando cámara..."
        self._start_camera_auto_off_timer()

        result = await self.api.auto_on(
            self.panel_id,
            self.notification_listener.fcm_token,
            self.house_id,
        )

        if not result:
            self.camera_active = False
            self.panel_state = "En reposo"
            if self._camera_auto_off_unsub:
                self._camera_auto_off_unsub()
                self._camera_auto_off_unsub = None
            self.async_set_updated_data(self._build_coordinator_data())
            return False

        if result.get("busy"):
            self.panel_state = "Placa ocupada"
            self.camera_active = False
            if self._camera_auto_off_unsub:
                self._camera_auto_off_unsub()
                self._camera_auto_off_unsub = None
            self.async_set_updated_data(self._build_coordinator_data())
            return False

        self.async_set_updated_data(self._build_coordinator_data())
        return True

    async def stop_camera_preview(self) -> None:
        """Turn off camera immediately and disconnect streaming session."""
        if self._camera_auto_off_unsub:
            self._camera_auto_off_unsub()
            self._camera_auto_off_unsub = None

        self.camera_active = False
        if not self.is_ringing:
            self.panel_state = "En reposo"

        if self.stream_session:
            await self.stream_session.stop()
            self.stream_session = None

        async_dispatcher_send(self.hass, SIGNAL_CAMERA_OFF.format(self.house_id))
        self.async_set_updated_data(self._build_coordinator_data())

    async def open_door(self, number: int = 1) -> bool:
        """Open door. Uses incall endpoint if camera/call is active, else directOpenDoorNoWifi."""
        success = False

        if self.is_streaming and self.stream_session:
            fcm_token = (
                self.notification_listener.fcm_token
                if self.notification_listener
                else ""
            )
            _LOGGER.info("Opening door via in-call endpoint during active stream")
            success = await self.api.open_door_incall(
                panel_id=self.panel_id,
                room_id=self.stream_session.room_id,
                fcm_token=fcm_token or "",
                house_id=self.house_id,
            )

        if not success:
            _LOGGER.info("Opening door via directOpenDoorNoWifi (relay #%d)", number)
            block = self.door_params.get("block", 0)
            subblock = self.door_params.get("subblock", -1)
            door_num = self.door_params.get("number", 0) if number == 1 else number
            _LOGGER.info("Opening door via directOpenDoorNoWifi (block=%d, subblock=%d, number=%d)", block, subblock, door_num)
            success = await self.api.open_door_nowifi(
                panel_id=self.panel_id,
                house_id=self.house_id,
                block=block,
                subblock=subblock,
                number=door_num,
            )

        if success:
            _LOGGER.info("Door opened successfully")
            if self.is_ringing:
                self.is_ringing = False
                if self._doorbell_reset_unsub:
                    self._doorbell_reset_unsub()
                    self._doorbell_reset_unsub = None
                async_dispatcher_send(
                    self.hass, SIGNAL_CALL_ENDED.format(self.house_id)
                )

            async_dispatcher_send(
                self.hass, SIGNAL_DOOR_OPENED.format(self.house_id)
            )

        self.async_set_updated_data(self._build_coordinator_data())
        return success

    async def press_f1(self) -> bool:
        """Trigger F1 auxiliary function (courtesy light / secondary relay)."""
        return await self.api.press_f1(self.house_id)

    def _build_coordinator_data(self) -> dict[str, Any]:
        return {
            "is_ringing": self.is_ringing,
            "camera_active": self.camera_active,
            "is_streaming": self.is_streaming,
            "panel_state": self.panel_state,
            "last_ring_time": self.last_ring_time,
            "has_photo": self.last_photo is not None,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Periodic background refresh / watchdog verification."""
        if self.notification_listener:
            await self.notification_listener.ensure_running()
        return self._build_coordinator_data()
