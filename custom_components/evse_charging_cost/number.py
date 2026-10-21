"""Charging current limit."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EveusConfigEntry
from .api import as_float
from .const import MIN_CURRENT
from .entity import EveusEntity

CURRENT_LIMIT = NumberEntityDescription(
    key="current_limit",
    translation_key="current_limit",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_min_value=MIN_CURRENT,
    native_max_value=MIN_CURRENT,
    native_step=1,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the current limit control."""
    async_add_entities([EveusCurrentLimit(entry.runtime_data, CURRENT_LIMIT)])


class EveusCurrentLimit(EveusEntity, NumberEntity):
    """Sets ``currentSet`` on the charger."""

    @property
    def native_value(self) -> float | None:
        return as_float(self.device_data.get("currentSet"))

    @property
    def native_max_value(self) -> float:
        """The configured limit, never above what the charger is designed for."""
        design = as_float(self.device_data.get("curDesign"))
        limit = float(self.coordinator.max_current)
        return min(limit, design) if design else limit

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.cancel_reapply()
        await self.coordinator.async_write("currentSet", int(value))
