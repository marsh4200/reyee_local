# Ruijie Reyee (Local) for Home Assistant

Local-polling Home Assistant integration for Ruijie Reyee EG-series gateways
(tested on **EG105G-V3**, ReyeeOS 2.x). Talks directly to the device's local
eWeb API over your LAN — no cloud dependency.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

## Features

### Monitoring
- **Connected devices** with real names (from the router's device remarks),
  grouped by VLAN, marked wired/wireless, with signal and switch port
- **Per-VLAN device sensors**, named from your router config
- **Device trackers** — one per client, grouped under the gateway
- **Physical port status** — live up/down, speed, duplex per port
- **Live WAN throughput** per uplink
- **Public WAN IP**, per-WAN IP/gateway/DNS detail
- **WAN role** (primary/backup) + **Active WAN** sensors
- **PPPoE drop tracking** — status, drop count, last disconnect/connect per line
- **Switches & access points** surfaced as devices (from topology)
- **WAN online** connectivity, port forwards, flow control, VPN clients, WiFi SSID list

### Control
- **Primary WAN select** — switch the active uplink
- **Forced switch** toggle — strict primary/backup failover
- **Flow control** switch — bandwidth management on/off
- **WiFi SSID on/off** — one switch per SSID
- **Add / remove port forward** services
- **Refresh** and **deep probe** buttons

## Installation (HACS)

1. HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/marsh4200/ruijie_reyee` as category **Integration**
3. Install **Ruijie Reyee (Local)**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Ruijie Reyee (Local)**
5. Enter the gateway IP, username (`admin`) and password

## Services

| Service | What it does |
|---|---|
| `reyee_local.set_primary_wan` | Make a WAN interface the primary uplink |
| `reyee_local.set_forced_switch` | Strict primary/backup failover on/off |
| `reyee_local.set_ssid` | Enable/disable a WiFi SSID by wlan_id |
| `reyee_local.add_port_forward` | Add or replace a port-forwarding rule |
| `reyee_local.remove_port_forward` | Remove a port-forwarding rule by name |
| `reyee_local.deep_probe` | Diagnostic sweep of the router's local API |

## How it works

The Reyee eWeb API is a LuCI JSON-RPC endpoint. Login is AES-256-CBC encrypted
("Salted__" format, MD5 KDF), returning a session id. Runtime data comes from
`devSta.get`, config from `devConfig.get` / `devConfig.set`, and the wireless
controller from `acConfig.get` / `acConfig.set`. Every data source is
auto-discovered — no values are hardcoded to one unit.

## Notes & limitations

- Config writes apply asynchronously; the gateway may briefly drop the
  management path while reconverging (handled as success).
- Topology online/offline updates on the router's own cache cycle.
- Not affiliated with or endorsed by Ruijie Networks. "Ruijie" and "Reyee"
  are trademarks of Ruijie Networks Co., Ltd.

## Disclaimer

Provided as-is under the MIT license. You are responsible for changes made to
your own network equipment through this integration.
