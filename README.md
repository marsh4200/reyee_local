# 🌐 Ruijie Reyee (Local) for Home Assistant

<p align="center">

**Complete local control for Ruijie Reyee EG Series Gateways**

No cloud • No subscriptions • Direct LAN communication

[![Version](https://img.shields.io/badge/version-v1.15.0-2ea44f?style=for-the-badge)]()
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-Compatible-41BDF5?style=for-the-badge&logo=homeassistant)]()
[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=for-the-badge)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)]()

</p>

---

## ✨ Overview

Ruijie Reyee (Local) is a **fully local** Home Assistant integration for
**Reyee EG-series gateways**.

Unlike the official cloud integration, this connects **directly to your
gateway** using the built-in eWeb API over your LAN.

✔ No Cloud Account

✔ No Internet Required

✔ Real-time Monitoring

✔ Full Network Control

✔ Automatic Discovery

---

# 🚀 Features

## 📊 Network Monitoring

- 👥 Connected device list with friendly names
- 📍 Device Trackers for every client
- 🌐 VLAN discovery with named networks
- 🔌 Live Ethernet port status
- 📶 WAN upload/download throughput
- 🌍 Public IP monitoring
- 🔄 PPPoE reconnect tracking
- 📡 Connected APs and switches
- 📶 WiFi SSID monitoring
- 🔐 VPN client status
- 🔀 Active WAN detection
- 🌐 Port forwarding list

---

## 🎛 Control

Control almost everything directly from Home Assistant.

| Feature | Supported |
|----------|-----------|
| 🌐 Primary WAN Switching | ✅ |
| 🔄 Forced WAN Failover | ✅ |
| 📶 WiFi SSID Enable/Disable | ✅ |
| 🚦 Flow Control | ✅ |
| ⚡ WiFi Rate Limiting | ✅ |
| 💡 Gateway LEDs | ✅ |
| 💡 AP LEDs | ✅ |
| 🚫 Block Internet Access | ✅ |
| 🌍 Port Forward Management | ✅ |

---

## ⚙ Buttons

- 🔄 Refresh Router
- 🔍 Deep API Probe

---

# 🖥 Supported Hardware

## Tested Hardware

- ✅ EG105G-V3 (ReyeeOS 2.360.x)
- ✅ RG-EW3000GX

Compatible with most EG-series gateways running **ReyeeOS 2.x**

The integration automatically discovers:

- VLANs
- WAN Interfaces
- Ethernet Ports
- Access Points
- Switches
- Clients

No model-specific configuration required.

---

# 📦 Installation

## HACS (Recommended)

1. Open **HACS**
2. Integrations
3. ⋮ → **Custom Repositories**
4. Add

```
https://github.com/marsh4200/ruijie_reyee
```

Category:

```
Integration
```

Restart Home Assistant.

Then:

```
Settings
→ Devices & Services
→ Add Integration
→ Ruijie Reyee (Local)
```

Enter:

- Gateway IP
- Username
- Password

---

## Manual Installation

Copy

```
custom_components/reyee_local/
```

into

```
config/custom_components/
```

Restart Home Assistant.

---

# 🛠 Services

| Service | Purpose |
|-----------|----------|
| `set_primary_wan` | Switch Primary WAN |
| `set_forced_switch` | Enable/Disable Failover |
| `set_ssid` | Enable or Disable SSIDs |
| `set_rate_limit` | Wireless Speed Limits |
| `block_device` | Block Internet Access |
| `unblock_device` | Remove Internet Block |
| `add_port_forward` | Create Port Forward |
| `remove_port_forward` | Delete Port Forward |
| `deep_probe` | Advanced API Diagnostics |

---

# ⚡ Polling

Polling interval is configurable between

**10–300 seconds**

from the Integration Configure menu.

---

# 🔒 How It Works

The integration communicates directly with the gateway's built-in **eWeb API**.

```
/cgi-bin/luci/api/
```

Authentication uses the same encrypted login process as the official web
interface.

Configuration changes are written locally and automatically verified after the
gateway applies them.

No telemetry.

No cloud.

No external services.

---

# ⚠ Notes

- EG105G-V3 has **no built-in WiFi**. Wireless information is collected from the integrated AP Controller.
- Some APs may display their serial number if topology information is incomplete.
- Device status depends on the gateway's topology refresh interval.
- The gateway device is prefixed with its IP address so it stays at the top of Home Assistant's device list.

---

# ❤️ Why This Integration?

Unlike cloud-based solutions, this integration provides:

- 🏠 100% Local
- ⚡ Faster Updates
- 🔒 Better Privacy
- 🌐 Works Without Internet
- 🚀 Native Home Assistant Entities
- 🔧 Nearly Every Router Feature Exposed

---

# 📄 License

Released under the **MIT License**.

This project is **not affiliated with or endorsed by Ruijie Networks**.

"Ruijie" and "Reyee" are trademarks of Ruijie Networks Co., Ltd.
