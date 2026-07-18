"""Device tracker — one per client, real name + wire/wireless/signal/port."""
import logging

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    seen = set()

    def _add():
        new = []
        for c in (coordinator.data or {}).get("clients", []):
            mac = c.get("mac")
            if mac and mac not in seen:
                seen.add(mac)
                new.append(ReyeeTracker(coordinator, entry, mac))
        if new:
            async_add_entities(new)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class ReyeeTracker(CoordinatorEntity, ScannerEntity):
    def __init__(self, coordinator, entry, mac):
        super().__init__(coordinator)
        self._mac = mac
        self._last_ip = None
        self._attr_unique_id = f"{entry.entry_id}_tracker_{mac.replace(':', '')}"

    def _client(self):
        for c in (self.coordinator.data or {}).get("clients", []):
            if c.get("mac") == self._mac:
                if c.get("ip"):
                    self._last_ip = c["ip"]
                return c
        return None

    @property
    def name(self):
        c = self._client()
        # Real name resolved by the coordinator (devRemark > alias > hostname > MAC)
        return (c or {}).get("name") or self._mac.upper()

    @property
    def source_type(self):
        return SourceType.ROUTER

    @property
    def is_connected(self):
        return self._client() is not None

    @property
    def ip_address(self):
        c = self._client()
        return (c or {}).get("ip") or self._last_ip

    @property
    def mac_address(self):
        return self._mac

    @property
    def icon(self):
        c = self._client() or {}
        if c.get("connection") == "wireless":
            return "mdi:wifi"
        if c.get("connection") == "wired":
            return "mdi:ethernet"
        return "mdi:lan-connect"

    @property
    def extra_state_attributes(self):
        c = self._client() or {}
        attrs = {
            "ip_address": c.get("ip") or self._last_ip,
            "vlan": c.get("vlan"),
            "connection": c.get("connection"),
            "mac": self._mac,
        }
        if c.get("connection") == "wireless":
            attrs["ssid"] = c.get("ssid")
            attrs["band"] = c.get("band")
            attrs["signal_dbm"] = c.get("rssi")
        if c.get("switch_port"):
            attrs["switch_port"] = c.get("switch_port")
        if c.get("online_since"):
            attrs["online_since"] = c.get("online_since")
        return attrs
