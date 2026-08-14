from __future__ import annotations

import json
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, HunonicAPIClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    entities: list[SensorEntity] = []

    for device_id, info in client.devices.items():
        entities.extend(
            [
                RolRoiDoorSensor(client, device_id, info),
                RolRoiCleftSensor(client, device_id, info),
                RolRoiWifiSensor(client, device_id, info),
                RolRoiBluetoothVersionSensor(client, device_id, info),
                RolRoiHardwareVersionSensor(client, device_id, info),
            ]
        )

    async_add_entities(entities)


class RolRoiDoorSensor(SensorEntity):
    """Cảm biến % cửa mở."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:garage-variant"
    _attr_has_entity_name = True

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_name = "Cửa"
        self._attr_unique_id = f"rol_roi_door_{device_id}"
        self._value: int | None = None
        self._available = False
        self._attr_device_info = _device_info(device_id, info)
        client.add_listener(device_id, self._state_changed)

    @property
    def native_value(self) -> int | None:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if "position" in state:
            self._value = state["position"]
        if "available" in state:
            self._available = bool(state["available"])
        self.async_write_ha_state()


class RolRoiCleftSensor(SensorEntity):
    """Cảm biến % ô thoáng."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:window-shutter-open"
    _attr_has_entity_name = True

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_name = "Ô thoáng"
        self._attr_unique_id = f"rol_roi_cleft_{device_id}"
        self._value: int | None = None
        self._available = False
        self._attr_device_info = _device_info(device_id, info)
        client.add_listener(device_id, self._state_changed)

    @property
    def native_value(self) -> int | None:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if "cleft_position" in state:
            self._value = state["cleft_position"]
        if "available" in state:
            self._available = bool(state["available"])
        self.async_write_ha_state()


def _device_info(device_id: str, info: dict[str, Any]) -> dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": info.get("name", f"ROL-ROI Door {device_id}"),
        "manufacturer": "Author: Nguyen Thang",
        "model": info.get("model", "ROL-ROI Steel Door"),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _text(value: Any) -> str | None:
    return None if value in (None, "", "null", "None") else str(value)


class _RolRoiInfoSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        client: HunonicAPIClient,
        device_id: str,
        info: dict[str, Any],
        name: str,
        unique_suffix: str,
        icon: str,
    ) -> None:
        self._client = client
        self._device_id = device_id
        self._info = info
        self._attr_name = name
        self._attr_unique_id = f"rol_roi_{unique_suffix}_{device_id}"
        self._attr_icon = icon
        self._attr_device_info = _device_info(device_id, info)
        self._available = False
        client.add_listener(device_id, self._state_changed)

    @property
    def available(self) -> bool:
        return self._available

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if "available" in state:
            self._available = bool(state["available"])
        self.async_write_ha_state()

    def _state(self) -> dict[str, Any]:
        return self._client.device_states.get(str(self._device_id), {})

    def _info_now(self) -> dict[str, Any]:
        return self._client.devices.get(str(self._device_id), self._info)


class RolRoiWifiSensor(_RolRoiInfoSensor):
    """Tên Wi-Fi mà cửa ROL-ROI đang kết nối."""

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
        super().__init__(client, device_id, info, "Wi-Fi", "wifi", "mdi:wifi")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        info = self._info_now()
        return _text(state.get("wifi_ssid") or info.get("ssid") or info.get("ssidWifi"))


class RolRoiBluetoothVersionSensor(_RolRoiInfoSensor):
    """Phiên bản Bluetooth của cửa."""

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
        super().__init__(client, device_id, info, "Phiên bản Bluetooth", "bluetooth_version", "mdi:bluetooth")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        info = self._info_now()

        if state.get("bluetooth_version") not in (None, ""):
            return str(state["bluetooth_version"])

        blever = _json_object(info.get("blever"))
        ble_sw = _json_object(blever.get("sw"))
        return _text(
            info.get("verBLE")
            or ble_sw.get("build")
            or ble_sw.get("ver")
            or info.get("bluetooth_version")
        )


class RolRoiHardwareVersionSensor(_RolRoiInfoSensor):
    """Phiên bản phần cứng của cửa."""

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
        super().__init__(client, device_id, info, "Phiên bản phần cứng", "hardware_version", "mdi:chip")

    @property
    def native_value(self) -> str | None:
        info = self._info_now()

        # APK đọc hardware version từ fw_extra.hw.ver.
        fw_extra = _json_object(info.get("fw_extra"))
        hw = _json_object(fw_extra.get("hw"))
        value = _text(hw.get("ver"))
        if value:
            return value

        return _text(
            info.get("hardwareVersion")
            or info.get("hardware_version")
            or info.get("hw_version")
        )
