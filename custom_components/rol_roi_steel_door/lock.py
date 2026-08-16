from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, HunonicAPIClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = [
        HunonicDoorLock(hass, client, did, info)
        for did, info in client.devices.items()
    ]
    async_add_entities(entities)


class HunonicDoorLock(LockEntity):
    _attr_supported_features = LockEntityFeature.OPEN
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        client: HunonicAPIClient,
        device_id: str,
        info: dict[str, Any],
    ) -> None:
        self._hass = hass
        self._client = client
        self._device_id = device_id
        self._info = info
        self._attr_name = "Lock"
        self._attr_unique_id = f"rol_roi_lock_{device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": info.get("name", f"ROL-ROI Door {device_id}"),
            "manufacturer": "Author: Nguyen Thang",
            "model": info.get("model", "ROL-ROI Steel Door"),
        }
        self._attr_is_locked = None
        self._attr_available = False
        client.add_listener(device_id, self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_listener(self._device_id, self._state_changed)
        await super().async_will_remove_from_hass()

    @callback
    def _state_changed(self, state: dict[str, Any]) -> None:
        if self.hass is None:
            return
        if "locked" in state:
            self._attr_is_locked = bool(state["locked"])
            self._notify_cover_lock(self._attr_is_locked)
        if "available" in state:
            self._attr_available = bool(state["available"])
        self.async_write_ha_state()

    def _notify_cover_lock(self, locked: bool) -> None:
        covers = self._hass.data.get(DOMAIN, {}).get("cover_entities", {})
        cover = covers.get(self._device_id)
        if cover is not None:
            cover.set_locked(locked)

    async def async_lock(self, **kwargs: Any) -> None:
        if await self._client.control_device(self._device_id, "lock"):
            self._attr_is_locked = True
            self._attr_available = True
            self._notify_cover_lock(True)
            self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        if await self._client.control_device(self._device_id, "unlock"):
            self._attr_is_locked = False
            self._attr_available = True
            self._notify_cover_lock(False)
            self.async_write_ha_state()

    async def async_open(self, **kwargs: Any) -> None:
        if await self._client.control_device(self._device_id, "open"):
            self._attr_is_locked = False
            self._attr_available = True
            self._notify_cover_lock(False)
            self.async_write_ha_state()

    async def async_update(self) -> None:
        await self._client.request_status(self._device_id)
