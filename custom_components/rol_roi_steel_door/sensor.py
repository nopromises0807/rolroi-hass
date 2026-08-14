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

    entities = []

    for device_id, info in client.devices.items():
        # Cửa mở %
        entities.append(
            RolRoiDoorSensor(
                client,
                device_id,
                info,
            )
        )

        # Ô thoáng %
        entities.append(
            RolRoiCleftSensor(
                client,
                device_id,
                info,
            )
        )

    async_add_entities(entities)


class RolRoiDoorSensor(SensorEntity):
    """Cảm biến % cửa mở."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:garage-variant"
    _attr_has_entity_name = True

    def __init__(
        self,
        client: HunonicAPIClient,
        device_id: str,
        info: dict[str, Any],
    ) -> None:
        self._client = client
        self._device_id = device_id
        self._info = info

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
        if "position" in state:
            self._value = state["position"]
            self._available = True

        if "available" in state:
            self._available = bool(state["available"])

        self.async_write_ha_state()


class RolRoiCleftSensor(SensorEntity):
    """Cảm biến % ô thoáng."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:window-shutter-open"
    _attr_has_entity_name = True

    def __init__(
        self,
        client: HunonicAPIClient,
        device_id: str,
        info: dict[str, Any],
    ) -> None:
        self._client = client
        self._device_id = device_id
        self._info = info

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
        if "cleft_position" in state:
            self._value = state["cleft_position"]
            self._available = True

        if "available" in state:
            self._available = bool(state["available"])

        self.async_write_ha_state()
