"""Sensors: devices, per-VLAN, physical ports, WAN throughput, topology, WAN."""
import logging

from homeassistant.components.sensor import (
    SensorEntity, SensorStateClass, SensorDeviceClass,
)
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


def _slug(s):
    return "".join(c if c.isalnum() else "_" for c in str(s)).strip("_").lower()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ReyeeTotalDevicesSensor(coordinator, entry),
        ReyeeGatewaySensor(coordinator, entry),
        ReyeeActiveWanSensor(coordinator, entry),
        ReyeePublicIpSensor(coordinator, entry),
        ReyeePortForwardSensor(coordinator, entry),
        ReyeeFlowControlSensor(coordinator, entry),
        ReyeeTopologySensor(coordinator, entry),
    ]
    seen_vlans, seen_wan, seen_ports = set(), set(), set()

    def _add_dynamic():
        new = []
        for v in (coordinator.data or {}).get("vlans", []):
            if v["name"] not in seen_vlans:
                seen_vlans.add(v["name"])
                new.append(ReyeeVlanSensor(coordinator, entry, v["name"]))
        for line in (coordinator.data or {}).get("wan_lines", []):
            ifn = line.get("ifname")
            if ifn and ifn not in seen_wan:
                seen_wan.add(ifn)
                new.append(ReyeeWanRoleSensor(coordinator, entry, ifn))
                new.append(ReyeeWanThroughputSensor(coordinator, entry, ifn, "down"))
                new.append(ReyeeWanThroughputSensor(coordinator, entry, ifn, "up"))
        for p in (coordinator.data or {}).get("ports", []):
            pid = p.get("portId")
            if pid and pid not in seen_ports:
                seen_ports.add(pid)
                new.append(ReyeePortSensor(coordinator, entry, pid))
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
        clients = d.get("clients", [])
        wired = sum(1 for c in clients if c.get("connection") == "wired")
        wireless = sum(1 for c in clients if c.get("connection") == "wireless")
        return {
            "wired": wired,
            "wireless": wireless,
            "by_vlan": d.get("vlan_counts", {}),
            "devices": sorted(
                [{"name": c["name"], "ip": c["ip"], "vlan": c["vlan"],
                  "connection": c["connection"]} for c in clients],
                key=lambda x: (x["vlan"] or "", x["name"] or ""),
            ),
        }


class ReyeeVlanSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:lan"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, vlan_name):
        super().__init__(coordinator)
        self._vname = vlan_name
        self._attr_name = f"Reyee {vlan_name} Devices"
        self._attr_unique_id = f"{entry.entry_id}_vlan_{_slug(vlan_name)}"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("vlan_counts", {}).get(self._vname, 0)

    @property
    def extra_state_attributes(self):
        clients = [c for c in (self.coordinator.data or {}).get("clients", [])
                   if c["vlan"] == self._vname]
        return {"devices": [{"name": c["name"], "ip": c["ip"],
                             "connection": c["connection"]} for c in clients]}


class ReyeePortSensor(CoordinatorEntity, SensorEntity):
    """A physical port on the gateway (from port_status)."""
    _attr_icon = "mdi:ethernet"

    def __init__(self, coordinator, entry, port_id):
        super().__init__(coordinator)
        self._pid = port_id
        self._attr_unique_id = f"{entry.entry_id}_port_{port_id}"
        self._attr_device_info = _gw(entry)

    def _port(self):
        for p in (self.coordinator.data or {}).get("ports", []):
            if p.get("portId") == self._pid:
                return p
        return {}

    @property
    def name(self):
        p = self._port()
        return f"Reyee Port {p.get('panel_name') or self._pid}"

    @property
    def native_value(self):
        p = self._port()
        if not p:
            return "unknown"
        return "up" if p.get("status") == "on" else "down"

    @property
    def icon(self):
        return "mdi:ethernet" if self._port().get("status") == "on" else "mdi:ethernet-off"

    @property
    def extra_state_attributes(self):
        p = self._port()
        return {
            "panel": p.get("panel_name"),
            "role": p.get("name"),
            "speed_mbps": int(p.get("speed", 0) or 0),
            "duplex": p.get("duplex") if p.get("duplex") != "NULL" else None,
            "ip": p.get("ipaddr"),
            "poe_enabled": p.get("poe_enable") == "1",
        }


class ReyeeWanRoleSensor(CoordinatorEntity, SensorEntity):
    """Whether a WAN uplink is the primary (master) or backup line."""
    _attr_icon = "mdi:wan"

    def __init__(self, coordinator, entry, ifname):
        super().__init__(coordinator)
        self._ifn = ifname
        self._attr_name = f"Reyee WAN {ifname} Role"
        self._attr_unique_id = f"{entry.entry_id}_wanrole_{ifname}"
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
        # m == "1" is the master/primary uplink; "0" is backup
        return "primary" if str(l.get("m")) == "1" else "backup"

    @property
    def icon(self):
        return "mdi:wan" if self.native_value == "primary" else "mdi:backup-restore"

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        l = self._line()
        return {
            "ifname": self._ifn,
            "role": self.native_value,
            "is_active": d.get("active_wan") == self._ifn,
            "weight": l.get("w"),
        }


class ReyeeWanThroughputSensor(CoordinatorEntity, SensorEntity):
    """Live WAN throughput per uplink (from flow interface_info), in Mbit/s."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, ifname, direction):
        super().__init__(coordinator)
        self._ifn = ifname
        self._dir = direction
        arrow = "Down" if direction == "down" else "Up"
        self._attr_name = f"Reyee WAN {ifname} {arrow}"
        self._attr_unique_id = f"{entry.entry_id}_wanflow_{ifname}_{direction}"
        self._attr_icon = "mdi:download" if direction == "down" else "mdi:upload"
        self._attr_device_info = _gw(entry)

    def _raw(self):
        f = (self.coordinator.data or {}).get("wan_flow", {}).get(self._ifn, {})
        try:
            return int(f.get(self._dir, 0))
        except (ValueError, TypeError):
            return None

    @property
    def native_value(self):
        raw = self._raw()
        if raw is None:
            return None
        # Router reports bytes/sec; convert to megabits/sec for display.
        return round(raw * 8 / 1_000_000, 2)

    @property
    def extra_state_attributes(self):
        return {"raw_bytes_per_sec": self._raw()}


class ReyeeActiveWanSensor(CoordinatorEntity, SensorEntity):
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
        d = self.coordinator.data or {}
        info = d.get("ipinfo", {})
        active = d.get("active_wan")
        detail = info.get(active, {}) if isinstance(info, dict) else {}
        m = d.get("mllb", {})
        return {
            "mode": m.get("mode"),
            "policy": m.get("policy"),
            "public_ip": detail.get("ip"),
            "gateway": detail.get("gateway"),
            "dns": detail.get("dnsList"),
            "protocol": detail.get("proto"),
            "uplinks": [l.get("ifname") for l in m.get("master_list", [])],
        }


class ReyeePublicIpSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Reyee Public IP"
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_public_ip"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        info = d.get("ipinfo", {})
        active = d.get("active_wan")
        if isinstance(info, dict) and active in info:
            return info[active].get("ip") or d.get("wan_ip") or "unknown"
        return d.get("wan_ip") or "unknown"

    @property
    def extra_state_attributes(self):
        info = (self.coordinator.data or {}).get("ipinfo", {})
        return {"wan_ips": {k: v.get("ip") for k, v in info.items()}
                if isinstance(info, dict) else {}}


class ReyeeTopologySensor(CoordinatorEntity, SensorEntity):
    """Downstream Reyee devices (switches + APs) from local_topology."""
    _attr_name = "Reyee Network Devices"
    _attr_icon = "mdi:lan"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_topology"
        self._attr_device_info = _gw(entry)

    @property
    def native_value(self):
        # count excludes the gateway itself (depth 0)
        return sum(1 for n in (self.coordinator.data or {}).get("topology", [])
                   if n.get("depth", 0) > 0)

    @property
    def extra_state_attributes(self):
        topo = (self.coordinator.data or {}).get("topology", [])
        aps = [n for n in topo if n.get("type") in ("EAP", "AP")]
        switches = [n for n in topo if n.get("type") in ("MSW", "SW", "SWITCH")]
        offline = [n["name"] for n in topo if not n.get("online") and n.get("depth", 0) > 0]
        return {
            "access_points": len(aps),
            "switches": len(switches),
            "offline": offline,
            "devices": [{"name": n["name"], "type": n["type"], "model": n["model"],
                         "ip": n["ip"], "online": n["online"]}
                        for n in topo if n.get("depth", 0) > 0],
        }


class ReyeeFlowControlSensor(CoordinatorEntity, SensorEntity):
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
            "p2p_control": fc.get("p2pSwtich"),
            "wan_bandwidth": [
                {"interface": l.get("ifname"), "up_mbps": l.get("uploadBand"),
                 "down_mbps": l.get("downloadBand")}
                for l in fc.get("list", [])
            ],
        }


class ReyeePortForwardSensor(CoordinatorEntity, SensorEntity):
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
            {"name": r.get("ruleName", "").strip(), "protocol": r.get("proto"),
             "wan_port": r.get("srcPort"), "lan_ip": r.get("destIp"),
             "lan_port": r.get("destPort")} for r in rules]}


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
            "model": s.get("model") or s.get("product_class"),
            "firmware": s.get("software_version"),
            "hardware_version": s.get("hardware_version"),
            "mac": s.get("sys_mac"),
            "serial_number": s.get("serial_num"),
            "public_ip": s.get("wan_ip"),
            "forward_mode": s.get("forwardMode"),
            "vlan_count": len(d.get("vlans", [])),
        }
