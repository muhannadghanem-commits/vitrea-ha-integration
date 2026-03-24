import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .const import DOMAIN, PLATFORMS
from .client import VitreaClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = VitreaClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    await asyncio.sleep(1)  # Allow VBox Pro to release config flow connection
    await client.connect()
    result = await client.discover_devices()
    devices = result["devices"]

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "devices": devices,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Assign entities to existing HA areas (only if not already assigned)
    try:
        ent_reg = er.async_get(hass)
        area_reg = ar.async_get(hass)
        # Build area name → area_id lookup from existing HA areas
        area_lookup = {}
        for area in area_reg.async_list_areas():
            area_lookup[area.name.lower()] = area.id
        # Build unique_id → room_name mapping
        for dev in devices:
            rname = dev.get("room_name", "")
            if not rname:
                continue
            for key in dev.get("keys", []):
                uid = f"vitrea_{dev['node_id']}_{key['id']}"
                area_id = area_lookup.get(rname.lower())
                if not area_id:
                    continue
                for platform in PLATFORMS:
                    entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, uid)
                    if entity_id:
                        ent = ent_reg.async_get(entity_id)
                        if ent and not ent.area_id:
                            ent_reg.async_update_entity(entity_id, area_id=area_id)
    except Exception:
        _LOGGER.warning("Failed to assign entity areas", exc_info=True)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].disconnect()
    return unload_ok
