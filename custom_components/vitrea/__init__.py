import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .const import DOMAIN, PLATFORMS, POLL_INTERVAL
from .client import VitreaClient, KEY_TYPE_NOT_EXIST, KEY_TYPE_NOT_ACTIVE

_LOGGER = logging.getLogger(__name__)

SKIP_POLL_TYPES = {KEY_TYPE_NOT_EXIST, KEY_TYPE_NOT_ACTIVE, 12}  # skip inactive + scenes


async def _poll_loop(client, devices, stop_event):
    """Poll all active keys and fire push callbacks."""
    poll_keys = []
    for dev in devices:
        for key in dev.get("keys", []):
            if key["type"] not in SKIP_POLL_TYPES:
                poll_keys.append((dev["node_id"], key["id"]))
    _LOGGER.warning("Vitrea poll: %d keys to poll, %d callbacks registered", len(poll_keys), len(client._key_status_callbacks))
    while not stop_event.is_set():
        polled = 0
        errors = 0
        for node_id, key_id in poll_keys:
            if stop_event.is_set():
                break
            try:
                status = await client.get_key_status(node_id, key_id)
                for cb in client._key_status_callbacks:
                    cb(status)
                polled += 1
            except (Exception, asyncio.CancelledError):
                errors += 1
            await asyncio.sleep(0.05)  # 50ms between polls
        _LOGGER.warning("Vitrea poll cycle: %d polled, %d errors, %d callbacks", polled, errors, len(client._key_status_callbacks))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = VitreaClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    try:
        await asyncio.sleep(1)  # Allow VBox Pro to release config flow connection
        await client.connect()
        result = await client.discover_devices()
        devices = result["devices"]
    except Exception as err:
        _LOGGER.error("Vitrea: failed to connect: %s", err)
        raise ConfigEntryNotReady(f"Cannot connect to VBox Pro: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    stop_event = asyncio.Event()
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "devices": devices,
        "stop_event": stop_event,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start polling AFTER platforms register their callbacks
    poll_task = asyncio.ensure_future(_poll_loop(client, devices, stop_event))
    hass.data[DOMAIN][entry.entry_id]["poll_task"] = poll_task

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
        data["stop_event"].set()
        data["poll_task"].cancel()
        await data["client"].disconnect()
    return unload_ok
