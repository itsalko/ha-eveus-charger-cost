"""Binary sensors: ground check and charging state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EveusConfigEntry
from .api import as_bool, as_float
from .entity import EveusEntity

GROUND = BinarySensorEntityDescription(
    key="ground",
    translation_key="ground",
    device_class=BinarySensorDeviceClass.PROBLEM,
)
CHARGING = BinarySensorEntityDescription(
    key="charging",
    translation_key="charging",
    device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EveusGround(coordinator, GROUND),
            EveusCharging(coordinator, CHARGING),
        ]
    )


class EveusGround(EveusEntity, BinarySensorEntity):
    """On when the ground connection is missing."""

    @property
    def is_on(self) -> bool:
        return not as_bool(self.device_data.get("ground"))


class EveusCharging(EveusEntity, BinarySensorEntity):
    """On while the car is actually being charged."""

    @property
    def is_on(self) -> bool:
        return as_float(self.device_data.get("state")) == 4
