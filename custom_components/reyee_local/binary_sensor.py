"""WAN / internet connectivity binary sensor."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity, BinarySensorDeviceClass,
)
from homeassistant.helpers.device_registry import DeviceInfo, CONNECTION_NETWORK_MAC
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


_INFRA_TYPES = {
    "MSW": "Switch", "SW": "Switch", "SWITCH": "Switch",
    "EAP": "Access Point", "AP": "Access Point",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReyeeInternetOnline(coordinator, entry)])

    seen = set()

    def _add_infra():
        new = []
        for n in (coordinator.data or {}).get("topology", []):
            if n.get("depth", 0) == 0:
                continue  # skip the gateway itself
            sn = n.get("sn") or n.get("mac") or n.get("name")
            if sn and sn not in seen and n.get("type") in _INFRA_TYPES:
                seen.add(sn)
                new.append(ReyeeInfraDevice(coordinator, entry, sn))
        if new:
            async_add_entities(new)

    _add_infra()
    entry.async_on_unload(coordinator.async_add_listener(_add_infra))


class ReyeeInternetOnline(CoordinatorEntity, BinarySensorEntity):
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
        # networkConnect is the router's own internet-reachability check
        return bool((self.coordinator.data or {}).get("internet_up"))

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "active_uplink": d.get("active_wan"),
            "public_ip": d.get("wan_ip"),
        }


class ReyeeInfraDevice(CoordinatorEntity, BinarySensorEntity):
    """A downstream Reyee switch or AP as its own device, connected via the gateway."""
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry, sn):
        super().__init__(coordinator)
        self._sn = sn
        self._attr_unique_id = f"{entry.entry_id}_infra_{sn}"
        node = self._node() or {}
        kind = _INFRA_TYPES.get(node.get("type"), "Device")
        name = node.get("name") or sn
        info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_infra_{sn}")},
            "name": name,
            "model": node.get("model"),
            "manufacturer": "Ruijie",
            "via_device": (DOMAIN, entry.entry_id),
        }
        if node.get("mac"):
            info["connections"] = {(CONNECTION_NETWORK_MAC, node["mac"])}
        if node.get("ip"):
            info["configuration_url"] = f"http://{node['ip']}"
        self._attr_device_info = DeviceInfo(**info)
        self._kind = kind

    def _node(self):
        for n in (self.coordinator.data or {}).get("topology", []):
            if (n.get("sn") or n.get("mac") or n.get("name")) == self._sn:
                return n
        return None

    @property
    def is_on(self):
        n = self._node()
        return bool(n and n.get("online"))

    @property
    def icon(self):
        return "mdi:switch" if self._kind == "Switch" else "mdi:access-point"

    @property
    def extra_state_attributes(self):
        n = self._node() or {}
        return {
            "type": self._kind,
            "model": n.get("model"),
            "ip": n.get("ip"),
            "mac": n.get("mac"),
            "serial": n.get("sn"),
            "uplink_port": n.get("uplink_port"),
        }
