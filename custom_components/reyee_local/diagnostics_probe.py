"""
Deep diagnostic sweep — service reyee_local.deep_probe / button.

v2: reads config modules (devConfig.get is param-free & read-only) across the
full EG feature set — port mapping, DDNS, flow control, VPN, firewall, DHCP
reservations, DNS, static routes, MAC clone, SON. Everything that comes back
with a real shape becomes a candidate for a control entity. Writes are NEVER
issued here — this is read-only discovery.
"""
import json
import logging

from homeassistant.components.persistent_notification import async_create

_LOGGER = logging.getLogger(__name__)

# Config modules across the documented EG feature set. devConfig.get needs no
# params, so this is safe: it either returns the module's config or an error.
_CONFIG_MODULES = [
    # networking / WAN
    "network", "mllb", "wan", "lan", "vlan", "dns", "dnsProxy", "dhcpBind",
    "staticDhcp", "ipMac", "macBind", "arpBind",
    # NAT / forwarding
    "portMap", "port_mapping", "portMapping", "natMapping", "dmz", "upnp",
    "virtualServer", "napt",
    # security / firewall
    "firewall", "acl", "urlFilter", "appControl", "macFilter", "attackDefense",
    "blacklist", "whitelist",
    # traffic
    "flowControl", "smartFlow", "flowctrl", "rateLimit", "qos", "iptv",
    # VPN
    "wireguard", "ipsec", "pptp", "l2tp", "openvpn", "vpn",
    # dynamic dns / remote
    "ddns", "peanuthull", "noip", "remoteMgmt",
    # system / behaviour
    "son", "reyeeMesh", "workMode", "macClone", "led", "reboot_schedule",
    "schedule", "timedReboot", "sysCfg", "ntp", "timezone", "loginCfg",
    "adminPass", "webCfg",
    # routing
    "staticRoute", "route", "policyRoute", "pbr",
]

# A few runtime-state modules worth capturing too.
_STATE_MODULES = [
    ("devSta.get", "sysinfo", None),
    ("devSta.get", "arp", None),
    ("devSta.get", "mllb", {"getype": "0"}),
    ("devSta.get", "cpu", {"getype": "0"}),
    ("devSta.get", "memory", {"getype": "0"}),
    ("devSta.get", "sys", {"getype": "0"}),
    ("devSta.get", "wireguard", {"getype": "0"}),
    ("devSta.get", "wireguard", {"getype": "1"}),
    ("devSta.get", "ddns", {"getype": "0"}),
    ("devSta.get", "flowStat", {"getype": "0"}),
    ("devSta.get", "ifStat", {"getype": "0"}),
]


def _classify(body):
    if not isinstance(body, dict):
        return "other", str(body)[:1500]
    if "_error" in body:
        return "error", body["_error"]
    rcode = body.get("rcode")
    rmsg = body.get("rmsg") or body.get("message")
    data = body.get("data")
    if isinstance(data, str) and data.strip() == "":
        return "empty", ""
    if rcode and str(rcode) != "00000000":
        return "error", f"rcode={rcode} {rmsg or ''}"[:80]
    if rmsg and not data:
        return "error", str(rmsg)[:80]
    # real data can be wrapped in .data OR be the top-level body
    if data not in (None, {}, []):
        return "data", json.dumps(data)[:1500]
    real = {k: v for k, v in body.items()
            if k not in ("code", "id", "error", "rcode", "message", "rmsg", "data")}
    if real:
        return "data", json.dumps(real)[:1500]
    return "empty", ""


async def run_deep_probe(hass, coordinator):
    api = coordinator.api
    hits, errors, empties = [], [], []

    for module in _CONFIG_MODULES:
        body = await api.raw_cmd("devConfig.get", module)
        kind, preview = _classify(body)
        label = f"devConfig.get {module}"
        if kind == "data":
            hits.append((label, preview))
        elif kind == "error":
            errors.append(module)
        else:
            empties.append(module)

    for method, module, data in _STATE_MODULES:
        body = await api.raw_cmd(method, module, data)
        kind, preview = _classify(body)
        label = f"{method} {module}" + (f" {json.dumps(data)}" if data else "")
        if kind == "data":
            hits.append((label, preview))

    lines = [f"## Reyee Deep Probe v2\n\n**{len(hits)} modules returned real data.**\n"]
    for label, preview in hits:
        lines.append(f"### ✅ {label}\n`{preview}`\n")
    if empties:
        lines.append(f"\n**Present but empty (exist, unconfigured):** {', '.join(empties)}")
    if errors:
        lines.append(f"\n**Not on this firmware:** {', '.join(errors)}")

    async_create(
        hass, "\n".join(lines),
        title="Reyee Deep Probe v2",
        notification_id="reyee_deep_probe",
    )
    _LOGGER.info("Reyee deep probe v2: %d hits, %d empty, %d absent",
                 len(hits), len(empties), len(errors))
