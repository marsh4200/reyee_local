"""Reyee coordinator — full data model from confirmed eWeb modules (EG105G-V3).

Confirmed sources (from live eWeb capture):
  devSta.get   user_list  data={devType:all,dataType:timely}  → clients (wire+wireless)
  devConfig.get devRemark                                     → mac→custom name
  devSta.get   port_status                                    → 5 physical ports
  devSta.get   flow  data={func:interface_info}               → live WAN throughput
  devSta.get   flow  data={func:user_info}                    → per-IP live rate
  devSta.get   ipinfo                                         → per-WAN ip/gw/dns
  devSta.get   networkConnect                                 → internet up/down
  devSta.get   local_topology                                 → AP/switch tree
  devSta.get   arp                                            → fallback client coverage
  devConfig.get network / mllb                                → VLANs / WAN uplinks
"""
import ipaddress
import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_SCAN_INTERVAL
from .api import (ReyeeAuthError, ReyeeConnError, build_master_swap_payload,
                  build_portmap_add, build_portmap_remove, build_flowctrl_toggle,
                  build_ssid_toggle)

_LOGGER = logging.getLogger(__name__)

_JUNK_NAMES = {"", "*", "wlan0", "unknown", "null"}


def _norm_mac(m):
    if not m:
        return ""
    m = m.lower().replace(".", "").replace(":", "").replace("-", "")
    if len(m) == 12:
        return ":".join(m[i:i + 2] for i in range(0, 12, 2))
    return m.lower()


def _clean_name(n):
    if n and n.strip().lower() not in _JUNK_NAMES:
        return n.strip()
    return None


def _is_error(r):
    if r is None:
        return True
    if isinstance(r, str):
        return r.strip() == ""
    if isinstance(r, dict):
        if "_error" in r:
            return True
        if r.get("rcode") and str(r.get("rcode")) != "00000000":
            return True
        if r.get("rmsg"):
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
        """Proven path (devSta.get, unwrapped) for classic modules."""
        try:
            r = await self.api.get_state(module, data)
            return None if _is_error(r) else r
        except Exception:  # noqa: BLE001
            return None

    async def _cfg(self, module, data=None):
        """Proven path (devConfig.get, unwrapped) for classic modules."""
        try:
            r = await self.api.get_config(module, data)
            return None if _is_error(r) else r
        except Exception:  # noqa: BLE001
            return None

    async def _ac(self, module, data=None):
        """acConfig.get path for the wireless controller modules."""
        try:
            r = await self.api.raw_cmd("acConfig.get", module, data=data)
            if _is_error(r):
                return None
            if isinstance(r, dict) and isinstance(r.get("data"), (dict, list)):
                return r["data"]
            return r
        except Exception:  # noqa: BLE001
            return None

    async def _getx(self, module, data=None, no_parse=True):
        """eWeb path (raw_cmd with noParse) for advanced modules; unwrap .data."""
        try:
            r = await self.api.raw_cmd("devSta.get", module, data=data, no_parse=no_parse)
            if _is_error(r):
                return None
            # raw_cmd returns the full body; unwrap a .data wrapper if present
            if isinstance(r, dict) and isinstance(r.get("data"), (dict, list)):
                return r["data"]
            return r
        except Exception:  # noqa: BLE001
            return None

    async def _cfgx(self, module, data=None, no_parse=False):
        try:
            r = await self.api.raw_cmd("devConfig.get", module, data=data, no_parse=no_parse)
            if _is_error(r):
                return None
            if isinstance(r, dict) and isinstance(r.get("data"), (dict, list)):
                return r["data"]
            return r
        except Exception:  # noqa: BLE001
            return None

    # ── VLAN parsing (unchanged, confirmed) ──────────────────────────────
    @staticmethod
    def _parse_networks(net_cfg):
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
                "vlan_id": lan.get("vlanid") or lan.get("ovlanid"),
                "name": (lan.get("desc") or "").strip() or f"VLAN {lan.get('vlanid')}",
                "gateway": ip, "netmask": mask, "cidr": str(net), "network": net,
                "dhcp_from": lan.get("ipstart"), "lease_min": lan.get("leasetime"),
                "max_hosts": lan.get("limit"),
            })
        return vlans

    @staticmethod
    def _match_vlan(ip_str, vlans):
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

    @staticmethod
    def _flatten_topology(node, out, depth=0):
        if not isinstance(node, dict):
            return
        out.append({
            "name": node.get("name"),
            "type": node.get("deviceType"),
            "model": node.get("productClass"),
            "ip": node.get("manageIp"),
            "mac": node.get("mac"),
            "sn": node.get("deviceSn"),
            "online": node.get("onlineStatus") == "ON",
            "uplink_port": node.get("uplinkPort"),
            "depth": depth,
        })
        for child in node.get("children", []) or []:
            ReyeeCoordinator._flatten_topology(child, out, depth + 1)

    @staticmethod
    def _parse_pppoe(entries):
        if not entries:
            return {}
        ordered = sorted(entries, key=lambda e: int(e.get("order", 0) or 0))
        last = ordered[-1]
        code = str(last.get("code"))
        if code == "5":
            status = "connected"
        elif code in ("11", "9"):
            status = "disconnected"
        else:
            status = "connecting"
        disc = next((e.get("time") for e in reversed(ordered)
                     if str(e.get("code")) in ("11", "9")), None)
        conn = next((e.get("time") for e in reversed(ordered)
                     if str(e.get("code")) == "5"), None)
        drops = sum(1 for e in ordered if str(e.get("code")) == "11")
        recent = [f'{e.get("time")} \u2014 {e.get("msg")}' for e in ordered[-6:]]
        return {"status": status, "last_disconnect": disc,
                "last_connect": conn, "drop_count": drops, "recent": recent}

    async def _async_update_data(self):
        try:
            raw_arp = await self.api.get_state("arp")
        except ReyeeAuthError as err:
            raise UpdateFailed(f"Auth failed: {err}") from err
        except ReyeeConnError as err:
            raise UpdateFailed(f"Cannot reach router: {err}") from err
        arp = raw_arp.get("arpList", []) if isinstance(raw_arp, dict) else []

        # ── Real client list, custom names, live per-IP rate ──────────────
        ul = await self._getx("user_list",
                             {"devType": "all", "dataType": "timely"})
        user_list = ul.get("list", []) if isinstance(ul, dict) else []

        remark_cfg = await self._cfgx("devRemark")
        remark = {}
        if isinstance(remark_cfg, dict):
            for e in remark_cfg.get("list", []):
                nm = _clean_name(e.get("name"))
                if nm:
                    remark[_norm_mac(e.get("mac"))] = nm

        flow_user = await self._getx("flow", {"func": "user_info"})
        rate_by_ip = {}
        if isinstance(flow_user, dict):
            for e in flow_user.get("list", []):
                if e.get("ip"):
                    rate_by_ip[e["ip"]] = {
                        "up": int(e.get("up", 0) or 0),
                        "down": int(e.get("down", 0) or 0),
                        "conns": int(e.get("flowNum", 0) or 0),
                    }

        # VLANs
        net_cfg = await self._cfg("network")
        vlans = self._parse_networks(net_cfg)

        # ── Merge: ARP (coverage) + user_list (rich) + remark (names) ─────
        ul_by_mac = {_norm_mac(u.get("mac")): u for u in user_list if u.get("mac")}
        clients = []
        vlan_counts = {}
        seen = set()

        def _build(mac, ip, intf, u):
            mac = _norm_mac(mac)
            v = self._match_vlan(ip, vlans)
            vname = v["name"] if v else (intf or "Unknown")
            u = u or {}
            name = (remark.get(mac)
                    or _clean_name(u.get("deviceAliasName"))
                    or _clean_name(u.get("hostName"))
                    or mac.upper())
            ctype = u.get("connectType")
            rate = rate_by_ip.get(ip, {})
            return {
                "mac": mac, "ip": ip, "name": name,
                "vlan": vname, "vlan_id": v["vlan_id"] if v else None,
                "connection": ("wireless" if ctype == "wireless"
                               else "wired" if ctype == "wire" else None),
                "ssid": _clean_name(u.get("ssid")),
                "band": _clean_name(u.get("band")),
                "rssi": u.get("rssi") or None,
                "switch_port": u.get("port") or None,
                "online_since": u.get("onlinetime") or None,
                "rate_up": rate.get("up"), "rate_down": rate.get("down"),
                "conns": rate.get("conns"),
            }

        for e in arp:
            mac = _norm_mac(e.get("hardware"))
            if not mac or mac in seen:
                continue
            seen.add(mac)
            c = _build(mac, e.get("address"), e.get("intf"), ul_by_mac.get(mac))
            clients.append(c)
            vlan_counts[c["vlan"]] = vlan_counts.get(c["vlan"], 0) + 1

        # user_list-only devices (e.g. wireless clients not in ARP)
        for mac, u in ul_by_mac.items():
            if mac in seen:
                continue
            seen.add(mac)
            c = _build(mac, u.get("userIp"), None, u)
            clients.append(c)
            vlan_counts[c["vlan"]] = vlan_counts.get(c["vlan"], 0) + 1

        # ── Physical ports ────────────────────────────────────────────────
        ps = await self._getx("port_status", no_parse=False)
        ports = ps.get("List", []) if isinstance(ps, dict) else []

        # ── Live WAN throughput ───────────────────────────────────────────
        flow_if = await self._getx("flow", {"func": "interface_info"})
        wan_flow = flow_if if isinstance(flow_if, dict) else {}
        # flow interface_info is double-nested: {count, data:{wan,wan1}} — the
        # _getx helper strips the outer .data, so unwrap the inner one here.
        if isinstance(wan_flow.get("data"), dict):
            wan_flow = wan_flow["data"]

        # ── Per-WAN IP detail ─────────────────────────────────────────────
        ipinfo = await self._getx("ipinfo") or {}

        # ── Internet up/down ──────────────────────────────────────────────
        nc = await self._getx("networkConnect", no_parse=False)
        internet_up = bool(nc and str(nc.get("connnected")).lower() == "true")

        # ── Topology (APs / switches) ─────────────────────────────────────
        topo_raw = await self._getx("local_topology",
                                   {"fromcache": "true", "caller": "eweb"})
        topo = []
        if isinstance(topo_raw, dict) and isinstance(topo_raw.get("topo"), dict):
            self._flatten_topology(topo_raw["topo"], topo)

        # ── WAN uplinks + sysinfo ─────────────────────────────────────────
        mllb_live = await self._get("mllb", {"getype": "0"})
        mllb_cfg = await self._cfg("mllb")
        mllb = mllb_live or (mllb_cfg.get("data", mllb_cfg)
                             if isinstance(mllb_cfg, dict) else {}) or {}
        wan_lines = mllb.get("master_list", []) if isinstance(mllb, dict) else []
        active_wan = mllb.get("intf") if isinstance(mllb, dict) else None

        sysinfo = await self._get("sysinfo") or {}

        # ── PPPoE connection log per WAN line (drop tracking) ──────────────
        # Fully guarded: a failure here must never take down the whole update.
        pppoe = {}
        _pppoe_debug = {}
        try:
            for line in wan_lines:
                ifn = line.get("ifname")
                if not ifn:
                    continue
                raw = await self.api.raw_cmd(
                    "devSta.get", "pppoeLog",
                    data={"intf_name": [ifn]}, no_parse=False)
                _pppoe_debug[ifn] = repr(raw)[:250]
                body = raw.get("data") if isinstance(raw, dict) else None
                entries = None
                if isinstance(body, dict) and isinstance(body.get(ifn), list):
                    entries = body[ifn]
                elif isinstance(raw, dict) and isinstance(raw.get(ifn), list):
                    entries = raw[ifn]
                if entries:
                    try:
                        pppoe[ifn] = self._parse_pppoe(entries)
                    except Exception as err:  # noqa: BLE001
                        _pppoe_debug[ifn] = f"parse error: {err}"
        except Exception as err:  # noqa: BLE001
            _pppoe_debug["_error"] = str(err)
            _LOGGER.warning("Reyee pppoe read failed: %s", err)

        # ── WiFi SSIDs from the AC controller (read-only) ─────────────────
        # Mirror the exact call the deep probe uses (data=None), fully guarded.
        ssids = []
        _ssid_debug = ""
        try:
            wireless_raw = await self.api.raw_cmd("acConfig.get", "wireless")
            _ssid_debug = repr(wireless_raw)[:400]
            wireless = None
            if isinstance(wireless_raw, dict):
                inner = wireless_raw.get("data")
                wireless = inner if isinstance(inner, dict) else wireless_raw
            if isinstance(wireless, dict) and wireless.get("ssidList"):
                for s_ in wireless.get("ssidList", []):
                    ssids.append({
                        "name": s_.get("ssidName"),
                        "enabled": s_.get("enable") == "true",
                        "hidden": s_.get("ishidden") == "true",
                        "vlan": s_.get("vlanId"),
                        "guest": s_.get("guest") == "true",
                        "band": s_.get("relatedRadio"),
                        "wlan_id": s_.get("wlanId"),
                    })
        except Exception as err:  # noqa: BLE001
            _ssid_debug = f"read error: {err}"
            _LOGGER.warning("Reyee wireless read failed: %s", err)
        _LOGGER.info("Reyee [v1.11.4] parsed %d ssids", len(ssids))

        # port forwards + flow control (confirmed writable)
        pm = await self._cfg("port_mapping")
        pm_data = pm.get("data", pm) if isinstance(pm, dict) else {}
        port_forwards = pm_data.get("portMapping", []) if isinstance(pm_data, dict) else []
        fc = await self._cfg("flowctrl")
        flowctrl = fc.get("data", fc) if isinstance(fc, dict) else {}

        return {
            "clients": clients,
            "vlans": vlans,
            "vlan_counts": vlan_counts,
            "ports": ports,
            "wan_flow": wan_flow,
            "ipinfo": ipinfo,
            "internet_up": internet_up,
            "topology": topo,
            "wan_lines": wan_lines,
            "active_wan": active_wan,
            "mllb": mllb,
            "sysinfo": sysinfo,
            "wan_ip": sysinfo.get("wan_ip"),
            "port_forwards": port_forwards,
            "flowctrl": flowctrl,
            "pppoe": pppoe,
            "ssids": ssids,
            "ssids_debug": _ssid_debug,
            "pppoe_debug": _pppoe_debug,
        }

    # ── Writes (unchanged) ───────────────────────────────────────────────
    async def async_set_primary_wan(self, ifname):
        cfg = await self._cfg("mllb")
        if not cfg:
            raise ReyeeConnError("Could not read current WAN config")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        await self.api.set_config("mllb", build_master_swap_payload(data, ifname))
        await self.async_request_refresh()

    async def async_set_forced_switch(self, enabled):
        cfg = await self._cfg("mllb")
        if not cfg:
            raise ReyeeConnError("Could not read current WAN config")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        stamps = ("version", "configTime", "currentTime", "configId")
        payload = {k: v for k, v in data.items() if k not in stamps}
        payload["backup_discon"] = "1" if enabled else "0"
        await self.api.set_config("mllb", payload)
        await self.async_request_refresh()

    async def async_add_port_forward(self, rule):
        cfg = await self._cfg("port_mapping")
        if not cfg:
            raise ReyeeConnError("Could not read current port_mapping")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        await self.api.set_config("port_mapping", build_portmap_add(data, rule))
        await self.async_request_refresh()

    async def async_remove_port_forward(self, rule_name):
        cfg = await self._cfg("port_mapping")
        if not cfg:
            raise ReyeeConnError("Could not read current port_mapping")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        await self.api.set_config("port_mapping", build_portmap_remove(data, rule_name))
        await self.async_request_refresh()

    async def async_set_flow_control(self, enabled):
        cfg = await self._cfg("flowctrl")
        if not cfg:
            raise ReyeeConnError("Could not read current flowctrl")
        data = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
        await self.api.set_config("flowctrl", build_flowctrl_toggle(data, enabled))
        await self.async_request_refresh()

    async def async_set_ssid_enabled(self, wlan_id, enabled: bool):
        """Enable/disable a WiFi SSID via the AC controller."""
        cfg = await self._ac("wireless", {"groupId": "0"})
        if not cfg:
            raise ReyeeConnError("Could not read current wireless config")
        payload = build_ssid_toggle(cfg, wlan_id, enabled)
        await self.api.set_ac_config("wireless", payload)
        _LOGGER.info("Reyee: SSID wlanId=%s enabled=%s", wlan_id, enabled)
        await self.async_request_refresh()
