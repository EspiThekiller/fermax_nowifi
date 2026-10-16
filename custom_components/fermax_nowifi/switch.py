"""Switch entities for Fermax NOWIFI."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL_NOWIFI,
    SIGNAL_CAMERA_OFF,
    SIGNAL_CAMERA_ON,
)
from .coordinator import FermaxNowifiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fermax NOWIFI switches."""
    coordinator: FermaxNowifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FermaxCameraSwitch(coordinator)])


class FermaxCameraSwitch(CoordinatorEntity[FermaxNowifiCoordinator], SwitchEntity):
    """Switch to toggle the outdoor camera preview with an automatic 65s timer."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_camera_switch"
        self._attr_name = "Cámara Exterior"
        self._attr_icon = "mdi:cctv"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.house_id)},
            name=f"Fermax NOWIFI ({coordinator.house_tag})",
            manufacturer=MANUFACTURER,
            model=MODEL_NOWIFI,
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True if camera is currently previewing or streaming."""
        return self.coordinator.camera_active or self.coordinator.is_streaming

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on outdoor camera and start the 65-second auto-off timer."""
        _LOGGER.info(
            "Camera switch turned on: starting auto-on with %ds auto-off timeout",
            self.coordinator.stream_duration,
        )
        await self.coordinator.start_camera_preview()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off outdoor camera immediately."""
        _LOGGER.info("Camera switch turned off manually: disconnecting stream")
        await self.coordinator.stop_camera_preview()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to camera state signals."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CAMERA_ON.format(self.coordinator.house_id),
                self.async_write_ha_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CAMERA_OFF.format(self.coordinator.house_id),
                self.async_write_ha_state,
            )
        )
