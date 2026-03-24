import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, ATTR_POSITION

from .const import DOMAIN
from .client import (
    VitreaClient, KeyStatusResponse,
    KEY_ON, KEY_OFF,
    KEY_TYPE_BLIND, KEY_TYPE_BLIND_MW,
)

BLIND_TYPES = {KEY_TYPE_BLIND, KEY_TYPE_BLIND_MW}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    devices = data["devices"]
    entities = [
        VitreaCover(client, device, key)
        for device in devices
        for key in device["keys"]
        if key["type"] in BLIND_TYPES
    ]
    async_add_entities(entities)


class VitreaCover(CoverEntity):
    def __init__(self, client: VitreaClient, device: dict, key: dict) -> None:
        self._client = client
        self._node_id = device["node_id"]
        self._key_id = key["id"]
        self._position = 0
        self._attr_unique_id = f"vitrea_{device['node_id']}_{key['id']}"
        self._attr_name = key.get("name") or f"{device.get('room_name', '')} Key {key['id']}"
        self._room_name = device.get("room_name", "")
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION
        )
        name_str = key.get("name", "")
        if re.match(r"^N\d+-\d+$", name_str) or "Pair" in name_str or name_str.endswith(" MW"):
            self._attr_entity_registry_enabled_default = False

    @property
    def is_closed(self) -> bool:
        return self._position == 0

    @property
    def current_cover_position(self) -> int:
        return self._position

    async def async_open_cover(self, **kwargs) -> None:
        await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, 100)
        self._position = 100
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs) -> None:
        await self._client.toggle_key(self._node_id, self._key_id, KEY_OFF, 0)
        self._position = 0
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs[ATTR_POSITION]
        await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, position)
        self._position = position
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.on_key_status(self._handle_status_update)

    @callback
    def _handle_status_update(self, status: KeyStatusResponse) -> None:
        if status.node_id == self._node_id and status.key_id == self._key_id:
            self._position = status.power
            self.async_write_ha_state()
