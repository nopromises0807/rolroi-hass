from __future__ import annotations

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
        # Existing v2.2.2 entities — IDs remain unchanged.
        entities.append(RolRoiDoorSensor(client, device_id, info))
        entities.append(RolRoiCleftSensor(client, device_id, info))

        # Device information restored as dedicated diagnostic sensors.
        entities.append(RolRoiInfoSensor(client, device_id, info, "wifi", "WiFi", "mdi:wifi"))
        entities.append(RolRoiInfoSensor(client, device_id, info, "bluetooth", "Bluetooth", "mdi:bluetooth"))
        entities.append(RolRoiInfoSensor(client, device_id, info, "hardware", "Phần cứng", "mdi:chip"))
        entities.append(RolRoiInfoSensor(client, device_id, info, "esp_software", "ESP software", "mdi:memory"))

    async_add_entities(entities)


class _BaseRolRoiSensor(SensorEntity):
    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_listener(self._device_id, self._state_changed)
        await super().async_will_remove_from_hass()

    def _safe_write(self) -> None:
        if self.hass is not None:
            self.async_write_ha_state()


class RolRoiDoorSensor(_BaseRolRoiSensor):
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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": info.get("name", f"ROL-ROI Door {device_id}"),
            "manufacturer": "Author: Nguyen Thang",
            "model": info.get("model", "ROL-ROI Steel Door"),
        }
        client.add_listener(device_id, self._state_changed)

    @property
    def native_value(self) -> int | None:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if self.hass is None:
            return
        if "position" in state:
            self._value = state["position"]
            self._available = True
        if "available" in state:
            self._available = bool(state["available"])
        self._safe_write()


class RolRoiCleftSensor(_BaseRolRoiSensor):
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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": info.get("name", f"ROL-ROI Door {device_id}"),
            "manufacturer": "Author: Nguyen Thang",
            "model": info.get("model", "ROL-ROI Steel Door"),
        }
        client.add_listener(device_id, self._state_changed)

    @property
    def native_value(self) -> int | None:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if self.hass is None:
            return
        if "cleft_position" in state:
            self._value = state["cleft_position"]
            self._available = True
        if "available" in state:
            self._available = bool(state["available"])
        self._safe_write()


class RolRoiInfoSensor(_BaseRolRoiSensor):
    """Diagnostic information returned by APK-exact MQTT sdr=100/102/103."""

    _attr_has_entity_name = True
    _attr_entity_category = "diagnostic"

    def __init__(
        self,
        client: HunonicAPIClient,
        device_id: str,
        info: dict[str, Any],
        key: str,
        name: str,
        icon: str,
    ) -> None:
        self._client = client
        self._device_id = device_id
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"rol_roi_info_{key}_{device_id}"
        self._attr_icon = icon
        self._value: str | None = None
        self._available = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": info.get("name", f"ROL-ROI Door {device_id}"),
            "manufacturer": "Author: Nguyen Thang",
            "model": info.get("model", "ROL-ROI Steel Door"),
        }
        client.add_listener(device_id, self._state_changed)

    @property
    def native_value(self) -> str | None:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    def _read_value(self, state: dict[str, Any]) -> Any:
        if self._key == "wifi":
            return state.get("wifi_ssid")
        if self._key == "bluetooth":
            return state.get("bluetooth_version")
        if self._key == "hardware":
            return state.get("hardware_version")
        if self._key == "esp_software":
            return state.get("esp_software_version")
        return None

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if self.hass is None:
            return
        value = self._read_value(state)
        if value not in (None, ""):
            self._value = str(value)
            self._available = True
        if "available" in state:
            self._available = bool(state["available"])
        self._safe_write()
