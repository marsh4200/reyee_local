"""Ruijie Reyee (Local) integration."""
import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from .api import ReyeeLocalAPI
from .coordinator import ReyeeCoordinator
from .diagnostics_probe import run_deep_probe

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = ReyeeLocalAPI(
        host=entry.data[CONF_HOST],
        password=entry.data[CONF_PASSWORD],
        username=entry.data.get(CONF_USERNAME, "admin"),
        session=async_get_clientsession(hass),
    )

    coordinator = ReyeeCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    sys = (coordinator.data or {}).get("sysinfo", {})
    if sys:
        model = sys.get("model") or sys.get("product_class") or "EG Series"
        gw_name = f"Reyee {model}"

        registry = dr.async_get(hass)
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=sys.get("manufacturer", "Ruijie Networks"),
            model=model,
            name=gw_name,
            hw_version=sys.get("hardware_version"),
            sw_version=sys.get("software_version"),
            connections={(dr.CONNECTION_NETWORK_MAC, sys.get("sys_mac"))}
                        if sys.get("sys_mac") else set(),
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
        # If an earlier version created this device with a fallback name
        # (e.g. "Reyee EG Series"), correct it now that we know the model —
        # but never override a name the user set themselves.
        if device.name_by_user is None and device.name != gw_name:
            registry.async_update_device(device.id, name=gw_name)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # ── Services ─────────────────────────────────────────────────────────
    def _coords():
        return [c for c in hass.data.get(DOMAIN, {}).values()
                if isinstance(c, ReyeeCoordinator)]

    async def _deep_probe(call: ServiceCall):
        for coord in _coords():
            await run_deep_probe(hass, coord)

    async def _set_primary_wan(call: ServiceCall):
        ifname = call.data["ifname"]
        for coord in _coords():
            await coord.async_set_primary_wan(ifname)

    async def _set_forced_switch(call: ServiceCall):
        enabled = call.data["enabled"]
        for coord in _coords():
            await coord.async_set_forced_switch(enabled)

    async def _add_port_forward(call: ServiceCall):
        rule = {
            "ruleName": call.data["name"],
            "proto":    call.data.get("protocol", "tcp"),
            "src":      call.data.get("wan_interface", "wan"),
            "srcPort":  str(call.data["wan_port"]),
            "destIp":   call.data["lan_ip"],
            "destPort": str(call.data["lan_port"]),
            "srcIp":    "", "intf": "", "list": "",
        }
        for coord in _coords():
            await coord.async_add_port_forward(rule)

    async def _remove_port_forward(call: ServiceCall):
        for coord in _coords():
            await coord.async_remove_port_forward(call.data["name"])

    async def _set_ssid(call: ServiceCall):
        wlan_id = call.data["wlan_id"]
        enabled = call.data["enabled"]
        for coord in _coords():
            await coord.async_set_ssid_enabled(wlan_id, enabled)

    if not hass.services.has_service(DOMAIN, "deep_probe"):
        hass.services.async_register(DOMAIN, "deep_probe", _deep_probe)
        hass.services.async_register(
            DOMAIN, "set_primary_wan", _set_primary_wan,
            schema=vol.Schema({vol.Required("ifname"): cv.string}),
        )
        hass.services.async_register(
            DOMAIN, "set_forced_switch", _set_forced_switch,
            schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
        )
        hass.services.async_register(
            DOMAIN, "add_port_forward", _add_port_forward,
            schema=vol.Schema({
                vol.Required("name"): cv.string,
                vol.Required("wan_port"): vol.Coerce(int),
                vol.Required("lan_ip"): cv.string,
                vol.Required("lan_port"): vol.Coerce(int),
                vol.Optional("protocol", default="tcp"): vol.In(
                    ["tcp", "udp", "tcp+udp"]),
                vol.Optional("wan_interface", default="wan"): cv.string,
            }),
        )
        hass.services.async_register(
            DOMAIN, "remove_port_forward", _remove_port_forward,
            schema=vol.Schema({vol.Required("name"): cv.string}),
        )
        hass.services.async_register(
            DOMAIN, "set_ssid", _set_ssid,
            schema=vol.Schema({
                vol.Required("wlan_id"): cv.string,
                vol.Required("enabled"): cv.boolean,
            }),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for svc in ("deep_probe", "set_primary_wan", "set_forced_switch",
                        "add_port_forward", "remove_port_forward", "set_ssid"):
                hass.services.async_remove(DOMAIN, svc)
    return unloaded
