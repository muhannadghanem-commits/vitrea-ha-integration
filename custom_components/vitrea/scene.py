import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.scene import Scene

from .const import DOMAIN, KEY_TYPE_SCENARIO
from .client import VitreaClient, KEY_ON


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    devices = data["devices"]
    entities = []
    for device in devices:
        for key in device["keys"]:
            if key["type"] == KEY_TYPE_SCENARIO:
                entities.append(VitreaScene(client, device, key))
    async_add_entities(entities)


class VitreaScene(Scene):
    def __init__(self, client: VitreaClient, device: dict, key: dict) -> None:
        self._client = client
        self._node_id = device["node_id"]
        self._key_id = key["id"]
        self._attr_unique_id = f"vitrea_{device['node_id']}_{key['id']}"
        self._attr_name = key.get("name") or f"{device.get('room_name', '')} Key {key['id']}"
        self._room_name = device.get("room_name", "")
        name_str = key.get("name", "")
        if re.match(r"^N\d+-\d+$", name_str) or "Pair" in name_str or name_str.endswith(" MW"):
            self._attr_entity_registry_enabled_default = False

    async def async_activate(self, **kwargs) -> None:
        await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, 100)
