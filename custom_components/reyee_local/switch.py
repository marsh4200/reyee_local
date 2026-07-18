"""Switch — Forced Switch (strict primary/backup) toggle."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ReyeeForcedSwitch(coordinator, entry),
        ReyeeFlowControlSwitch(coordinator, entry),
    ])


class ReyeeForcedSwitch(CoordinatorEntity, SwitchEntity):
    """When on, all traffic uses the master WAN unless it drops."""

    _attr_name = "Reyee Forced Switch"
    _attr_icon = "mdi:call-split"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_forced_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("mllb", {}).get("backup_discon") == "1"

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_forced_switch(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_forced_switch(False)


class ReyeeFlowControlSwitch(CoordinatorEntity, SwitchEntity):
    """Master traffic-control (bandwidth management) on/off."""
    _attr_name = "Reyee Flow Control"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_flow_control_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("flowctrl", {}).get("tcSwitch") == "on"

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_flow_control(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_flow_control(False)
