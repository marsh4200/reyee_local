"""WAN connectivity binary sensor."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity, BinarySensorDeviceClass,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReyeeWanOnline(coordinator, entry)])


class ReyeeWanOnline(CoordinatorEntity, BinarySensorEntity):
    _attr_name = "Reyee WAN Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_wan_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    @property
    def is_on(self):
        d = self.coordinator.data or {}
        # An active uplink reported by mllb means the gateway has a live WAN.
        return bool(d.get("active_wan"))

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        m = d.get("mllb", {})
        return {
            "active_uplink": d.get("active_wan"),
            "mode":          m.get("mode"),
            "policy":        m.get("policy"),
        }
