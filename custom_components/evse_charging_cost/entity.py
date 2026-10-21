"""Base entity for Eveus EV Charger + Cost."""

from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EveusCoordinator


class EveusEntity(CoordinatorEntity[EveusCoordinator]):
    """Entity bound to one charger."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: EveusCoordinator, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def device_info(self):
        """Return the charger device."""
        return self.coordinator.device_info

    @property
    def tracker(self):
        """Shortcut to the cost tracker."""
        return self.coordinator.tracker

    @property
    def device_data(self) -> dict:
        """Last data received from the charger."""
        return self.coordinator.data or {}
