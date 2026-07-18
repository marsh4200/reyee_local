# Ruijie Reyee (Local) for Home Assistant

Local-polling Home Assistant integration for Ruijie Reyee EG-series gateways
(tested on **EG105G-V3**, ReyeeOS 2.x). Talks directly to the device's local
eWeb API over your LAN — no cloud dependency.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

## Features

### Monitoring
- **Connected devices** count, grouped by VLAN
- **Per-VLAN device sensors** (named from your router config, e.g. ioT / GUEST / CCTV / MAIN), with subnet, gateway, DHCP range
- **Device trackers** — one per client, with IP address and VLAN (use for presence automations)
- **Public WAN IP** sensor
- **Gateway** sensor — model, firmware, serial, MAC
- **Active WAN** + per-uplink primary/backup sensors
- **WAN online** connectivity binary sensor
- **Port forwards** sensor (lists all rules)
- **Flow control** sensor (traffic control + per-WAN bandwidth)
- **VPN clients** sensor (WireGuard)

### Control
- **Primary WAN select** — switch which uplink is primary from HA
- **Forced switch** toggle — strict primary/backup failover
- **Flow control** switch — master bandwidth management on/off
- **Add / remove port forward** services
- **Refresh** and **deep probe** buttons

## Installation (HACS)

1. HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/marsh4200/ruijie_reyee` as category **Integration**
3. Install **Ruijie Reyee (Local)**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Ruijie Reyee (Local)**
5. Enter the gateway IP (e.g. `192.168.110.1`), username (`admin`) and password

## Manual installation

Copy `custom_components/reyee_local/` into your HA `config/custom_components/`
directory and restart.

## Services

| Service | What it does |
|---|---|
| `reyee_local.set_primary_wan` | Make a WAN interface (`wan` / `wan1`) the primary uplink |
| `reyee_local.set_forced_switch` | Turn strict primary/backup failover on/off |
| `reyee_local.add_port_forward` | Add or replace a port-forwarding rule |
| `reyee_local.remove_port_forward` | Remove a port-forwarding rule by name |
| `reyee_local.deep_probe` | Diagnostic sweep of the router's local API |

## How it works

The Reyee eWeb API is a LuCI JSON-RPC endpoint:

- Login: `POST /cgi-bin/luci/api/auth` — password is AES-256-CBC encrypted
  (OpenSSL "Salted__" format, MD5 KDF) and returned as a session id (`sid`).
- Everything else: `POST /cgi-bin/luci/api/cmd?auth=<sid>` with
  `devSta.get` (runtime state) and `devConfig.get` / `devConfig.set` (config).
  Success is `rcode: "00000000"`.

Data sources confirmed on EG105G-V3: `arp` (clients), `network` (VLANs),
`mllb` (WAN load-balance), `port_mapping` (forwards), `flowctrl` (bandwidth),
`sysinfo`, `wireguard`.

## Notes & limitations

- The EG105G-V3 has **no built-in Wi-Fi** and its local API exposes **no
  per-port (G1/G2) status** — that data isn't available on this hardware.
  Wi-Fi client detail lives on your APs / Ruijie Cloud.
- Config writes are applied asynchronously; the gateway may drop the
  management path briefly while it reconverges (handled as success).
- Not affiliated with or endorsed by Ruijie Networks. "Ruijie" and "Reyee"
  are trademarks of Ruijie Networks Co., Ltd.

## Disclaimer

Provided as-is under the MIT license. You are responsible for changes made to
your own network equipment through this integration.
