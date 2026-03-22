import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import area_registry as ar, floor_registry as fr

from .const import DOMAIN, PLATFORMS, FLOOR_NAMES
from .client import VitreaClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = VitreaClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    await client.connect()
    devices = await client.discover_devices()

    try:
        floor_reg = fr.async_get(hass)
        area_reg = ar.async_get(hass)

        # Detect duplicate room names across floors
        name_floors = {}
        for dev in devices:
            rname = dev.get("room_name", "")
            fid = dev.get("floor_id", 0)
            if rname:
                name_floors.setdefault(rname, set()).add(fid)
        dup_names = {n for n, fids in name_floors.items() if len(fids) > 1}

        floor_map = {}
        seen_rooms = {}
        for dev in devices:
            fid = dev.get("floor_id", 0)
            if fid not in floor_map:
                fname = FLOOR_NAMES.get(fid, f"Floor {fid}")
                floor_entry = floor_reg.async_get_floor_by_name(fname)
                if not floor_entry:
                    try:
                        floor_entry = floor_reg.async_create(fname, level=fid)
                    except ValueError:
                        floor_entry = floor_reg.async_get_floor_by_name(fname)
                if floor_entry:
                    floor_map[fid] = floor_entry.floor_id

            rid = dev.get("room_id", 0)
            rname = dev.get("room_name", "")
            if rname and rid not in seen_rooms and fid in floor_map:
                if rname in dup_names:
                    area_name = f"{FLOOR_NAMES.get(fid, f'Floor {fid}')} {rname}"
                else:
                    area_name = rname
                area_entry = area_reg.async_get_or_create(area_name)
                area_reg.async_update(area_entry.id, floor_id=floor_map[fid])
                dev["room_name"] = area_name
                seen_rooms[rid] = area_name

            # Update room_name for devices in already-seen rooms
            if rid in seen_rooms:
                dev["room_name"] = seen_rooms[rid]
    except Exception:
        _LOGGER.warning("Failed to create floor/area hierarchy", exc_info=True)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "devices": devices,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].disconnect()
    return unload_ok
