"""Isolated AST tests of tracker discovery, not full Home Assistant integration.

Execute the actual async_setup_entry and _norm_mac functions with lightweight
stubs; no Home Assistant imports, network access, or devices are required.
Run with: python -m unittest discover -s tests -p 'test_device_tracker_ap_filter.py'
Set REYEE_TRACKER_SOURCE to a saved device_tracker.py to run these same
expectations against another revision (the unpatched source should fail).
"""

import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "reyee_local"
TRACKER_SOURCE = Path(
    os.environ.get("REYEE_TRACKER_SOURCE", str(COMPONENT / "device_tracker.py"))
)
AP1 = "02:00:00:00:ab:01"
AP2 = "02:00:00:00:ab:02"
CLIENT = "02:00:00:00:ab:10"


def function_node(path, name):
    """Extract production code without importing its HA-dependent module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def mac_variants(mac):
    compact = mac.replace(":", "")
    return (
        mac,
        mac.upper(),
        mac.upper().replace(":", "-"),
        ".".join(compact[i:i + 4] for i in range(0, 12, 4)),
        compact,
    )


def discovery(records, data):
    """Run setup and retain its registered listener for subsequent polls."""
    added, bound, unloaded, constructed = [], [], [], []
    coordinator = SimpleNamespace(data=data)
    entry = SimpleNamespace(entry_id="test-entry", async_on_unload=unloaded.append)

    def remove_listener():
        pass

    def listen(listener):
        coordinator.listener = listener
        return remove_listener

    def bind(bound_entry, add_entities, group):
        bound.append((bound_entry, group))
        return add_entities

    def tracker(coord, tracker_entry, mac):
        constructed.append((coord, tracker_entry, mac))
        return SimpleNamespace(mac=mac)

    coordinator.async_add_listener = listen
    namespace = {
        "DOMAIN": "reyee_local",
        "CLIENTS": "clients",
        "bind": bind,
        "ap_records": lambda config_entry: records,
        "ReyeeTracker": tracker,
    }
    # Compile each node with its own source filename for useful tracebacks.
    for path, name in (
        (COMPONENT / "coordinator.py", "_norm_mac"),
        (TRACKER_SOURCE, "async_setup_entry"),
    ):
        module = ast.Module(body=[function_node(path, name)], type_ignores=[])
        exec(compile(module, str(path), "exec"), namespace)

    hass = SimpleNamespace(data={"reyee_local": {entry.entry_id: coordinator}})
    asyncio.run(namespace["async_setup_entry"](hass, entry, added.extend))
    return SimpleNamespace(
        coordinator=coordinator,
        entry=entry,
        added=added,
        bound=bound,
        unloaded=unloaded,
        constructed=constructed,
        remove_listener=remove_listener,
    )


def added_macs(result):
    return [entity.mac for entity in result.added]


class TrackerAPFilterTests(unittest.TestCase):
    def test_configured_aps_excluded_plain_client_kept(self):
        result = discovery(
            [{"mac": AP1}, {"mac": AP2}],
            {"clients": [{"mac": AP1}, {"mac": CLIENT}, {"mac": AP2}]},
        )
        self.assertEqual(added_macs(result), [CLIENT])
        self.assertEqual(result.bound, [(result.entry, "clients")])
        self.assertEqual(result.unloaded, [result.remove_listener])

    def test_ap_record_mac_normalization(self):
        for mac in mac_variants(AP1):
            with self.subTest(mac=mac):
                result = discovery([{"mac": mac}], {"clients": [{"mac": AP1}]})
                self.assertEqual(added_macs(result), [])

    def test_client_mac_normalization_for_ap_filter(self):
        for mac in mac_variants(AP1):
            with self.subTest(mac=mac):
                result = discovery([{"mac": AP1}], {"clients": [{"mac": mac}]})
                self.assertEqual(added_macs(result), [])

    def test_empty_ap_list_preserves_normal_discovery(self):
        result = discovery([], {"clients": [
            {"mac": AP1}, {"mac": CLIENT}, {"mac": CLIENT},
            {}, {"mac": None}, {"mac": ""},
        ]})
        self.assertEqual(added_macs(result), [AP1, CLIENT])

    def test_absent_null_and_empty_ap_macs_are_safe(self):
        result = discovery(
            [{}, {"mac": None}, {"mac": ""}],
            {"clients": [{"mac": CLIENT}]},
        )
        self.assertEqual(added_macs(result), [CLIENT])

    def test_repeated_polls_deduplicate_and_add_later_client(self):
        result = discovery([{"mac": AP1}], {"clients": [{"mac": AP1}]})
        result.coordinator.data = {"clients": [
            {"mac": AP1}, {"mac": CLIENT}, {"mac": CLIENT},
        ]}
        result.coordinator.listener()
        result.coordinator.listener()
        self.assertEqual(added_macs(result), [CLIENT])
        self.assertEqual(len(result.constructed), 1)

    def test_ap_first_seen_on_later_poll_is_excluded(self):
        result = discovery([{"mac": AP1}], {"clients": [{"mac": CLIENT}]})
        result.coordinator.data = {"clients": [{"mac": CLIENT}, {"mac": AP1}]}
        result.coordinator.listener()
        self.assertEqual(added_macs(result), [CLIENT])

    def test_new_setup_rebuilds_exclusions_after_add_and_remove(self):
        records = []
        data = {"clients": [{"mac": AP1}, {"mac": CLIENT}]}
        self.assertEqual(added_macs(discovery(records, data)), [AP1, CLIENT])
        records.append({"mac": AP1})
        self.assertEqual(added_macs(discovery(records, data)), [CLIENT])
        records.clear()
        self.assertEqual(added_macs(discovery(records, data)), [AP1, CLIENT])

    def test_empty_coordinator_clients(self):
        for data in (None, {}, {"clients": []}):
            with self.subTest(data=data):
                result = discovery([{"mac": AP1}], data)
                result.coordinator.listener()
                self.assertEqual(added_macs(result), [])
                self.assertEqual(result.constructed, [])

    def test_original_client_mac_passed_unchanged_to_tracker(self):
        for mac in mac_variants(CLIENT):
            with self.subTest(mac=mac):
                result = discovery([{"mac": AP1}], {"clients": [{"mac": mac}]})
                self.assertEqual(added_macs(result), [mac])
                self.assertEqual(
                    result.constructed, [(result.coordinator, result.entry, mac)]
                )


if __name__ == "__main__":
    unittest.main()
