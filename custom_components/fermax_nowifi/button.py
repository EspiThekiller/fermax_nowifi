"""Button entities for Fermax NOWIFI."""

from __future__ import annotations

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION, MANUFACTURER, MODEL_NOWIFI
from .coordinator import FermaxNowifiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fermax NOWIFI buttons."""
    coordinator: FermaxNowifiCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        FermaxOpenDoorButton(coordinator, number=1, key="main_door", name="Abrir Puerta Principal"),
        FermaxOpenDoorButton(coordinator, number=2, key="secondary_door", name="Abrir Puerta 2 / Cancela"),
        FermaxF1Button(coordinator),
    ]

    async_add_entities(entities)


class FermaxBaseButton(CoordinatorEntity[FermaxNowifiCoordinator], ButtonEntity):
    """Base button for Fermax NOWIFI."""

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


class FermaxOpenDoorButton(FermaxBaseButton):
    """Button to open outdoor door (in-call if camera active, or directOpenDoorNoWifi)."""

    def __init__(
        self,
        coordinator: FermaxNowifiCoordinator,
        number: int,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._number = number
        self._attr_unique_id = f"{coordinator.house_id}_{key}"
        self._attr_name = name
        self._attr_icon = "mdi:door-open"

    async def async_press(self) -> None:
        """Trigger door opening."""
        _LOGGER.info("Door button pressed: opening door relay #%d", self._number)
        await self.coordinator.open_door(number=self._number)


class FermaxF1Button(FermaxBaseButton):
    """Button to trigger F1 auxiliary courtesy function."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_f1"
        self._attr_name = "Luz de Cortesía (F1)"
        self._attr_icon = "mdi:lightbulb-outline"

    async def async_press(self) -> None:
        """Trigger F1 relay."""
        _LOGGER.info("F1 button pressed")
        await self.coordinator.press_f1()
