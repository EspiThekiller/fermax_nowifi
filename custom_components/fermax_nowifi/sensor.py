"""Sensor entities for Fermax NOWIFI."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION, MANUFACTURER, MODEL_NOWIFI
from .coordinator import FermaxNowifiCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fermax NOWIFI sensors."""
    coordinator: FermaxNowifiCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            FermaxPanelStateSensor(coordinator),
            FermaxLastRingSensor(coordinator),
            FermaxLastFaceSensor(coordinator),
        ]
    )


class FermaxBaseSensor(CoordinatorEntity[FermaxNowifiCoordinator], SensorEntity):
    """Base sensor for Fermax NOWIFI."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.house_id)},
            name=f"Fermax NOWIFI ({coordinator.house_tag})",
            manufacturer=MANUFACTURER,
            model=MODEL_NOWIFI,
            sw_version=INTEGRATION_VERSION,
        )


class FermaxPanelStateSensor(FermaxBaseSensor):
    """Sensor reporting the real-time operational state of the outdoor panel."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_panel_state"
        self._attr_name = "Estado de la Placa"
        self._attr_icon = "mdi:intercom"

    @property
    def native_value(self) -> str:
        """Return the current panel state."""
        return self.coordinator.panel_state


class FermaxLastRingSensor(FermaxBaseSensor):
    """Sensor recording the timestamp of the last doorbell ring."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_last_ring"
        self._attr_name = "Última Llamada"
        self._attr_icon = "mdi:history"

    @property
    def native_value(self) -> str | None:
        """Return the timestamp of the last ring event."""
        return self.coordinator.last_ring_time


class FermaxLastFaceSensor(FermaxBaseSensor):
    """Sensor reporting the last recognized face at the outdoor panel."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_last_face"
        self._attr_name = "Último Rostro Reconocido"
        self._attr_icon = "mdi:face-recognition"

    @property
    def native_value(self) -> str | None:
        """Return the name of the last recognized person or Desconocido."""
        return self.coordinator.last_recognized_face or "Ninguno"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return face recognition metadata."""
        return {
            "confidence": self.coordinator.last_face_confidence,
            "timestamp": self.coordinator.last_face_time,
            "door_opened": self.coordinator.last_face_door_opened,
        }
