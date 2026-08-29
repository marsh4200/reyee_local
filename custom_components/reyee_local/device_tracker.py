"""Device tracker — client presence entities living on the gateway device.

Reyee gateways report dozens of transient LAN/WiFi clients. Giving each one
its own Home Assistant device (as before, via `via_device`) floods the device
registry with entries for phones, laptops, etc. that come and go. Instead,
every tracker entity attaches directly to the single gateway device, exactly
like every other entity this integration creates — so only the router shows
up as a device, with per-client presence exposed as entities on it.
"""
import logging

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _resolve_name(coordinator, mac):
    for c in (coordinator.data or {}).get("clients", []):
        if c.get("mac") == mac:
            return c.get("name") or mac.upper()
    return mac.upper()


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
    # Entities carry their own name (the client's name/hostname) rather than
    # inheriting the gateway device's name, since many entities now share
    # that one device.
    _attr_has_entity_name = False

    def __init__(self, coordinator, entry, mac):
        super().__init__(coordinator)
        self._mac = mac
        self._last_ip = None
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_tracker_{mac.replace(':', '')}"
        # Attach to the gateway device itself — no separate per-client device.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def name(self):
        return _resolve_name(self.coordinator, self._mac)

    def _client(self):
        for c in (self.coordinator.data or {}).get("clients", []):
            if c.get("mac") == self._mac:
                if c.get("ip"):
                    self._last_ip = c["ip"]
                return c
        return None

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
        return "mdi:lan-disconnect" if not self.is_connected else "mdi:lan-connect"

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
