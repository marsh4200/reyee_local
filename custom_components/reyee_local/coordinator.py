"""Reyee coordinator — confirmed data sources only (EG105G-V3 / ReyeeOS 2.x).

Confirmed working on this firmware:
  devSta.get   sysinfo          → model, sw version, sys_mac, forwardMode
  devSta.get   arp              → {"arpList":[{hardware,intf,address}]}
  devSta.get   mllb  getype=0   → live WAN load-balance + active intf
  devConfig.get network         → LAN/VLAN definitions (ipaddr/netmask/vlanid/desc)
  devConfig.get mllb            → WAN uplink config (master_list)

Confirmed NOT available (do not re-probe):
  port / dhcp / lan / wan / vlan / interface / flow / topo / son  → no data
"""
import ipaddress
import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_SCAN_INTERVAL
from .api import (ReyeeAuthError, ReyeeConnError, build_master_swap_payload,
                  build_portmap_add, build_portmap_remove, build_flowctrl_toggle)

_LOGGER = logging.getLogger(__name__)


def _is_error(r):
    """Reyee signals failure via rcode/rmsg or an empty data string."""
    if r is None:
        return True
    if isinstance(r, str):
        return r.strip() == ""
    if isinstance(r, dict):
        if r.get("rcode") and str(r.get("rcode")) != "00000000":
            return True
        if r.get("rmsg") or r.get("message"):
            return True
        d = r.get("data")
        if isinstance(d, str) and d.strip() == "":
            return True
        if set(r.keys()) <= {"code", "id", "error", "data"} and not d:
            return True
    return False


class ReyeeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, api):
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(hass, logger=_LOGGER, name=DOMAIN,
                         update_interval=timedelta(seconds=interval))
        self.api = api
        self.entry = entry

    async def _get(self, module, data=None):
        try:
            r = await self.api.get_state(module, data)
            return None if _is_error(r) else r
        except Exception:  # noqa: BLE001
            return None

    async def _cfg(self, module, data=None):
        try:
            r = await self.api.get_config(module, data)
            return None if _is_error(r) else r
        except Exception:  # noqa: BLE001
            return None

    # ── VLAN / subnet mapping ────────────────────────────────────────────
    @staticmethod
    def _parse_networks(net_cfg):
        """network config → list of VLAN dicts with a usable ip_network object."""
        vlans = []
        if not isinstance(net_cfg, dict):
            return vlans
        payload = net_cfg.get("data") if isinstance(net_cfg.get("data"), dict) else net_cfg
        for lan in (payload.get("lan") or []):
            if not isinstance(lan, dict):
                continue
            ip = lan.get("ipaddr")
            mask = lan.get("netmask") or "255.255.255.0"
            if not ip:
                continue
            try:
                net = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
            except ValueError:
                continue
            vlans.append({
                "vlan_id":   lan.get("vlanid") or lan.get("ovlanid"),
                "name":      (lan.get("desc") or "").strip() or f"VLAN {lan.get('vlanid')}",
                "gateway":   ip,
                "netmask":   mask,
                "cidr":      str(net),
                "network":   net,
                "mac":       lan.get("macaddr"),
                "lease_min": lan.get("leasetime"),
                "max_hosts": lan.get("limit"),
                "dhcp_from": lan.get("ipstart"),
                "proto":     lan.get("proto"),
            })
        return vlans

    @staticmethod
    def _match_vlan(ip_str, vlans):
        """Map a client IP to its VLAN by subnet containment."""
        if not ip_str:
            return None
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return None
        for v in vlans:
            if addr in v["network"]:
                return v
        return None

    # ── Write operations ─────────────────────────────────────────────────
    async def async_set_primary_wan(self, ifname: str):
        """Make `ifname` the primary (master) WAN uplink."""
        cfg = await self._cfg("mllb")
        if not cfg:
            raise ReyeeConnError("Could not read current WAN config")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        payload = build_master_swap_payload(data, ifname)
        await self.api.set_config("mllb", payload)
        _LOGGER.info("Reyee: primary WAN set to %s", ifname)
        await self.async_request_refresh()

    async def async_set_forced_switch(self, enabled: bool):
        """Toggle 'Forced Switch' (all traffic on master unless it drops)."""
        cfg = await self._cfg("mllb")
        if not cfg:
            raise ReyeeConnError("Could not read current WAN config")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        stamps = ("version", "configTime", "currentTime", "configId")
        payload = {k: v for k, v in data.items() if k not in stamps}
        payload["backup_discon"] = "1" if enabled else "0"
        await self.api.set_config("mllb", payload)
        _LOGGER.info("Reyee: forced switch = %s", enabled)
        await self.async_request_refresh()

    async def async_add_port_forward(self, rule: dict):
        cfg = await self._cfg("port_mapping")
        if not cfg:
            raise ReyeeConnError("Could not read current port_mapping")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        payload = build_portmap_add(data, rule)
        await self.api.set_config("port_mapping", payload)
        _LOGGER.info("Reyee: added port forward %s", rule.get("ruleName"))
        await self.async_request_refresh()

    async def async_remove_port_forward(self, rule_name: str):
        cfg = await self._cfg("port_mapping")
        if not cfg:
            raise ReyeeConnError("Could not read current port_mapping")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        payload = build_portmap_remove(data, rule_name)
        await self.api.set_config("port_mapping", payload)
        _LOGGER.info("Reyee: removed port forward %s", rule_name)
        await self.async_request_refresh()

    async def async_set_flow_control(self, enabled: bool):
        cfg = await self._cfg("flowctrl")
        if not cfg:
            raise ReyeeConnError("Could not read current flowctrl")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        payload = build_flowctrl_toggle(data, enabled)
        await self.api.set_config("flowctrl", payload)
        _LOGGER.info("Reyee: flow control = %s", enabled)
        await self.async_request_refresh()

    async def _async_update_data(self):
        # ── ARP: the client list ──────────────────────────────────────────
        try:
            raw_arp = await self.api.get_state("arp")
        except ReyeeAuthError as err:
            raise UpdateFailed(f"Auth failed: {err}") from err
        except ReyeeConnError as err:
            raise UpdateFailed(f"Cannot reach router: {err}") from err

        arp = raw_arp.get("arpList", []) if isinstance(raw_arp, dict) else []

        # ── VLAN / network topology ───────────────────────────────────────
        net_cfg = await self._cfg("network")
        vlans = self._parse_networks(net_cfg)

        # ── WAN (live state preferred, config as fallback) ────────────────
        mllb_live = await self._get("mllb", {"getype": "0"})
        mllb_cfg = await self._cfg("mllb")
        mllb = mllb_live or (mllb_cfg.get("data", mllb_cfg)
                             if isinstance(mllb_cfg, dict) else {}) or {}
        wan_lines = mllb.get("master_list", []) if isinstance(mllb, dict) else []
        active_wan = mllb.get("intf") if isinstance(mllb, dict) else None

        # ── sysinfo ───────────────────────────────────────────────────────
        sysinfo = await self._get("sysinfo") or {}

        # ── WireGuard VPN (read-only; module confirmed to exist on EG) ──────
        wg = await self._get("wireguard", {"getype": "0"})
        wg_clients = []
        if isinstance(wg, dict):
            wg_clients = wg.get("clientlist") or wg.get("clientList") or []

        # ── Port forwarding (confirmed real: module "port_mapping") ─────────
        pm = await self._cfg("port_mapping")
        pm_data = pm.get("data", pm) if isinstance(pm, dict) else {}
        port_forwards = pm_data.get("portMapping", []) if isinstance(pm_data, dict) else []

        # ── Flow / bandwidth control (confirmed real: module "flowctrl") ────
        fc = await self._cfg("flowctrl")
        flowctrl = fc.get("data", fc) if isinstance(fc, dict) else {}

        # ── Public WAN IP (from sysinfo) ───────────────────────────────────
        wan_ip = sysinfo.get("wan_ip")

        # ── Enrich clients with VLAN identity ─────────────────────────────
        clients = []
        vlan_counts = {}
        for e in arp:
            ip = e.get("address")
            mac = (e.get("hardware") or "").lower()
            v = self._match_vlan(ip, vlans)
            vname = v["name"] if v else (e.get("intf") or "Unknown")
            clients.append({
                "mac":     mac,
                "ip":      ip,
                "intf":    e.get("intf"),
                "vlan":    vname,
                "vlan_id": v["vlan_id"] if v else None,
            })
            vlan_counts[vname] = vlan_counts.get(vname, 0) + 1

        return {
            "clients":     clients,
            "vlans":       vlans,
            "vlan_counts": vlan_counts,
            "wan_lines":   wan_lines,
            "active_wan":  active_wan,
            "mllb":        mllb,
            "sysinfo":     sysinfo,
            "wg_clients":  wg_clients,
            "port_forwards": port_forwards,
            "flowctrl":    flowctrl,
            "wan_ip":      wan_ip,
        }
