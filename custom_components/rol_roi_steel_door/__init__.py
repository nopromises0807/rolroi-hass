"""ROL-ROI Steel Door integration for Home Assistant.

Protocol is based on the original ROL-ROI STEEL DOOR APK:
- Cloud API is HTTPS /v3.
- Every POST is multipart/form-data and includes the APK's signature.
- GET requests that use getData() include the same signature in the query.
- Device control is MQTT over WebSocket ws://<server>:8080/ws.
- Door commands are JSON {"sdr": <1..5>, "u": <user_id>} encrypted with
  the AES key/IV derived from the device root_id.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import threading
from datetime import timedelta
from typing import Any, Callable

import aiohttp
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None

DOMAIN = "rol_roi_steel_door"
DEFAULT_API_HOST = "api.hunonicpro.com"
DEFAULT_API_PORT = 443
API_TIMEOUT = 30
PLATFORMS = ["lock", "cover", "sensor"]

APP_NAME = "queenviet"
APP_ROLE = 3
IS_PRO_APP = 0  # APK bundle is com.queenviet.door.qv, not com.iot.hunonic.newver

ACCESS_KEY = "accessKey=accessKey98ccdcbbe7b5528bec0ca31bbe8d93b4e76590dd"
SIGN_SUFFIX = "HUNONICBIGBUG94d3c445e72ae7805fca3489edac9608c893e66b"
SIGN_OFFSET = 58

MQTT_INFO_ID = "HUN0987654321123456"
MQTT_INFO_URL = f"https://infom.hunonicpro.com/v2?device_id={MQTT_INFO_ID}&dev=false"
MQTT_INFO_KEY = "yAlaCKUYI3qr0kTd"
MQTT_INFO_IV = "QFjnL4GVODlNB0eZ"
DEFAULT_MQTT_HOST = "mqtt.hunonicpro.com"
DEFAULT_MQTT_WS_PORT = 8080
DEFAULT_MQTT_USER = "bestbug"
DEFAULT_MQTT_PASSWORD = "bigbugdmm"

DOOR_ROOT_TYPES = {
    "sdoor", "sdoor1", "sdoor2", "sdoor3", "sdoor4", "sdoor5",
    "sdoorqv", "sdoorqv2",
}

_LOGGER = logging.getLogger(__name__)


def _js_string(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _b64_utf8(value: Any) -> str:
    return base64.b64encode(_js_string(value).encode("utf-8")).decode("ascii")


def hunonic_encode_sign(params: dict[str, Any]) -> str:
    """Exact implementation of APK module APIEnc.hunonicEncodeSign()."""
    total = 0
    for key, value in params.items():
        if key == "signature":
            continue
        # APK condition is: if (value && !equalVal(value, 0)) ... else ...
        # Therefore numeric 0 MUST take the else branch; it is not signed as Base64("0").
        if value and value != 0:
            value_b64 = _b64_utf8(value)
            # JS uses isNaN(base64_string), not a digit test. Base64 output from
            # UTF-8 is normally non-numeric, but keep the branch semantically aligned.
            try:
                float(value_b64)
                is_numeric = True
            except ValueError:
                is_numeric = False
            if not is_numeric:
                mid = len(value_b64) // 2
                total += ord(value_b64[0]) + ord(value_b64[mid]) + ord(value_b64[-1])
            else:
                total += int(value_b64)
        else:
            total += ord(key[0]) if key else ord("a")
            total += SIGN_OFFSET
    f = ACCESS_KEY + hashlib.md5(str(total).encode("utf-8")).hexdigest()
    return hashlib.md5(("sha256fake" + f + SIGN_SUFFIX).encode("utf-8")).hexdigest()


def md5_password(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def normalize_vietnam_phone(phone: str) -> str:
    # Match the APK TextInputPhoneForm.getPhone(): Vietnam numbers are sent
    # in national form with the leading 0 (e.g. 0386386118).
    p = re.sub(r"[^\d+]", "", phone.strip())
    if p.startswith("+84"):
        rest = p[3:]
        return "0" + rest if rest and not rest.startswith("0") else rest
    if p.startswith("84") and len(p) >= 10:
        rest = p[2:]
        return "0" + rest if rest and not rest.startswith("0") else rest
    if p.isdigit() and len(p) == 9:
        return "0" + p
    return p


def _aes_cbc_encrypt_bytes(text: str, key: bytes, iv: bytes) -> bytes:
    padder = sym_padding.PKCS7(128).padder()
    raw = padder.update(text.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(raw) + enc.finalize()


def _aes_cbc_decrypt_bytes(data: bytes, key: bytes, iv: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = dec.update(data) + dec.finalize()
    unpad = sym_padding.PKCS7(128).unpadder()
    return unpad.update(raw) + unpad.finalize()


def derive_device_key_iv(root_id: str) -> tuple[bytes, bytes]:
    """Exact APK keyById()/ivById(): AES(root_id, zero key/IV), then slices."""
    encrypted = _aes_cbc_encrypt_bytes(str(root_id), b"0" * 16, b"0" * 16)
    return encrypted[4:20], encrypted[12:28]


def _decode_mqtt_info(value: str) -> dict[str, Any] | None:
    try:
        raw = base64.b64decode(value)
        plain = _aes_cbc_decrypt_bytes(raw, MQTT_INFO_KEY.encode(), MQTT_INFO_IV.encode())
        obj = json.loads(plain.decode("utf-8"))
        if not obj.get("server"):
            return None
        return obj
    except Exception as err:
        _LOGGER.warning("Hunonic MQTT info decode failed: %s", err)
        return None


class HunonicMQTT:
    def __init__(self, hass: HomeAssistant, client: "HunonicAPIClient") -> None:
        self.hass = hass
        self.client = client
        self._mqtt = None
        self.connected = False
        self._lock = threading.Lock()
        self._started = False

    async def start(self) -> bool:
        if mqtt is None:
            _LOGGER.error("paho-mqtt is not installed")
            return False
        return await self.hass.async_add_executor_job(self._start_blocking)

    def _start_blocking(self) -> bool:
        with self._lock:
            if self._started:
                return self.connected
            try:
                info = self.client.mqtt_server or {}
                host = info.get("server") or DEFAULT_MQTT_HOST
                user = info.get("user") or DEFAULT_MQTT_USER
                password = info.get("pass") or info.get("password") or DEFAULT_MQTT_PASSWORD
                self._mqtt = mqtt.Client(transport="websockets", protocol=mqtt.MQTTv311)
                self._mqtt.ws_set_options(path="/ws")
                self._mqtt.username_pw_set(str(user), str(password))
                self._mqtt.on_connect = self._on_connect
                self._mqtt.on_disconnect = self._on_disconnect
                self._mqtt.on_message = self._on_message
                self._mqtt.connect(host, DEFAULT_MQTT_WS_PORT, 60)
                self._mqtt.loop_start()
                self._started = True
                _LOGGER.info("Hunonic MQTT connecting ws://%s:%s/ws", host, DEFAULT_MQTT_WS_PORT)
                return True
            except Exception as err:
                _LOGGER.error("Hunonic MQTT start failed: %s", err)
                self._mqtt = None
                self._started = False
                return False

    def _on_connect(self, _client, _userdata, _flags, rc, properties=None):
        if rc != 0:
            self.connected = False
            _LOGGER.error("Hunonic MQTT connection failed rc=%s", rc)
            return
        self.connected = True
        _LOGGER.info("Hunonic MQTT connected")
        for device in self.client.devices.values():
            self._subscribe_device(device)
        self.hass.loop.call_soon_threadsafe(self.client._mqtt_connected_changed, True)
        self.hass.loop.call_soon_threadsafe(self.client._request_all_status)

    def _on_disconnect(self, _client, _userdata, rc, properties=None):
        self.connected = False
        _LOGGER.warning("Hunonic MQTT disconnected rc=%s", rc)
        self.hass.loop.call_soon_threadsafe(self.client._mqtt_connected_changed, False)

    def _subscribe_device(self, device: dict[str, Any]) -> None:
        if not self._mqtt or not self.connected:
            return
        topic = device.get("topicpub") or device.get("topicPub")
        if topic:
            result, _mid = self._mqtt.subscribe(str(topic), qos=0)
            if result != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.error("MQTT subscribe failed rc=%s topic=%s", result, topic)

    async def refresh_subscriptions(self) -> None:
        if not self.connected:
            return
        await self.hass.async_add_executor_job(self._refresh_subscriptions_blocking)

    def _refresh_subscriptions_blocking(self) -> None:
        for device in self.client.devices.values():
            self._subscribe_device(device)

    async def publish_command(self, device: dict[str, Any], payload_json: str) -> bool:
        if not self.connected or not self._mqtt:
            if not await self.start():
                return False
            # Give the paho thread a short opportunity to complete CONNECT.
            for _ in range(20):
                if self.connected:
                    break
                await asyncio.sleep(0.1)
        if not self.connected:
            _LOGGER.error("Hunonic MQTT is not connected; command not sent")
            return False
        return await self.hass.async_add_executor_job(self._publish_blocking, device, payload_json)

    def _publish_blocking(self, device: dict[str, Any], payload_json: str) -> bool:
        topic = device.get("topicsub") or device.get("topicSub")
        root_id = device.get("root_id") or device.get("rootId") or device.get("id")
        if not topic or not root_id:
            _LOGGER.error("Door MQTT fields missing: id=%s root_id=%s topicsub=%s", device.get("id"), root_id, topic)
            return False
        try:
            key, iv = derive_device_key_iv(str(root_id))
            encrypted = _aes_cbc_encrypt_bytes(payload_json, key, iv)
            result = self._mqtt.publish(str(topic), encrypted, qos=0, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.error("MQTT publish failed rc=%s topic=%s", result.rc, topic)
                return False
            _LOGGER.info(
                "ROL-ROI command published: device=%s root_id=%s topic=%s payload=%s",
                device.get("id"), root_id, topic, payload_json,
            )
            return True
        except Exception as err:
            _LOGGER.error("MQTT publish/encrypt failed: %s", err)
            return False

    def _on_message(self, _client, _userdata, msg):
        topic = msg.topic
        device = self.client.device_by_topic(topic)
        if not device:
            return
        root_id = device.get("root_id") or device.get("rootId") or device.get("id")
        try:
            key, iv = derive_device_key_iv(str(root_id))
            plain = _aes_cbc_decrypt_bytes(bytes(msg.payload), key, iv).decode("utf-8")
            data = json.loads(plain)
            _LOGGER.debug("ROL-ROI MQTT message: device=%s data=%s", device.get("id"), data)
        except Exception as err:
            _LOGGER.debug("Unable to decrypt door MQTT message topic=%s: %s", topic, err)
            return
        self.hass.loop.call_soon_threadsafe(self.client.handle_device_message, device, data)

    async def stop(self) -> None:
        await self.hass.async_add_executor_job(self._stop_blocking)

    def _stop_blocking(self) -> None:
        with self._lock:
            if self._mqtt:
                try:
                    self._mqtt.disconnect()
                    self._mqtt.loop_stop()
                except Exception:
                    pass
            self._mqtt = None
            self.connected = False
            self._started = False


class HunonicAPIClient:
    def __init__(self, hass: HomeAssistant, session, phone: str, password: str, api_host=DEFAULT_API_HOST, api_port=DEFAULT_API_PORT):
        self.hass = hass
        self.session = session
        self.phone = normalize_vietnam_phone(phone)
        self.password = password
        self.api_host = api_host
        self.api_port = api_port
        self.token_id: str | None = None
        self.user: dict[str, Any] | None = None
        self.user_id: str | None = None
        self.base_url = self._base_url(api_host)
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_states: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, set[Callable[[dict[str, Any]], None]]] = {}
        self.mqtt_server: dict[str, Any] | None = None
        self.mqtt = HunonicMQTT(hass, self)
        self._unsub_refresh = None

    def _base_url(self, host: str) -> str:
        return f"https://{host}:{self.api_port}" if self.api_port != 443 else f"https://{host}"

    async def _post_form(self, path: str, params: dict[str, Any], retry=True):
        """Exact APK post(): multipart FormData + signature."""
        url = f"{self.base_url}/v3/{path.lstrip('/')}"
        form = aiohttp.FormData()
        for key, value in params.items():
            form.add_field(key, _js_string(value))
        form.add_field("signature", hunonic_encode_sign(params))
        async with self.session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = None
            if resp.status >= 500 and retry and self.api_host == "api.hunonicpro.com":
                self.api_host = "api2.hunonicpro.com"
                self.base_url = self._base_url(self.api_host)
                return await self._post_form(path, params, retry=False)
            return resp.status, data, raw

    async def _get_signed(self, path: str, params: dict[str, Any]):
        url = f"{self.base_url}/v3/{path.lstrip('/')}"
        query = dict(params)
        query["signature"] = hunonic_encode_sign(params)
        async with self.session.get(url, params=query, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = None
            return resp.status, data, raw

    async def authenticate(self) -> bool:
        params = {
            "phone": self.phone,
            "password": md5_password(self.password),
            "app_name": APP_NAME,
            "app_role": APP_ROLE,
            "is_pro_app": IS_PRO_APP,
        }
        _LOGGER.debug("Hunonic login request phone=%s app_name=%s app_role=%s is_pro_app=%s", self.phone, APP_NAME, APP_ROLE, IS_PRO_APP)
        for host in [self.api_host, "api2.hunonicpro.com"]:
            self.api_host = host
            self.base_url = self._base_url(host)
            try:
                status, data, raw = await self._post_form("user/login", params, retry=False)
                if status != 200 or not isinstance(data, dict):
                    _LOGGER.error("Hunonic login failed HTTP=%s response=%s", status, raw[:1000])
                    continue
                if data.get("status") is not True:
                    _LOGGER.error("Hunonic login rejected: message=%s error_code=%s", data.get("message"), data.get("error_code"))
                    # 1026 is normally signature/request validation; don't retry the same bad payload on api2.
                    return False
                user = data.get("data")
                token = user.get("token_id") if isinstance(user, dict) else None
                if not token:
                    _LOGGER.error("Hunonic login succeeded but token_id is missing: %s", data)
                    return False
                self.user = user
                self.user_id = str(user.get("id")) if user.get("id") is not None else None
                self.token_id = str(token)
                _LOGGER.info("Hunonic Cloud login OK, user_id=%s", self.user_id)
                return True
            except Exception as err:
                _LOGGER.warning("Hunonic login request to %s failed: %s", host, err)
        return False

    async def get_devices(self) -> list[dict[str, Any]]:
        if not self.token_id and not await self.authenticate():
            raise ConfigEntryAuthFailed("Unable to authenticate with Hunonic")
        status, data, raw = await self._get_signed("device/listDeviceByHome", {"token_id": self.token_id})
        if status != 200 or not isinstance(data, dict):
            raise ConfigEntryNotReady(f"Hunonic device list HTTP {status}: {raw[:500]}")
        if data.get("status") is not True:
            if data.get("error_code") == 40:
                self.token_id = None
                raise ConfigEntryAuthFailed("Hunonic session expired")
            raise ConfigEntryNotReady(f"Hunonic device list rejected: {data.get('message')}")
        flat: list[dict[str, Any]] = []
        for home in data.get("data") or []:
            if not isinstance(home, dict):
                continue
            for room in home.get("rooms") or []:
                if not isinstance(room, dict):
                    continue
                for device in room.get("devices") or []:
                    if not isinstance(device, dict):
                        continue
                    root_type = str(device.get("root_type") or device.get("type") or "")
                    if root_type not in DOOR_ROOT_TYPES:
                        continue
                    d = dict(device)
                    d["home_id"] = home.get("id")
                    d["home_name"] = home.get("name")
                    d["room_id"] = room.get("id")
                    d["room_name"] = room.get("name")
                    d["root_id"] = d.get("root_id") or d.get("id")
                    flat.append(d)
        self.devices = {str(d["id"]): d for d in flat if d.get("id") is not None}
        for d in self.devices.values():
            self.device_states.setdefault(str(d["id"]), {})
        _LOGGER.info("Hunonic Cloud synced: %s ROL-ROI door(s)", len(self.devices))
        await self.mqtt.refresh_subscriptions()
        return flat

    async def fetch_mqtt_server(self) -> None:
        try:
            async with self.session.get(MQTT_INFO_URL, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as resp:
                raw = await resp.text()
                payload = json.loads(raw) if raw else None
            encrypted = payload.get("data") if isinstance(payload, dict) else None
            if encrypted:
                info = _decode_mqtt_info(str(encrypted))
                if info and info.get("server"):
                    self.mqtt_server = info
                    _LOGGER.info("Hunonic MQTT server discovered: %s", info.get("server"))
                    return
        except Exception as err:
            _LOGGER.warning("Hunonic MQTT server discovery failed: %s", err)
        # APK also ships a default credential set. WebSocket control still uses :8080/ws.
        self.mqtt_server = {
            "server": DEFAULT_MQTT_HOST,
            "port": 1883,
            "user": DEFAULT_MQTT_USER,
            "pass": DEFAULT_MQTT_PASSWORD,
        }
        _LOGGER.warning("Using APK fallback MQTT server %s", DEFAULT_MQTT_HOST)

    def device_by_topic(self, topic: str) -> dict[str, Any] | None:
        for d in self.devices.values():
            if str(d.get("topicpub") or d.get("topicPub") or "") == str(topic):
                return d
        return None

    def add_listener(self, device_id: str, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.setdefault(device_id, set()).add(listener)

    def remove_listener(self, device_id: str, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.get(device_id, set()).discard(listener)

    def handle_device_message(self, device: dict[str, Any], data: dict[str, Any]) -> None:
        did = str(device.get("id"))
        state = self.device_states.setdefault(did, {})
        action = data.get("sdr")

        # APK protocol: 100/105 asks Wi-Fi info; the APK then asks 102 (ESP)
        # and 103 (Bluetooth) so it can display firmware/hardware details.
        if action in (100, 105):
            if data.get("ssid") not in (None, ""):
                state["wifi_ssid"] = str(data.get("ssid"))
            self.hass.async_create_task(self._request_device_info_commands(did))

        if action == 102:
            espver = data.get("espver")
            if isinstance(espver, str):
                try:
                    espver = json.loads(espver)
                except (TypeError, ValueError):
                    espver = None
            if isinstance(espver, dict):
                state["esp_version"] = espver
                hw = espver.get("hw")
                if isinstance(hw, dict):
                    value = hw.get("ver") or hw.get("build")
                    if value not in (None, ""):
                        state["hardware_version"] = str(value)
                sw = espver.get("sw")
                if isinstance(sw, dict):
                    value = sw.get("build") or sw.get("ver")
                    if value not in (None, ""):
                        state["esp_software_version"] = str(value)

            fw_extra = data.get("fw_extra")
            if isinstance(fw_extra, str):
                try:
                    fw_extra = json.loads(fw_extra)
                except (TypeError, ValueError):
                    fw_extra = None
            if isinstance(fw_extra, dict):
                state["fw_extra"] = fw_extra
                hw = fw_extra.get("hw")
                if isinstance(hw, dict):
                    value = hw.get("ver") or hw.get("build")
                    if value not in (None, ""):
                        state["hardware_version"] = str(value)

        if action == 103:
            blever = data.get("blever")
            if isinstance(blever, str):
                try:
                    blever = json.loads(blever)
                except (TypeError, ValueError):
                    blever = None
            if isinstance(blever, dict):
                state["ble_version_info"] = blever
                sw = blever.get("sw")
                if isinstance(sw, dict):
                    value = sw.get("build") or sw.get("ver")
                    if value not in (None, ""):
                        state["bluetooth_version"] = str(value)
                hw = blever.get("hw")
                if isinstance(hw, dict) and state.get("hardware_version") in (None, ""):
                    value = hw.get("ver") or hw.get("build")
                    if value not in (None, ""):
                        state["hardware_version"] = str(value)
            if state.get("bluetooth_version") in (None, "") and data.get("ver") not in (None, ""):
                state["bluetooth_version"] = str(data.get("ver"))

        if action == 4:
            state["locked"] = True
        elif action in (5, 3):
            state["locked"] = False
        if action == 9:
            state["locked"] = data.get("stt") == 4 or data.get("val") == 4
        if data.get("pcn") is not None:
            try:
                state["position"] = max(0, min(100, int(data.get("pcn"))))
            except (TypeError, ValueError):
                pass

        if data.get("pcnslot") is not None:
            try:
                state["cleft_position"] = max(0, min(100, int(data.get("pcnslot"))))
            except (TypeError, ValueError):
                pass
        if action == 1:
            state["position"] = 100
        elif action == 2:
            state["position"] = 0
        state["available"] = True
        for listener in list(self._listeners.get(did, set())):
            try:
                listener(state)
            except Exception as err:
                _LOGGER.debug("State listener failed: %s", err)

    async def _request_device_info_commands(self, device_id: str) -> None:
        await self._send_command(device_id, 102)
        await self._send_command(device_id, 103)

    def _request_all_status(self) -> None:
        async def _run():
            for did in list(self.devices):
                await self.request_status(did)
        self.hass.async_create_task(_run())

    def _mqtt_connected_changed(self, connected: bool) -> None:
        for did, listeners in self._listeners.items():
            state = self.device_states.setdefault(did, {})
            state["available"] = bool(connected)
            for listener in list(listeners):
                listener(state)

    async def _send_command(self, device_id: str, action: int) -> bool:
        device = self.devices.get(str(device_id))
        if not device:
            _LOGGER.error("Door %s is not present in Cloud device list", device_id)
            return False
        payload: dict[str, Any] = {"sdr": action, "src": 1}
        if self.user_id is not None:
            try:
                payload["u"] = int(self.user_id)
            except ValueError:
                payload["u"] = self.user_id
        return await self.mqtt.publish_command(device, json.dumps(payload, separators=(",", ":")))

    async def control_device(self, device_id: str, command: str, parameters: dict[str, Any] | None = None) -> bool:
        action = {"open": 1, "close": 2, "stop": 3, "lock": 4, "unlock": 5}.get(command)
        return await self._send_command(device_id, action) if action is not None else False

    async def request_status(self, device_id: str) -> bool:
        ok = await self._send_command(device_id, 9)
        await self._send_command(device_id, 100)
        return ok

    async def async_refresh(self) -> None:
        try:
            await self.get_devices()
            if self.mqtt.connected:
                for device_id in list(self.devices):
                    await self.request_status(device_id)
        except (ConfigEntryAuthFailed, ConfigEntryNotReady) as err:
            _LOGGER.warning("Hunonic Cloud refresh failed: %s", err)
        except Exception as err:
            _LOGGER.warning("Hunonic Cloud refresh failed: %s", err)

    async def start(self) -> None:
        await self.fetch_mqtt_server()
        if not self.mqtt_server or not self.mqtt_server.get("server"):
            raise ConfigEntryNotReady("Hunonic MQTT server could not be discovered")
        if not await self.mqtt.start():
            raise ConfigEntryNotReady("Hunonic MQTT connection could not be started")
        self._unsub_refresh = async_track_time_interval(self.hass, self._scheduled_refresh, timedelta(seconds=30))

    async def _scheduled_refresh(self, _now) -> None:
        await self.async_refresh()

    async def stop(self) -> None:
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        await self.mqtt.stop()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = HunonicAPIClient(
        hass, session,
        entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
        entry.data.get("api_host", DEFAULT_API_HOST),
        entry.data.get("api_port", DEFAULT_API_PORT),
    )
    if not await client.authenticate():
        raise ConfigEntryAuthFailed("Invalid Hunonic phone/password or API signature")
    await client.get_devices()
    if not client.devices:
        raise ConfigEntryNotReady("Cloud login succeeded, but no ROL-ROI door was found")
    await client.start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"client": client}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data:
        await data["client"].stop()
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
