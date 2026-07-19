# Ruijie Reyee (Local) for Home Assistant

A local-polling Home Assistant integration for Ruijie Reyee **EG-series
gateways**. It talks directly to the device's on-box eWeb API over your LAN —
no cloud account, no Ruijie Cloud dependency.

**Tested on:** EG105G-V3, ReyeeOS 2.360.x. Other EG models running ReyeeOS 2.x
should work; the integration auto-discovers VLANs, WAN uplinks, ports and
downstream devices rather than hardcoding them.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-1.15.0-blue.svg)

---

## What it does

### Monitoring (sensors)
- **Connected devices** — total count, with each client's real name (pulled
  from the router's device remarks), IP, VLAN, wired/wireless, signal, and
  switch port
- **Per-VLAN device counts** — named from your router config (e.g. ioT / GUEST
  / CCTV / MAIN)
- **Device trackers** — one per client, grouped under the gateway, usable for
  presence automations
- **Physical ports** — live up/down, speed and duplex per port
- **WAN throughput** — live up/down per uplink
- **Public IP** and per-WAN IP / gateway / DNS
- **WAN role** (primary/backup) and **Active WAN**
- **PPPoE drop tracking** — status, drop count, last disconnect/connect per line
- **Network devices** — downstream switches and APs, surfaced as their own
  devices with online status
- **WiFi SSID list**, port-forward list, flow-control state, VPN clients

### Control
- **Primary WAN** select — switch the active uplink
- **Forced switch** — strict primary/backup failover
- **Flow control** — bandwidth management on/off
- **WiFi rate limit** — global per-station upload/download caps
- **WiFi SSID** on/off — one switch per SSID
- **Device LEDs** — on/off per access point and the gateway
- **Port forwarding** — add/remove rules
- **Device internet block** — block/unblock a client by MAC

### Buttons
- **Refresh** — force an immediate poll
- **Deep probe** — diagnostic sweep of the router's local API (disabled by
  default)

---

## Installation

### HACS (recommended)
1. HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/marsh4200/ruijie_reyee`, category **Integration**
3. Install **Ruijie Reyee (Local)**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Ruijie Reyee (Local)**
5. Enter the gateway IP (e.g. `192.168.88.1`), username (`admin`) and password

### Manual
Copy `custom_components/reyee_local/` into your HA `config/custom_components/`
directory and restart.

---

## Services

| Service | Description |
|---|---|
| `reyee_local.set_primary_wan` | Make a WAN interface (`wan` / `wan1`) the primary uplink |
| `reyee_local.set_forced_switch` | Strict primary/backup failover on/off |
| `reyee_local.set_ssid` | Enable/disable a WiFi SSID by `wlan_id` |
| `reyee_local.set_rate_limit` | Global wireless up/down rate cap (kbps, 0 = unlimited) |
| `reyee_local.block_device` | Block a device (by MAC) from the internet |
| `reyee_local.unblock_device` | Remove a device's internet block |
| `reyee_local.add_port_forward` | Add or replace a port-forwarding rule |
| `reyee_local.remove_port_forward` | Remove a port-forwarding rule by name |
| `reyee_local.deep_probe` | Diagnostic sweep, posts results as a notification |

---

## Options

Set the polling interval (10–300 s) via **Configure** on the integration.

---

## How it works

The Reyee eWeb API is a LuCI JSON-RPC endpoint at `/cgi-bin/luci/api/`:

- **Login** — `POST /api/auth`. The password is AES-256-CBC encrypted
  (OpenSSL "Salted__" framing, MD5 key derivation) and exchanged for a session
  id (`sid`).
- **Everything else** — `POST /api/cmd?auth=<sid>` with `devSta.get` (runtime
  state), `devConfig.get` / `devConfig.set` (config), and `acConfig.get` /
  `acConfig.set` (the wireless controller). Success is `rcode: "00000000"` or
  `code: 0`.

Config writes are applied asynchronously; the gateway may briefly drop the
management path while it reconverges, which the integration treats as success
and then re-reads to confirm.

---

## Notes & limitations

- The EG105G-V3 has **no built-in WiFi** — wireless data (SSIDs, clients, rate
  limits, per-AP LEDs) is read from the on-box AC controller that manages your
  Reyee APs.
- Some access points may appear labelled by serial rather than name where the
  router's cached topology and live device lists disagree; rename them in the
  HA UI if desired.
- Topology online/offline status updates on the router's own cache cycle, not
  instantly.
- Home Assistant sorts the Devices list alphabetically; the gateway is named
  with a leading IP so it sorts to the top.

---

## Disclaimer

Provided as-is under the MIT license. You are responsible for any changes made
to your own network equipment through this integration. Not affiliated with or
endorsed by Ruijie Networks. "Ruijie" and "Reyee" are trademarks of Ruijie
Networks Co., Ltd.
