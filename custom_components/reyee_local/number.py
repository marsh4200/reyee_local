"""Number entities — global WiFi per-station rate limit (upload / download)."""
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.const import UnitOfDataRate
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _gw(entry):
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Ruijie",
        name=entry.title,
        configuration_url=f"http://{entry.data['host']}",
    )


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ReyeeRateLimit(coordinator, entry, "dl"),
        ReyeeRateLimit(coordinator, entry, "ul"),
    ])


class ReyeeRateLimit(CoordinatorEntity, NumberEntity):
    """WiFi per-station rate cap in kbps (0 = unlimited)."""
    _attr_native_min_value = 0
    _attr_native_max_value = 1000000
    _attr_native_step = 100
    _attr_native_unit_of_measurement = UnitOfDataRate.KILOBITS_PER_SECOND
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, direction):
        super().__init__(coordinator)
        self._dir = direction
        label = "Download" if direction == "dl" else "Upload"
        self._attr_name = f"Reyee Rate Limit {label}"
        self._attr_unique_id = f"{entry.entry_id}_ratelimit_{direction}"
        self._attr_icon = "mdi:speedometer-slow"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        rl = (self.coordinator.data or {}).get("rate_limit", {})
        try:
            return float(rl.get(self._dir, 0))
        except (ValueError, TypeError):
            return 0

    async def async_set_native_value(self, value):
        rl = (self.coordinator.data or {}).get("rate_limit", {"ul": "0", "dl": "0"})
        up = int(float(value)) if self._dir == "ul" else int(float(rl.get("ul", 0)))
        dl = int(float(value)) if self._dir == "dl" else int(float(rl.get("dl", 0)))
        await self.coordinator.async_set_rate_limit(up, dl)
