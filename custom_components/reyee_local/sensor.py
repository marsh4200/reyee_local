"""Sensors: devices, per-VLAN (named), WAN uplinks, gateway info."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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


def _slug(s):
    return "".join(c if c.isalnum() else "_" for c in str(s)).strip("_").lower()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        ReyeeTotalDevicesSensor(coordinator, entry),
        ReyeeGatewaySensor(coordinator, entry),
        ReyeeActiveWanSensor(coordinator, entry),
        ReyeeVpnSensor(coordinator, entry),
        ReyeePublicIpSensor(coordinator, entry),
        ReyeePortForwardSensor(coordinator, entry),
        ReyeeFlowControlSensor(coordinator, entry),
    ]

    seen_vlans, seen_wan = set(), set()

    def _add_dynamic():
        new = []
        for v in (coordinator.data or {}).get("vlans", []):
            key = v["name"]
            if key not in seen_vlans:
                seen_vlans.add(key)
                new.append(ReyeeVlanSensor(coordinator, entry, key))
        for line in (coordinator.data or {}).get("wan_lines", []):
            ifn = line.get("ifname")
            if ifn and ifn not in seen_wan:
                seen_wan.add(ifn)
                new.append(ReyeeWanLineSensor(coordinator, entry, ifn))
        if new:
            async_add_entities(new)

    _add_dynamic()
    entry.async_on_unload(coordinator.async_add_listener(_add_dynamic))
    async_add_entities(entities)


class ReyeeTotalDevicesSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Reyee Connected Devices"
    _attr_icon = "mdi:devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connected_devices"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("clients", []))

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "by_vlan": d.get("vlan_counts", {}),
            "devices": sorted(
                [{"mac": c["mac"], "ip": c["ip"], "vlan": c["vlan"]}
                 for c in d.get("clients", [])],
                key=lambda x: (x["vlan"] or "", x["ip"] or ""),
            ),
        }


class ReyeeVlanSensor(CoordinatorEntity, SensorEntity):
    """Device count on a named VLAN (from network config)."""
    _attr_icon = "mdi:lan"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, vlan_name):
        super().__init__(coordinator)
        self._vname = vlan_name
        self._attr_name = f"Reyee {vlan_name} Devices"
        self._attr_unique_id = f"{entry.entry_id}_vlan_{_slug(vlan_name)}"
        self._attr_device_info = _gw(entry)

    def _vlan(self):
        for v in (self.coordinator.data or {}).get("vlans", []):
            if v["name"] == self._vname:
                return v
        return {}

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("vlan_counts", {}).get(self._vname, 0)

    @property
    def extra_state_attributes(self):
        v = self._vlan()
        clients = [c for c in (self.coordinator.data or {}).get("clients", [])
                   if c["vlan"] == self._vname]
        return {
            "vlan_id":     v.get("vlan_id"),
            "subnet":      v.get("cidr"),
            "gateway_ip":  v.get("gateway"),
            "dhcp_start":  v.get("dhcp_from"),
            "lease_mins":  v.get("lease_min"),
            "max_hosts":   v.get("max_hosts"),
            "devices":     [{"mac": c["mac"], "ip": c["ip"]} for c in clients],
        }


class ReyeeWanLineSensor(CoordinatorEntity, SensorEntity):
    """A WAN uplink — primary or backup."""
    _attr_icon = "mdi:wan"

    def __init__(self, coordinator, entry, ifname):
        super().__init__(coordinator)
        self._ifn = ifname
        self._attr_name = f"Reyee WAN {ifname}"
        self._attr_unique_id = f"{entry.entry_id}_wanline_{ifname}"
        self._attr_device_info = _gw(entry)

    def _line(self):
        for l in (self.coordinator.data or {}).get("wan_lines", []):
            if l.get("ifname") == self._ifn:
                return l
        return {}

    @property
    def native_value(self):
        l = self._line()
        if not l:
            return "unknown"
        return "primary" if str(l.get("m")) == "1" else "backup"

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        l = self._line()
        return {
            "ifname":    self._ifn,
            "is_active": d.get("active_wan") == self._ifn,
            "weight":    l.get("w"),
            "policy":    (d.get("mllb") or {}).get("policy"),
        }


class ReyeeActiveWanSensor(CoordinatorEntity, SensorEntity):
    """Which WAN uplink is currently carrying traffic."""
    _attr_name = "Reyee Active WAN"
    _attr_icon = "mdi:transit-connection-variant"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active_wan"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("active_wan") or "unknown"

    @property
    def extra_state_attributes(self):
        m = (self.coordinator.data or {}).get("mllb", {})
        return {
            "mode":          m.get("mode"),
            "policy":        m.get("policy"),
            "forced_switch": m.get("backup_discon") == "1",
            "enabled":       m.get("enable") == "1",
            "uplinks":       [l.get("ifname") for l in m.get("master_list", [])],
        }


class ReyeeGatewaySensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Reyee Gateway"
    _attr_icon = "mdi:router-network"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_gateway"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        s = (self.coordinator.data or {}).get("sysinfo", {})
        return s.get("model") or s.get("product_class") or "EG Series"

    @property
    def extra_state_attributes(self):
        s = (self.coordinator.data or {}).get("sysinfo", {})
        d = self.coordinator.data or {}
        return {
            "model":            s.get("model") or s.get("product_class"),
            "firmware":         s.get("software_version"),
            "hardware_version": s.get("hardware_version"),
            "mac":              s.get("sys_mac"),
            "forward_mode":     s.get("forwardMode"),
            "os":               s.get("ostype"),
            "manufacturer":     s.get("manufacturer"),
            "max_aps":          s.get("max_ap_num"),
            "max_clients":      s.get("max_sta_num"),
            "wifi_built_in":    s.get("support_wifi") == "1",
            "ac_enabled":       s.get("acEnable") == "true",
            "vlan_count":       len(d.get("vlans", [])),
            "public_ip":        s.get("wan_ip"),
            "serial_number":    s.get("serial_num"),
        }


class ReyeeVpnSensor(CoordinatorEntity, SensorEntity):
    """WireGuard VPN client count (0 if VPN not configured)."""
    _attr_name = "Reyee VPN Clients"
    _attr_icon = "mdi:vpn"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_vpn_clients"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("wg_clients", []))

    @property
    def extra_state_attributes(self):
        clients = (self.coordinator.data or {}).get("wg_clients", [])
        return {"clients": [
            {"name": c.get("name") or c.get("desc"),
             "ip":   c.get("interface_ip") or c.get("ip"),
             "uuid": c.get("uuid")}
            for c in clients if isinstance(c, dict)
        ]}


class ReyeePublicIpSensor(CoordinatorEntity, SensorEntity):
    """Public WAN IP address."""
    _attr_name = "Reyee Public IP"
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_public_ip"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("wan_ip") or "unknown"


class ReyeePortForwardSensor(CoordinatorEntity, SensorEntity):
    """Number of active port-forwarding rules, with the rules in attributes."""
    _attr_name = "Reyee Port Forwards"
    _attr_icon = "mdi:arrow-decision"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_port_forwards"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("port_forwards", []))

    @property
    def extra_state_attributes(self):
        rules = (self.coordinator.data or {}).get("port_forwards", [])
        return {"rules": [
            {"name":     r.get("ruleName", "").strip(),
             "protocol": r.get("proto"),
             "wan_port": r.get("srcPort"),
             "lan_ip":   r.get("destIp"),
             "lan_port": r.get("destPort"),
             "source":   r.get("src")}
            for r in rules
        ]}


class ReyeeFlowControlSensor(CoordinatorEntity, SensorEntity):
    """Traffic/bandwidth control status."""
    _attr_name = "Reyee Flow Control"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_flow_control"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        fc = (self.coordinator.data or {}).get("flowctrl", {})
        return "on" if fc.get("tcSwitch") == "on" else "off"

    @property
    def extra_state_attributes(self):
        fc = (self.coordinator.data or {}).get("flowctrl", {})
        return {
            "traffic_control": fc.get("tcSwitch"),
            "p2p_control":     fc.get("p2pSwtich"),
            "wan_bandwidth":   [
                {"interface": l.get("ifname"),
                 "up_mbps":   l.get("uploadBand"),
                 "down_mbps": l.get("downloadBand")}
                for l in fc.get("list", [])
            ],
        }
