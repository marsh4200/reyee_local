"""Reyee eWeb local API client (ReyeeOS 2.x LuCI JSON-RPC)."""
import asyncio
import base64
import hashlib
import logging
import os
import time

import async_timeout

_LOGGER = logging.getLogger(__name__)

_AES_KEY = b"RjYkhwzx$2018!"
_OK_RCODE = "00000000"


class ReyeeAuthError(Exception):
    """Login rejected."""


class ReyeeConnError(Exception):
    """Could not reach the device."""


def _evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len=32, iv_len=16):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        d += prev
    return d[:key_len], d[key_len:key_len + iv_len]


def _encrypt_password(plain: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(_AES_KEY, salt)
    data = (plain + "\n").encode()
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(b"Salted__" + salt + ct).decode()


class ReyeeLocalAPI:
    def __init__(self, host, password, session, username="admin"):
        self.host = host
        self.username = username
        self.password = password
        self.session = session
        self.sid = None
        self.sn = None
        self._base = None
        self._id = 0

    def _next_id(self):
        self._id += 1
        return self._id

    async def _resolve_base(self):
        if self._base:
            return self._base
        for scheme in ("https", "http"):
            url = f"{scheme}://{self.host}/cgi-bin/luci/api/auth"
            try:
                async with async_timeout.timeout(8):
                    async with self.session.post(
                        url, json={"method": "login", "params": {}}, ssl=False
                    ) as resp:
                        await resp.read()
                self._base = f"{scheme}://{self.host}"
                return self._base
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                continue
        raise ReyeeConnError(f"No eWeb API on {self.host}")

    async def login(self):
        base = await self._resolve_base()
        # Encrypted login (matches your working setup); fall back to plaintext.
        attempts = [
            {
                "username": self.username,
                "password": _encrypt_password(self.password),
                "encry": True,
                "time": int(time.time()),
                "limit": False,
            },
            {"username": self.username, "password": self.password},
        ]
        last = None
        for params in attempts:
            payload = {"id": self._next_id(), "method": "login", "params": params}
            try:
                async with async_timeout.timeout(10):
                    async with self.session.post(
                        f"{base}/cgi-bin/luci/api/auth", json=payload, ssl=False
                    ) as resp:
                        last = await resp.json(content_type=None)
            except asyncio.TimeoutError as err:
                raise ReyeeConnError(f"Timeout contacting {self.host}") from err
            except Exception as err:  # noqa: BLE001
                raise ReyeeConnError(f"Connection error: {err}") from err

            data = last.get("data") or {}
            if data.get("sid"):
                self.sid = data["sid"]
                self.sn = data.get("sn")
                _LOGGER.debug("Reyee login OK sid=%s sn=%s", self.sid, self.sn)
                return self.sid

        raise ReyeeAuthError(f"Login rejected: {last}")

    async def _cmd(self, method, module, data=None, device="pc", _retry=True):
        """Core dispatch: everything goes through /api/cmd."""
        if not self.sid:
            await self.login()
        base = self._base or await self._resolve_base()

        params = {"module": module, "device": device}
        if data is not None:
            params["data"] = data
        payload = {"id": self._next_id(), "method": method, "params": params}

        try:
            async with async_timeout.timeout(12):
                async with self.session.post(
                    f"{base}/cgi-bin/luci/api/cmd?auth={self.sid}",
                    json=payload, ssl=False,
                ) as resp:
                    body = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise ReyeeConnError(f"Timeout on {method}/{module}") from err
        except Exception as err:  # noqa: BLE001
            raise ReyeeConnError(f"Error on {method}/{module}: {err}") from err

        d = body.get("data")
        rcode = ""
        if isinstance(d, dict):
            rcode = str(d.get("rcode", ""))
        if not rcode:
            rcode = str(body.get("rcode", ""))

        # Session expired -> re-auth once.
        if _retry and (rcode in ("401", "403", "-1") or body.get("code") in (401, 403)):
            self.sid = None
            return await self._cmd(method, module, data, device, _retry=False)

        return d if d is not None else body

    async def get_state(self, module, data=None):
        """devSta.get — runtime state for a module (clients, ports, wan...)."""
        return await self._cmd("devSta.get", module, data)

    async def get_config(self, module, data=None):
        """devConfig.get — persisted config for a module."""
        return await self._cmd("devConfig.get", module, data)


    async def raw_cmd(self, method, module, data=None, no_parse=False, extra=None):
        """
        Raw call for diagnostics / advanced modules.

        Reyee's eWeb sends more than {module,device} for many modules: a
        `data` sub-object, plus `noParse`/`async`/`remoteIp` flags. Support all
        of them so modules like user_list, flow, pppoeLog answer correctly.
        """
        if not self.sid:
            await self.login()
        base = self._base or await self._resolve_base()
        params = {
            "module": module,
            "noParse": bool(no_parse),
            "async": None,
            "remoteIp": False,
            "device": "pc",
        }
        if data is not None:
            params["data"] = data
        if extra:
            params.update(extra)
        payload = {"id": self._next_id(), "method": method, "params": params}
        try:
            async with async_timeout.timeout(15):
                async with self.session.post(
                    f"{base}/cgi-bin/luci/api/cmd?auth={self.sid}",
                    json=payload, ssl=False,
                ) as resp:
                    return await resp.json(content_type=None)
        except Exception as err:  # noqa: BLE001
            return {"_error": str(err)}


    async def set_config(self, module, data, timeout=60):
        """
        Write config (devConfig.set). Confirmed for module=mllb on EG.
        A timeout is treated as success — the gateway applies WAN changes
        asynchronously and may briefly drop the mgmt path while reconverging.
        """
        if not self.sid:
            await self.login()
        base = self._base or await self._resolve_base()
        params = {"module": module, "device": "pc", "data": data}
        payload = {"id": self._next_id(), "method": "devConfig.set", "params": params}

        try:
            async with async_timeout.timeout(timeout):
                async with self.session.post(
                    f"{base}/cgi-bin/luci/api/cmd?auth={self.sid}",
                    json=payload, ssl=False,
                ) as resp:
                    body = await resp.json(content_type=None)
        except asyncio.TimeoutError:
            _LOGGER.warning("Reyee: %s write timed out — treating as applied", module)
            return {"rcode": _OK_RCODE, "_timeout": True}
        except Exception as err:  # noqa: BLE001
            raise ReyeeConnError(f"Write failed on {module}: {err}") from err

        rcode = str(body.get("rcode", "")) or str(
            (body.get("data") or {}).get("rcode", "")
            if isinstance(body.get("data"), dict) else ""
        )
        if rcode and rcode != _OK_RCODE:
            msg = body.get("message") or body.get("rmsg") or body
            raise ReyeeConnError(f"Router rejected {module} write: {msg}")
        return body

    async def set_ac_config(self, module, data, timeout=60):
        """Write AC-controller config (acConfig.set), e.g. wireless SSIDs."""
        if not self.sid:
            await self.login()
        base = self._base or await self._resolve_base()
        params = {"module": module, "noParse": False, "async": None,
                  "remoteIp": False, "device": "pc", "data": data}
        payload = {"id": self._next_id(), "method": "acConfig.set", "params": params}
        try:
            async with async_timeout.timeout(timeout):
                async with self.session.post(
                    f"{base}/cgi-bin/luci/api/cmd?auth={self.sid}",
                    json=payload, ssl=False,
                ) as resp:
                    body = await resp.json(content_type=None)
        except asyncio.TimeoutError:
            _LOGGER.warning("Reyee: %s AC write timed out — treating as applied", module)
            return {"code": 0, "_timeout": True}
        except Exception as err:  # noqa: BLE001
            raise ReyeeConnError(f"AC write failed on {module}: {err}") from err
        code = body.get("code")
        inner = body.get("data") if isinstance(body.get("data"), dict) else {}
        if code not in (0, "0", None) or inner.get("code") not in (0, "0", None):
            raise ReyeeConnError(f"Router rejected {module} AC write: {body}")
        return body


def build_master_swap_payload(mllb_data: dict, primary_ifname: str) -> dict:
    """
    Return an mllb config dict making primary_ifname the master.
    Preserves every existing per-line field (w/band_up/band_down/...) and only
    flips the master bit. Strips read-only stamps the setter rejects.
    """
    stamps = ("version", "configTime", "currentTime", "configId")
    lines = mllb_data.get("master_list", [])
    ifnames = [str(e.get("ifname", "")) for e in lines]
    if primary_ifname not in ifnames:
        raise ValueError(f"{primary_ifname!r} not in WAN lines {ifnames}")

    out = {k: v for k, v in mllb_data.items() if k not in stamps}
    out["master_list"] = [
        {**e, "m": "1" if str(e.get("ifname")) == primary_ifname else "0"}
        for e in lines
    ]
    return out


_STAMP_FIELDS = ("version", "configTime", "currentTime", "configId")


def _strip_stamps(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _STAMP_FIELDS}


def build_portmap_add(cfg: dict, rule: dict) -> dict:
    """Return a port_mapping config with `rule` added (or replaced by ruleName)."""
    out = _strip_stamps(cfg)
    name = str(rule.get("ruleName", "")).strip()
    rules = [r for r in out.get("portMapping", [])
             if str(r.get("ruleName", "")).strip() != name]
    rules.append(rule)
    out["portMapping"] = rules
    return out


def build_portmap_remove(cfg: dict, rule_name: str) -> dict:
    """Return a port_mapping config with the named rule removed."""
    out = _strip_stamps(cfg)
    name = str(rule_name).strip()
    out["portMapping"] = [
        r for r in out.get("portMapping", [])
        if str(r.get("ruleName", "")).strip() != name
    ]
    return out


def build_flowctrl_toggle(cfg: dict, tc_on: bool) -> dict:
    """Return a flowctrl config with traffic control switched on/off."""
    out = _strip_stamps(cfg)
    out["tcSwitch"] = "on" if tc_on else "off"
    return out


_AC_STAMP_FIELDS = ("configTime", "currentTime", "configId",
                    "subConfigId", "networkId")


def build_ssid_toggle(wireless_cfg: dict, wlan_id, enable: bool) -> dict:
    """
    Return a wireless config with one SSID's enable flipped, everything else
    (radioList, healthy, other SSIDs, all per-SSID fields) preserved exactly.
    Strips the read-only stamps the eWeb write omits.
    """
    wid = str(wlan_id)
    out = {k: v for k, v in wireless_cfg.items() if k not in _AC_STAMP_FIELDS}
    out["ssidList"] = [
        ({**s, "enable": ("true" if enable else "false")}
         if str(s.get("wlanId")) == wid else dict(s))
        for s in wireless_cfg.get("ssidList", [])
    ]
    return out


