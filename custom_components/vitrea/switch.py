import re
from typing import Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, CALLBACK_TYPE
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .client import (
    VitreaClient,
    KeyStatusResponse,
    KEY_ON,
    KEY_OFF,
    KEY_TYPE_TOGGLE,
)

MAX_TIMER_SECONDS = 7200  # 120 min
TIMER_INCREMENT = 1800  # 30 min


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    devices = data["devices"]
    entities = []
    for device in devices:
        for key in device["keys"]:
            if key["type"] == KEY_TYPE_TOGGLE and "boiler" in key.get("name", "").lower():
                entities.append(VitreaSwitch(client, device, key))
    async_add_entities(entities)


class VitreaSwitch(SwitchEntity):
    def __init__(self, client: VitreaClient, device: dict, key: dict) -> None:
        self._client = client
        self._node_id = device["node_id"]
        self._key_id = key["id"]
        self._is_on = False
        self._timer_remaining = 0
        self._timer_cancel: Optional[CALLBACK_TYPE] = None
        self._attr_unique_id = f"vitrea_{device['node_id']}_{key['id']}"
        self._attr_has_entity_name = True
        self._attr_name = key.get("name") or f"{device.get('room_name', '')} Key {key['id']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"vitrea_room_{device['room_id']}")},
            name=device.get("room_name", f"Vitrea Room {device['room_id']}"),
            manufacturer="Vitrea",
            suggested_area=device.get("room_name", ""),
        )
        name_str = key.get("name", "")
        if re.match(r"^N\d+-\d+$", name_str) or "Pair" in name_str:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict:
        return {"timer_remaining": self._timer_remaining}

    async def async_turn_on(self, **kwargs) -> None:
        self._timer_remaining = min(self._timer_remaining + TIMER_INCREMENT, MAX_TIMER_SECONDS)
        await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, 100)
        self._is_on = True
        self._schedule_auto_off()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
        self._timer_remaining = 0
        await self._client.toggle_key(self._node_id, self._key_id, KEY_OFF, 0)
        self._is_on = False
        self.async_write_ha_state()

    def _schedule_auto_off(self) -> None:
        if self._timer_cancel:
            self._timer_cancel()
        self._timer_cancel = async_call_later(
            self.hass, self._timer_remaining, self._auto_off_callback
        )

    async def _auto_off_callback(self, _now) -> None:
        self._timer_cancel = None
        self._timer_remaining = 0
        await self._client.toggle_key(self._node_id, self._key_id, KEY_OFF, 0)
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.on_key_status(self._handle_status_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None

    @callback
    def _handle_status_update(self, status: KeyStatusResponse) -> None:
        if status.node_id != self._node_id or status.key_id != self._key_id:
            return
        self._is_on = status.is_on
        if not status.is_on and self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
            self._timer_remaining = 0
        self.async_write_ha_state()
