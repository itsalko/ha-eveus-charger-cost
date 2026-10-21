"""Sensors: live charger readings and two-zone cost accounting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EveusConfigEntry
from .api import as_float
from .const import STATUS_MAP, ZONE_DAY, ZONE_NIGHT, ZONES
from .coordinator import EveusCoordinator
from .entity import EveusEntity


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _iso_to_dt(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


def _power_w(data: dict[str, Any]) -> float | None:
    """Charging power in watts.

    Firmware versions disagree about the unit of ``powerMeas``: some report
    watts, some kilowatts. A home charger never exceeds ~22 kW, so a value
    above 100 can only be watts.
    """
    raw = as_float(data.get("powerMeas"))
    if raw is not None:
        return raw if raw > 100 else raw * 1000
    power = 0.0
    for phase in (1, 2, 3):
        volt = as_float(data.get(f"voltMeas{phase}")) or 0
        cur = as_float(data.get(f"curMeas{phase}")) or 0
        power += volt * cur
    return power or None


def _status(data: dict[str, Any]) -> str | None:
    raw = as_float(data.get("state"))
    return STATUS_MAP.get(int(raw)) if raw is not None else None


def _timestamp(data: dict[str, Any]) -> datetime | None:
    raw = as_float(data.get("systemTime"))
    return datetime.fromtimestamp(int(raw), tz=UTC) if raw else None


def _previous_month(t, key: str) -> dict[str, Any]:
    prev = t.data.get("previous_month")
    if not prev:
        return {}
    return {"previous_month": prev["month"], f"previous_month_{key}": _r(prev[key])}


@dataclass(frozen=True, kw_only=True)
class EveusSensorDescription(SensorEntityDescription):
    """Describes one sensor."""

    value_fn: Callable[[EveusCoordinator], Any]
    attrs_fn: Callable[[EveusCoordinator], dict[str, Any]] = field(
        default=lambda _c: {}
    )
    unit_fn: Callable[[EveusCoordinator], str | None] | None = None
    last_reset_fn: Callable[[EveusCoordinator], datetime | None] | None = None
    phases: int = 1
    from_tracker: bool = False


def _device(key: str) -> Callable[[EveusCoordinator], float | None]:
    return lambda c: as_float((c.data or {}).get(key))


CHARGER_SENSORS: tuple[EveusSensorDescription, ...] = (
    EveusSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_MAP.values()),
        value_fn=lambda c: _status(c.data or {}),
        attrs_fn=lambda c: {"raw_state": (c.data or {}).get("state")},
    ),
    EveusSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda c: _r(_power_w(c.data or {})),
    ),
    EveusSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=_device("sessionEnergy"),
    ),
    EveusSensorDescription(
        key="total_energy",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_device("totalEnergy"),
    ),
    EveusSensorDescription(
        key="session_time",
        translation_key="session_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=_device("sessionTime"),
    ),
    EveusSensorDescription(
        key="current_set",
        translation_key="current_set",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_device("currentSet"),
    ),
    EveusSensorDescription(
        key="box_temperature",
        translation_key="box_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_fn=_device("temperature1"),
    ),
    EveusSensorDescription(
        key="plug_temperature",
        translation_key="plug_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_fn=_device("temperature2"),
    ),
    EveusSensorDescription(
        key="leakage",
        translation_key="leakage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mA",
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_device("leakValue"),
    ),
    EveusSensorDescription(
        key="charger_time",
        translation_key="charger_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _timestamp(c.data or {}),
    ),
)

PHASE_SENSORS: tuple[EveusSensorDescription, ...] = tuple(
    sensor
    for phase in (1, 2, 3)
    for sensor in (
        EveusSensorDescription(
            key=f"voltage_l{phase}",
            translation_key=f"voltage_l{phase}",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            suggested_display_precision=0,
            value_fn=_device(f"voltMeas{phase}"),
            phases=phase,
        ),
        EveusSensorDescription(
            key=f"current_l{phase}",
            translation_key=f"current_l{phase}",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            suggested_display_precision=1,
            value_fn=_device(f"curMeas{phase}"),
            phases=phase,
        ),
    )
)

COST_SENSORS: tuple[EveusSensorDescription, ...] = (
    EveusSensorDescription(
        key="current_tariff",
        translation_key="current_tariff",
        device_class=SensorDeviceClass.ENUM,
        options=list(ZONES),
        value_fn=lambda c: c.tracker.current_zone,
        attrs_fn=lambda c: {
            "price": c.tracker.current_price,
            "day_price": c.tracker.prices[ZONE_DAY],
            "night_price": c.tracker.prices[ZONE_NIGHT],
            "night_start": c.tracker.night_start.isoformat(),
            "night_end": c.tracker.night_end.isoformat(),
            "next_change": c.tracker.next_zone_change().isoformat(),
        },
    ),
    EveusSensorDescription(
        key="current_price",
        translation_key="current_price",
        suggested_display_precision=2,
        value_fn=lambda c: c.tracker.current_price,
        unit_fn=lambda c: f"{c.tracker.currency}/{UnitOfEnergy.KILO_WATT_HOUR}",
    ),
    EveusSensorDescription(
        key="session_cost",
        translation_key="session_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda c: _r(c.tracker.session("cost")),
        unit_fn=lambda c: c.tracker.currency,
        last_reset_fn=lambda c: _iso_to_dt(c.tracker.data.get("session_started")),
        attrs_fn=lambda c: {
            "energy_kwh": _r(c.tracker.session("energy")),
            "day_energy_kwh": _r(c.tracker.session("energy", ZONE_DAY)),
            "night_energy_kwh": _r(c.tracker.session("energy", ZONE_NIGHT)),
            "day_cost": _r(c.tracker.session("cost", ZONE_DAY)),
            "night_cost": _r(c.tracker.session("cost", ZONE_NIGHT)),
            "average_price": (
                _r(c.tracker.session("cost") / c.tracker.session("energy"))
                if c.tracker.session("energy") > 0
                else None
            ),
            "started": c.tracker.data.get("session_started"),
        },
    ),
    EveusSensorDescription(
        key="last_session_cost",
        translation_key="last_session_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda c: (
            _r(c.tracker.data["previous_session"]["cost"])
            if c.tracker.data.get("previous_session")
            else None
        ),
        unit_fn=lambda c: c.tracker.currency,
        attrs_fn=lambda c: (
            {
                k: (_r(v) if isinstance(v, float) else v)
                for k, v in c.tracker.data["previous_session"].items()
                if k != "cost"
            }
            if c.tracker.data.get("previous_session")
            else {}
        ),
    ),
    EveusSensorDescription(
        key="month_cost",
        translation_key="month_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda c: _r(c.tracker.month("cost")),
        unit_fn=lambda c: c.tracker.currency,
        last_reset_fn=lambda c: c.tracker.month_start,
        attrs_fn=lambda c: {
            "month": c.tracker.data["month"]["key"],
            "day_cost": _r(c.tracker.month("cost", ZONE_DAY)),
            "night_cost": _r(c.tracker.month("cost", ZONE_NIGHT)),
            "average_price": (
                _r(c.tracker.month("cost") / c.tracker.month("energy"))
                if c.tracker.month("energy") > 0
                else None
            ),
            **_previous_month(c.tracker, "cost"),
        },
    ),
    EveusSensorDescription(
        key="month_energy",
        translation_key="month_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda c: _r(c.tracker.month("energy")),
        last_reset_fn=lambda c: c.tracker.month_start,
        attrs_fn=lambda c: {
            "month": c.tracker.data["month"]["key"],
            "day_energy_kwh": _r(c.tracker.month("energy", ZONE_DAY)),
            "night_energy_kwh": _r(c.tracker.month("energy", ZONE_NIGHT)),
            **_previous_month(c.tracker, "energy"),
        },
    ),
    *(
        EveusSensorDescription(
            key=f"month_{zone}_energy",
            translation_key=f"month_{zone}_energy",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            value_fn=lambda c, z=zone: _r(c.tracker.month("energy", z)),
            last_reset_fn=lambda c: c.tracker.month_start,
            attrs_fn=lambda c, z=zone: {
                "month": c.tracker.data["month"]["key"],
                "cost": _r(c.tracker.month("cost", z)),
                "total_energy_kwh": _r(c.tracker.total("energy", z)),
                **(
                    {
                        "previous_month_energy_kwh": _r(
                            c.tracker.data["previous_month"][f"{z}_energy"]
                        )
                    }
                    if c.tracker.data.get("previous_month")
                    else {}
                ),
            },
        )
        for zone in ZONES
    ),
    EveusSensorDescription(
        key="total_cost",
        translation_key="total_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda c: _r(c.tracker.total("cost")),
        unit_fn=lambda c: c.tracker.currency,
        last_reset_fn=lambda c: _iso_to_dt(c.tracker.data.get("totals_since")),
        attrs_fn=lambda c: {
            "energy_kwh": _r(c.tracker.total("energy")),
            "since": c.tracker.data.get("totals_since"),
        },
    ),
    *(
        EveusSensorDescription(
            key=f"total_{zone}_cost",
            translation_key=f"total_{zone}_cost",
            device_class=SensorDeviceClass.MONETARY,
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda c, z=zone: _r(c.tracker.total("cost", z)),
            unit_fn=lambda c: c.tracker.currency,
            last_reset_fn=lambda c: _iso_to_dt(c.tracker.data.get("totals_since")),
            attrs_fn=lambda c, z=zone: {
                "energy_kwh": _r(c.tracker.total("energy", z)),
                "since": c.tracker.data.get("totals_since"),
            },
        )
        for zone in ZONES
    ),
)


# Cost sensors are computed locally, so they stay available while the charger
# is unreachable.
COST_SENSORS = tuple(replace(d, from_tracker=True) for d in COST_SENSORS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create all sensors."""
    coordinator = entry.runtime_data
    descriptions = [
        *CHARGER_SENSORS,
        *(d for d in PHASE_SENSORS if d.phases <= coordinator.phases),
        *COST_SENSORS,
    ]
    async_add_entities(EveusSensor(coordinator, d) for d in descriptions)


class EveusSensor(EveusEntity, SensorEntity):
    """A sensor reading either the charger or the cost tracker."""

    entity_description: EveusSensorDescription

    def __init__(
        self, coordinator: EveusCoordinator, description: EveusSensorDescription
    ) -> None:
        super().__init__(coordinator, description)
        if description.unit_fn:
            self._attr_native_unit_of_measurement = description.unit_fn(coordinator)

    @property
    def available(self) -> bool:
        if self.entity_description.from_tracker:
            return True
        return super().available

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def last_reset(self) -> datetime | None:
        fn = self.entity_description.last_reset_fn
        return fn(self.coordinator) if fn else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator)
