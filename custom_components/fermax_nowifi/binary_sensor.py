"""Binary sensor entities for Fermax NOWIFI."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    SIGNAL_CALL_ENDED,
    SIGNAL_DOORBELL_RING,
)
from .coordinator import FermaxNowifiCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fermax NOWIFI binary sensors."""
    coordinator: FermaxNowifiCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            FermaxDoorbellBinarySensor(coordinator),
            FermaxConnectionBinarySensor(coordinator),
        ]
    )


class FermaxBaseBinarySensor(CoordinatorEntity[FermaxNowifiCoordinator], BinarySensorEntity):
    """Base binary sensor for Fermax NOWIFI."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.house_id)},
            name=f"Fermax NOWIFI ({coordinator.house_tag})",
            manufacturer=MANUFACTURER,
            model=MODEL_NOWIFI,
            sw_version="1.0.0",
        )


class FermaxDoorbellBinarySensor(FermaxBaseBinarySensor):
    """Binary sensor reporting when someone is ringing the doorbell."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_doorbell"
        self._attr_name = "Timbre"
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY
        self._attr_icon = "mdi:doorbell-video"

    @property
    def is_on(self) -> bool:
        """Return True if doorbell is currently ringing."""
        return self.coordinator.is_ringing

    async def async_added_to_hass(self) -> None:
        """Subscribe to doorbell events."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DOORBELL_RING.format(self.coordinator.house_id),
                self.async_write_ha_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CALL_ENDED.format(self.coordinator.house_id),
                self.async_write_ha_state,
            )
        )


class FermaxConnectionBinarySensor(FermaxBaseBinarySensor):
    """Binary sensor indicating if FCM cloud push connection is active."""

    def __init__(self, coordinator: FermaxNowifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house_id}_cloud_connection"
        self._attr_name = "Conexión Nube"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        """Return True if FCM listener is running."""
        return (
            self.coordinator.notification_listener is not None
            and self.coordinator.notification_listener.is_started
        )
