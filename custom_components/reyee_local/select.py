"""Select entity — choose the primary WAN uplink."""
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReyeePrimaryWanSelect(coordinator, entry)])


class ReyeePrimaryWanSelect(CoordinatorEntity, SelectEntity):
    """Switch which WAN line is primary, from HA."""

    _attr_name = "Reyee Primary WAN"
    _attr_icon = "mdi:swap-horizontal-bold"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_primary_wan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    @property
    def options(self):
        return [l.get("ifname") for l in
                (self.coordinator.data or {}).get("wan_lines", [])
                if l.get("ifname")]

    @property
    def current_option(self):
        for l in (self.coordinator.data or {}).get("wan_lines", []):
            if str(l.get("m")) == "1":
                return l.get("ifname")
        return None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "active_uplink": d.get("active_wan"),
            "mode":          (d.get("mllb") or {}).get("mode"),
            "policy":        (d.get("mllb") or {}).get("policy"),
        }

    async def async_select_option(self, option: str):
        _LOGGER.info("Reyee: switching primary WAN to %s", option)
        await self.coordinator.async_set_primary_wan(option)
