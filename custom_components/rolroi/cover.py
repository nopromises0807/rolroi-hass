from __future__ import annotations

import logging

from typing import Any
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, CoverDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import DOMAIN, HunonicAPIClient


_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    client: HunonicAPIClient = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([HunonicDoorCover(client, did, info) for did, info in client.devices.items()])

class HunonicDoorCover(CoverEntity):
    # Use SHUTTER so Home Assistant displays the cover actions as UP/DOWN arrows.
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_assumed_state = True
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    _attr_has_entity_name = True

    def __init__(self, client: HunonicAPIClient, device_id: str, info: dict[str, Any]) -> None:
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

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        main_position = getattr(self, "_main_position", None)
        if "position" in state:
            main_position = max(0, min(100, int(state["position"])))
            self._main_position = main_position

        self._cleft_position = state.get(
            "cleft_position",
            getattr(self, "_cleft_position", None),
        )

        # Home Assistant's cover UI uses the cover position to decide whether
        # the DOWN/CLOSE action is available. For advanced ROL-ROI doors,
        # pcnslot is a second opening dimension, so pcn==0 alone must not make
        # the cover look fully closed. Use the larger of the two percentages
        # as the effective cover position while retaining both raw values in
        # attributes.
        if main_position is not None:
            if self._cleft_position is None:
                effective_position = main_position
            else:
                effective_position = max(main_position, self._cleft_position)
            self._attr_current_cover_position = effective_position

            if self._cleft_position is None:
                self._attr_is_closed = main_position == 0
            else:
                self._attr_is_closed = (
                    main_position == 0 and self._cleft_position == 0
                )

        if "available" in state:
            self._attr_available = bool(state["available"])

        # Show both dimensions directly in the entity name used by the
        # standard HA cover control UI.
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
        attrs = {}
        if getattr(self, "_main_position", None) is not None:
            attrs["door_open_percent"] = self._main_position
        if self._cleft_position is not None:
            attrs["cleft_open_percent"] = self._cleft_position
        if self._attr_current_cover_position is not None:
            attrs["effective_position"] = self._attr_current_cover_position
        return attrs

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Hide UP/DOWN/STOP while the door is locked."""
        if self._is_locked:
            return CoverEntityFeature(0)
        return (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )

    def set_locked(self, locked: bool) -> None:
        """Synchronize lock state from the Lock entity / MQTT."""
        self._is_locked = bool(locked)
        self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        """Hide HA's automatic ' · NN%' suffix in the standard UI."""
        return None

    @property
    def state(self) -> str | None:
        """Replace HA's default 'Open · N%' text with both door percentages."""
        main = getattr(self, "_main_position", None)
        cleft = getattr(self, "_cleft_position", None)

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
            if self._cleft_position is None:
                self._attr_current_cover_position = 100
            else:
                self._attr_current_cover_position = max(100, self._cleft_position)
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
            if self._cleft_position is None:
                self._attr_current_cover_position = 0
            else:
                self._attr_current_cover_position = max(0, self._cleft_position)
            self._attr_available = True
            if self._cleft_position is not None:
                self._attr_is_closed = (
                    self._main_position == 0 and self._cleft_position == 0
                )
            else:
                self._attr_is_closed = None
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
        await self._client.request_status(self._device_id)
