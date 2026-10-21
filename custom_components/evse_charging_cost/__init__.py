"""Eveus EV Charger with two-zone (day/night) cost tracking."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_when_setup

from .const import CONF_HOST, DOMAIN, STORAGE_VERSION
from .coordinator import EveusCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type EveusConfigEntry = ConfigEntry[EveusCoordinator]

CARD_FILE = "eveus-flow-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
CARD_VERSION = "2.13.0"
CARD_URL_VERSIONED = f"{CARD_URL}?v={CARD_VERSION}"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the Lovelace card that ships with the integration."""
    if hass.data.get(f"{DOMAIN}_card"):
        return
    hass.data[f"{DOMAIN}_card"] = True
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL,
                str(Path(__file__).parent / "www" / CARD_FILE),
                # Cache it: the URL carries the version, so updates still land.
                True,
            )
        ]
    )

    async def _register(_hass: HomeAssistant, _component: str) -> None:
        """Runs as soon as the frontend is ready (or right away if it is)."""
        if await _async_add_lovelace_resource(hass):
            # Lovelace waits for its own resources before it draws the
            # dashboard, so cards never race the module load.
            return
        add_extra_js_url(hass, CARD_URL_VERSIONED)
        _LOGGER.debug("Registered the Eveus card as an extra module")

    # The entry can be set up before the frontend is, so wait for it rather
    # than silently skipping the card.
    async_when_setup(hass, "frontend", _register)


async def _async_add_lovelace_resource(hass: HomeAssistant) -> bool:
    """Add (or update) the card in the Lovelace resource list.

    Only works with UI-managed dashboards; in YAML mode the list is read-only
    and the caller falls back to an extra module URL.
    """
    resources = getattr(hass.data.get("lovelace"), "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        return False
    try:
        await resources.async_get_info()
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] != CARD_URL:
                continue
            if item["url"] != CARD_URL_VERSIONED:
                await resources.async_update_item(
                    item["id"], {"url": CARD_URL_VERSIONED}
                )
                _LOGGER.info("Updated the Eveus card resource to %s", CARD_VERSION)
            return True
        await resources.async_create_item(
            {"res_type": "module", "url": CARD_URL_VERSIONED}
        )
        _LOGGER.info("Added the Eveus card to the Lovelace resources")
        return True
    except Exception as err:  # noqa: BLE001 - never block setup over a card
        _LOGGER.debug("Could not add the card as a Lovelace resource: %s", err)
        return False


async def async_setup_entry(hass: HomeAssistant, entry: EveusConfigEntry) -> bool:
    """Set up a charger from a config entry."""
    await _async_register_card(hass)

    coordinator = EveusCoordinator(hass, entry)
    await coordinator.tracker.async_start()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EveusConfigEntry) -> bool:
    """Unload a config entry and flush the counters to disk."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data.cancel_reapply()
        await entry.runtime_data.tracker.async_stop()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entries made by version 1.x pointed at another integration's sensors."""
    if entry.version == 1 and CONF_HOST not in {**entry.data, **entry.options}:
        _LOGGER.error(
            "This entry was created by version 1.x, which read the energy from "
            "another integration. Version 2 talks to the charger directly: "
            "please delete this entry and add the integration again with the "
            "charger's IP address"
        )
        return False
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete stored counters when the integration is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when connection settings or prices change."""
    await hass.config_entries.async_reload(entry.entry_id)
