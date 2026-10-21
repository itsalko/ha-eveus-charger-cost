"""Switches: enable charging, one-charge mode, adaptive mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EveusConfigEntry
from .api import as_bool
from .entity import EveusEntity


@dataclass(frozen=True, kw_only=True)
class EveusSwitchDescription(SwitchEntityDescription):
    """Describes one switch."""

    device_key: str
    # Some fields are inverted in the charger's firmware.
    invert: bool = False


SWITCHES: tuple[EveusSwitchDescription, ...] = (
    EveusSwitchDescription(
        key="charging_enabled",
        translation_key="charging_enabled",
        device_key="evseEnabled",
        icon="mdi:ev-station",
        # evseEnabled = 1 means the charger is stopped, so the switch reads and
        # writes the opposite of the raw value.
        invert=True,
    ),
    EveusSwitchDescription(
        key="one_charge",
        translation_key="one_charge",
        device_key="oneCharge",
        icon="mdi:numeric-1-circle-outline",
    ),
    EveusSwitchDescription(
        key="adaptive_mode",
        translation_key="adaptive_mode",
        device_key="aiMode",
        icon="mdi:auto-fix",
        entity_registry_enabled_default=False,
    ),
    EveusSwitchDescription(
        key="ground_control",
        translation_key="ground_control",
        device_key="groundCtrl",
        icon="mdi:power-plug",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create switches."""
    coordinator = entry.runtime_data
    async_add_entities(EveusSwitch(coordinator, d) for d in SWITCHES)


class EveusSwitch(EveusEntity, SwitchEntity):
    """Writes a 0/1 setting to the charger."""

    entity_description: EveusSwitchDescription

    @property
    def is_on(self) -> bool:
        raw = as_bool(self.device_data.get(self.entity_description.device_key))
        return not raw if self.entity_description.invert else raw

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(False)

    async def _write(self, state: bool) -> None:
        if self.entity_description.invert:
            state = not state
        await self.coordinator.async_write(
            self.entity_description.device_key, int(state)
        )
        self.async_write_ha_state()
