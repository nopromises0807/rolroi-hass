from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    CoverDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, HunonicAPIClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: HunonicAPIClient = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = [
        HunonicDoorCover(client, did, info)
        for did, info in client.devices.items()
    ]
    async_add_entities(entities)
    hass.data.setdefault(DOMAIN, {}).setdefault("cover_entities", {}).update(
        {entity._device_id: entity for entity in entities}
    )


class HunonicDoorCover(CoverEntity):
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_assumed_state = True
    # IMPORTANT: capabilities are static. Changing supported_features on every
    # lock/state update triggers HA's "updating its capabilities too often".
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
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
        self._attr_name = "Door"
        self._attr_unique_id = f"rol_roi_cover_{device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": info.get("name", f"ROL-ROI Door {device_id}"),
            "manufacturer": "Author: Nguyen Thang",
            "model": info.get("model", "ROL-ROI Steel Door"),
        }
        self._attr_current_cover_position = None
        self._main_position: int | None = None
        self._cleft_position: int | None = None
        self._is_locked = False
        self._attr_is_closed = None
        self._attr_available = False
        self._attr_is_opening = False
        self._attr_is_closing = False
        client.add_listener(device_id, self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_listener(self._device_id, self._state_changed)
        registry = self.hass.data.get(DOMAIN, {}).get("cover_entities", {})
        registry.pop(self._device_id, None)
        await super().async_will_remove_from_hass()

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        # Entity may already have been removed while an MQTT callback is queued.
        if self.hass is None:
            return

        main_position = self._main_position
        if "position" in state:
            try:
                main_position = max(0, min(100, int(state["position"])))
                self._main_position = main_position
            except (TypeError, ValueError):
                pass

        if "cleft_position" in state:
            try:
                self._cleft_position = max(
                    0, min(100, int(state["cleft_position"]))
                )
            except (TypeError, ValueError):
                pass

        if main_position is not None:
            effective_position = (
                main_position
                if self._cleft_position is None
                else max(main_position, self._cleft_position)
            )
            self._attr_current_cover_position = effective_position
            self._attr_is_closed = (
                main_position == 0
                if self._cleft_position is None
                else main_position == 0 and self._cleft_position == 0
            )

        if "available" in state:
            self._attr_available = bool(state["available"])

        if self._main_position is not None:
            if self._cleft_position is None:
                self._attr_name = f"Door — Cửa {self._main_position}%"
            else:
                self._attr_name = (
                    f"Door — Cửa {self._main_position}% | "
                    f"Ô thoáng {self._cleft_position}%"
                )

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._main_position is not None:
            attrs["door_open_percent"] = self._main_position
        if self._cleft_position is not None:
            attrs["cleft_open_percent"] = self._cleft_position
        if self._attr_current_cover_position is not None:
            attrs["effective_position"] = self._attr_current_cover_position
        attrs["locked"] = self._is_locked
        return attrs

    def set_locked(self, locked: bool) -> None:
        # Capabilities remain static to avoid HA capability-churn warnings.
        # Commands are still blocked in the action methods below.
        self._is_locked = bool(locked)
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        return None

    @property
    def state(self) -> str | None:
        main = self._main_position
        cleft = self._cleft_position
        if main is None:
            return None
        if cleft is None:
            return f"Cửa {main}%"
        return f"Cửa {main}% | Ô thoáng {cleft}%"

    async def async_open_cover(self, **kwargs: Any) -> None:
        if self._is_locked:
            _LOGGER.debug("Ignoring cover command while locked: %s", self._device_id)
            return
        self._attr_is_opening = True
        self.async_write_ha_state()
        ok = await self._client.control_device(self._device_id, "open")
        self._attr_is_opening = False
        if ok:
            self._main_position = 100
            self._attr_current_cover_position = (
                100 if self._cleft_position is None
                else max(100, self._cleft_position)
            )
            self._attr_is_closed = False
            self._attr_available = True
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        if self._is_locked:
            _LOGGER.debug("Ignoring cover command while locked: %s", self._device_id)
            return
        self._attr_is_closing = True
        self.async_write_ha_state()
        ok = await self._client.control_device(self._device_id, "close")
        self._attr_is_closing = False
        if ok:
            self._main_position = 0
            self._attr_current_cover_position = (
                0 if self._cleft_position is None
                else max(0, self._cleft_position)
            )
            self._attr_available = True
            self._attr_is_closed = (
                self._main_position == 0 and self._cleft_position == 0
                if self._cleft_position is not None
                else True
            )
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        if self._is_locked:
            _LOGGER.debug("Ignoring cover command while locked: %s", self._device_id)
            return
        ok = await self._client.control_device(self._device_id, "stop")
        self._attr_is_opening = False
        self._attr_is_closing = False
        if ok:
            self._attr_available = True
        self.async_write_ha_state()

    async def async_update(self) -> None:
        if not self._is_locked:
            await self._client.request_status(self._device_id)
