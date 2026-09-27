"""Device tracker — one ScannerEntity per client.

IMPORTANT: Home Assistant makes ScannerEntity.device_info @final and always
returns None, so any DeviceInfo set on a tracker is silently ignored. HA builds
the client device itself, named `hostname or mac_address`. So the friendly name
must be exposed through `hostname`, and because HA never renames an existing
device, we push name changes into the device registry ourselves.
"""
import logging

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
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
    # The client device carries the name; the tracker entity inherits it.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, entry, mac):
        super().__init__(coordinator)
        self._mac = mac
        self._last_ip = None
        self._entry = entry
        self._last_name = None
        # NB: ScannerEntity.unique_id returns mac_address; this is not used.
        self._attr_unique_id = f"{entry.entry_id}_tracker_{mac.replace(':', '')}"

    def _friendly_name(self):
        """Resolved client name, or None when all we have is the MAC."""
        name = _resolve_name(self.coordinator, self._mac)
        if not name or name.upper() == self._mac.upper():
            return None
        return name

    @property
    def hostname(self):
        # HA names the client device `hostname or mac_address` — this is
        # the only name HA reads for a tracker's device.
        return self._friendly_name()

    @callback
    def _sync_device_name(self):
        """Push the resolved name into the device registry.

        HA sets the device name only when it creates the device, so without
        this a device that started as a MAC stays a MAC forever. Only touches
        devices owned solely by this entry, and never a user-set name.
        """
        name = self._friendly_name()
        if not name or name == self._last_name or not self.registry_entry:
            return
        device_id = self.registry_entry.device_id
        if not device_id:
            return
        reg = dr.async_get(self.hass)
        device = reg.async_get(device_id)
        if device is None:
            return
        self._last_name = name
        if (device.name_by_user is None
                and set(device.config_entries) == {self._entry.entry_id}
                and device.name != name):
            reg.async_update_device(device_id, name=name)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._sync_device_name()

    @callback
    def _handle_coordinator_update(self):
        self._sync_device_name()
        super()._handle_coordinator_update()

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
        if c.get("access_point"):
            attrs["access_point"] = c.get("access_point")
        if c.get("switch_port"):
            attrs["switch_port"] = c.get("switch_port")
        if c.get("online_since"):
            attrs["online_since"] = c.get("online_since")
        return attrs
