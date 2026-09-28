"""Split the integration page into two collapsible groups using config subentries.

  • "Reyee Network"      — gateway, access points, switches (+ all hub entities)
  • "Connected Devices"  — every client tracked on the network

Needs Home Assistant 2025.3+ (config subentries). On older versions every helper
here is a no-op and the integration behaves exactly as before.
"""
import logging
from types import MappingProxyType

from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:  # HA < 2025.3
    ConfigSubentry = None

NETWORK = "network"
CLIENTS = "clients"

_TITLES = {
    NETWORK: "Reyee Network",
    CLIENTS: "Connected Devices",
}


def subentry_id(entry, kind):
    """Return the subentry id for `kind`, or None when unsupported/missing."""
    for sub in (getattr(entry, "subentries", None) or {}).values():
        if sub.unique_id == kind:
            return sub.subentry_id
    return None


def ensure_subentries(hass, entry):
    """Create the two group subentries if they don't exist yet."""
    if ConfigSubentry is None:
        return
    for kind, title in _TITLES.items():
        if subentry_id(entry, kind):
            continue
        try:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType({}),
                    subentry_type=kind,
                    title=title,
                    unique_id=kind,
                ),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Reyee: could not create %s group: %s", kind, err)


def bind(entry, async_add_entities, kind):
    """Wrap a platform's async_add_entities so entities land in a group."""
    sid = subentry_id(entry, kind)
    if not sid:
        return async_add_entities

    def _add(new_entities, update_before_add=False):
        async_add_entities(new_entities, update_before_add, config_subentry_id=sid)

    return _add


def _current_subentries(device, entry_id):
    cur = getattr(device, "config_subentry_id", ...)
    if cur is not ...:  # HA 2026.9+: one entry / one subentry per device
        return {cur}
    return set(device.config_entries_subentries.get(entry_id, set()))


def _move(registry, device, entry_id, target):
    current = _current_subentries(device, entry_id)
    if current == {target}:
        return
    try:
        registry.async_update_device(device.id, new_config_subentry_id=target)
        return
    except TypeError:
        pass  # HA < 2026.9 — use the add/remove API
    registry.async_update_device(
        device.id, add_config_entry_id=entry_id, add_config_subentry_id=target)
    for old in current - {target}:
        registry.async_update_device(
            device.id, remove_config_entry_id=entry_id, remove_config_subentry_id=old)


def migrate_devices(hass, entry):
    """Move existing devices into the right group (no delete/re-add needed).

    Our own devices (gateway, APs, switches) carry a DOMAIN identifier; client
    devices are created by HA's ScannerEntity from the MAC alone.
    """
    net = subentry_id(entry, NETWORK)
    clients = subentry_id(entry, CLIENTS)
    if not net or not clients:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        ours = any(i[0] == DOMAIN for i in device.identifiers)
        try:
            _move(registry, device, entry.entry_id, net if ours else clients)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Reyee: could not regroup device %s: %s", device.id, err)
