"""Buttons that reset the cost counters."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EveusConfigEntry
from .entity import EveusEntity

BUTTONS = (
    ButtonEntityDescription(
        key="new_session",
        translation_key="new_session",
        icon="mdi:ev-plug-type2",
    ),
    ButtonEntityDescription(
        key="end_session",
        translation_key="end_session",
        icon="mdi:stop-circle-outline",
    ),
    ButtonEntityDescription(
        key="reapply_current",
        translation_key="reapply_current",
        icon="mdi:refresh-auto",
    ),
    ButtonEntityDescription(
        key="reset_counts",
        translation_key="reset_counts",
        icon="mdi:restart",
        entity_category=EntityCategory.CONFIG,
    ),
    ButtonEntityDescription(
        key="reset_totals",
        translation_key="reset_totals",
        icon="mdi:counter",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create buttons."""
    coordinator = entry.runtime_data
    async_add_entities(EveusButton(coordinator, d) for d in BUTTONS)


class EveusButton(EveusEntity, ButtonEntity):
    """Manual control of the cost counters."""

    @property
    def available(self) -> bool:
        return True  # the counters work even if the charger is offline

    async def async_press(self) -> None:
        key = self.entity_description.key
        if key == "end_session":
            await self.coordinator.async_end_session()
        elif key == "reapply_current":
            await self.coordinator.async_reapply_current()
        elif key == "new_session":
            self.tracker.new_session()
        elif key == "reset_counts":
            self.tracker.reset_all()
        else:
            self.tracker.reset_totals()
