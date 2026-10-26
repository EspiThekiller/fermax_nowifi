"""Camera entity for Fermax NOWIFI."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION, MANUFACTURER, MODEL_NOWIFI
from .coordinator import FermaxNowifiCoordinator
from .streaming import WEBRTC_AVAILABLE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fermax NOWIFI camera."""
    coordinator: FermaxNowifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FermaxNowifiCamera(coordinator)])


def _create_standby_image(
    text: str = "FERMAX NOWIFI • En reposo",
    subtitle: str = "La cámara se activa automáticamente al llamar o por switch",
) -> bytes:
    """Generate a clean 720x480 standby placeholder JPEG in memory."""
    img = Image.new("RGB", (720, 480), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.rectangle([(20, 20), (700, 460)], outline=(30, 41, 59), width=2)
    draw.text((220, 225), text, fill=(148, 163, 184), font=font)
    draw.text((180, 255), subtitle, fill=(71, 85, 105), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


_STANDBY_IMAGE = _create_standby_image()


class FermaxNowifiCamera(CoordinatorEntity[FermaxNowifiCoordinator], Camera):
    """Camera entity displaying the live video feed of the Fermax outdoor panel."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)

        self._attr_unique_id = f"{coordinator.house_id}_camera"
        self._attr_name = "Cámara Placa Exterior"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.house_id)},
            name=f"Fermax NOWIFI ({coordinator.house_tag})",
            manufacturer=MANUFACTURER,
            model=MODEL_NOWIFI,
            sw_version=INTEGRATION_VERSION,
        )

    @property
    def is_on(self) -> bool:
        """Return True if camera stream or preview is active."""
        return self.coordinator.camera_active or self.coordinator.is_streaming

    @property
    def is_recording(self) -> bool:
        return False

    @property
    def is_streaming(self) -> bool:
        """Return True if WebRTC stream is currently active."""
        return self.coordinator.is_streaming

    async def async_turn_on(self) -> None:
        """Turn on the camera preview via coordinator."""
        await self.coordinator.start_camera_preview()

    async def async_turn_off(self) -> None:
        """Turn off the camera preview via coordinator."""
        await self.coordinator.stop_camera_preview()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of the latest JPEG frame."""
        frame = self.coordinator.latest_frame
        if frame:
            return frame

        if not WEBRTC_AVAILABLE and self.coordinator.camera_active:
            return await asyncio.to_thread(
                _create_standby_image,
                "STREAMING WEBRTC PENDIENTE",
                "aiortc/av en espera de actualización compatible con HA 2026.10+",
            )

        if self.coordinator.camera_active:
            return await asyncio.to_thread(_create_standby_image, "CONECTANDO A PLACA FERMAX...")

        return _STANDBY_IMAGE

    async def handle_async_mjpeg_stream(
        self, request: Any
    ) -> Any:
        """Serve continuous MJPEG stream directly to Home Assistant dashboard."""
        from aiohttp import web

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "multipart/x-mixed-replace;boundary=frameboundary",
            },
        )
        await response.prepare(request)

        try:
            while True:
                stream = self.coordinator.stream_session
                frame = None

                if stream and stream.latest_frame:
                    frame = stream.latest_frame
                elif self.coordinator.last_photo:
                    frame = self.coordinator.last_photo
                elif not WEBRTC_AVAILABLE and self.coordinator.camera_active:
                    frame = await asyncio.to_thread(
                        _create_standby_image,
                        "STREAMING WEBRTC PENDIENTE",
                        "aiortc/av en espera de actualización compatible con HA 2026.10+",
                    )
                elif self.coordinator.camera_active:
                    frame = await asyncio.to_thread(_create_standby_image, "CONECTANDO A PLACA FERMAX...")
                else:
                    frame = _STANDBY_IMAGE

                if frame:
                    await response.write(
                        b"--frameboundary\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: "
                        + str(len(frame)).encode()
                        + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )

                if stream and stream.is_active:
                    await asyncio.sleep(0.04)  # ~25 FPS
                else:
                    await asyncio.sleep(1.0)
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass

        return response
