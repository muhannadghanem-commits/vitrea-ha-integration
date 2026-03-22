from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .client import (
    VitreaClient,
    KeyStatusResponse,
    KEY_ON,
    KEY_OFF,
    KEY_TYPE_TOGGLE,
    KEY_TYPE_DIMMER,
    KEY_TYPE_DIMMER_MW,
)

LIGHT_KEY_TYPES = {KEY_TYPE_TOGGLE, KEY_TYPE_DIMMER, KEY_TYPE_DIMMER_MW}
DIMMER_KEY_TYPES = {KEY_TYPE_DIMMER, KEY_TYPE_DIMMER_MW}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    devices = data["devices"]
    entities = []
    for device in devices:
        for key in device["keys"]:
            if key["type"] in LIGHT_KEY_TYPES:
                entities.append(VitreaLight(client, device, key))
    async_add_entities(entities)


class VitreaLight(LightEntity):
    def __init__(self, client: VitreaClient, device: dict, key: dict) -> None:
        self._client = client
        self._node_id = device["node_id"]
        self._key_id = key["id"]
        self._key_type = key["type"]
        self._is_on = False
        self._brightness = 0
        self._attr_unique_id = f"vitrea_{device['node_id']}_{key['id']}"
        self._attr_has_entity_name = True
        self._attr_name = key.get("name") or f"{device.get('room_name', '')} Key {key['id']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"vitrea_room_{device['room_id']}")},
            name=device.get("room_name", f"Vitrea Room {device['room_id']}"),
            manufacturer="Vitrea",
            suggested_area=device.get("room_name", ""),
        )

    @property
    def color_mode(self) -> ColorMode:
        if self._key_type in DIMMER_KEY_TYPES:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        return {self.color_mode}

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return self._brightness

    async def async_turn_on(self, **kwargs) -> None:
        if self._key_type in DIMMER_KEY_TYPES and ATTR_BRIGHTNESS in kwargs:
            dimmer = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, dimmer)
            self._brightness = kwargs[ATTR_BRIGHTNESS]
        elif self._key_type in DIMMER_KEY_TYPES:
            await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, 100)
            self._brightness = 255
        else:
            await self._client.toggle_key(self._node_id, self._key_id, KEY_ON, 100)
            self._brightness = 255
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self._client.toggle_key(self._node_id, self._key_id, KEY_OFF, 0)
        self._is_on = False
        self._brightness = 0
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.on_key_status(self._handle_status_update)

    @callback
    def _handle_status_update(self, status: KeyStatusResponse) -> None:
        if status.node_id != self._node_id or status.key_id != self._key_id:
            return
        self._is_on = status.is_on
        if self._key_type in DIMMER_KEY_TYPES:
            self._brightness = round(status.power * 255 / 100)
        else:
            self._brightness = 255 if status.is_on else 0
        self.async_write_ha_state()
