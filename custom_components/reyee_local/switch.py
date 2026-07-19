"""Switch — Forced Switch (strict primary/backup) toggle."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
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

    seen_leds = set()

    def _add_leds():
        new = []
        for d in (coordinator.data or {}).get("led_devices", []):
            sn = d.get("sn")
            if sn and sn not in seen_leds:
                seen_leds.add(sn)
                new.append(ReyeeDeviceLedSwitch(coordinator, entry, sn))
        if new:
            async_add_entities(new)

    _add_leds()
    entry.async_on_unload(coordinator.async_add_listener(_add_leds))

    seen_ssids = set()

    def _add_ssids():
        new = []
        for ss in (coordinator.data or {}).get("ssids", []):
            wid = ss.get("wlan_id")
            if wid and wid not in seen_ssids:
                seen_ssids.add(wid)
                new.append(ReyeeSsidSwitch(coordinator, entry, wid))
        if new:
            async_add_entities(new)

    _add_ssids()
    entry.async_on_unload(coordinator.async_add_listener(_add_ssids))


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


class ReyeeSsidSwitch(CoordinatorEntity, SwitchEntity):
    """Enable/disable a single WiFi SSID via the AC controller."""
    _attr_icon = "mdi:wifi"

    def __init__(self, coordinator, entry, wlan_id):
        super().__init__(coordinator)
        self._wid = wlan_id
        self._attr_unique_id = f"{entry.entry_id}_ssid_{wlan_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    def _ssid(self):
        for s in (self.coordinator.data or {}).get("ssids", []):
            if s.get("wlan_id") == self._wid:
                return s
        return None

    @property
    def name(self):
        s = self._ssid()
        return f"Reyee WiFi {s.get('name') if s else self._wid}"

    @property
    def is_on(self):
        s = self._ssid()
        return bool(s and s.get("enabled"))

    @property
    def icon(self):
        return "mdi:wifi" if self.is_on else "mdi:wifi-off"

    @property
    def extra_state_attributes(self):
        s = self._ssid() or {}
        return {"vlan": s.get("vlan"), "guest": s.get("guest"),
                "hidden": s.get("hidden"), "wlan_id": self._wid}

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_ssid_enabled(self._wid, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_ssid_enabled(self._wid, False)


class ReyeeDeviceLedSwitch(CoordinatorEntity, SwitchEntity):
    """LED on/off for one Reyee device, targeted by serial (auto-detected)."""
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, serial):
        super().__init__(coordinator)
        self._sn = serial
        self._attr_unique_id = f"{entry.entry_id}_led_{serial}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Ruijie",
            name=entry.title,
            configuration_url=f"http://{entry.data['host']}",
        )

    def _dev(self):
        for d in (self.coordinator.data or {}).get("led_devices", []):
            if d.get("sn") == self._sn:
                return d
        return {}

    @property
    def name(self):
        d = self._dev()
        label = d.get("name") or f"Device {self._sn[-4:]}"
        return f"Reyee LED {label}"

    @property
    def is_on(self):
        return self._sn not in (self.coordinator.data or {}).get("led_off_serials", [])

    @property
    def icon(self):
        return "mdi:led-on" if self.is_on else "mdi:led-off"

    @property
    def extra_state_attributes(self):
        return {"serial": self._sn, "device": self._dev().get("name")}

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_device_led(self._sn, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_device_led(self._sn, False)
