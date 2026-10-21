"""Energy-to-money accounting with two time zones (day / night)."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CURRENCY,
    CONF_DAY_PRICE,
    CONF_NIGHT_END,
    CONF_NIGHT_PRICE,
    CONF_NIGHT_START,
    DEFAULT_CURRENCY,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DOMAIN,
    MAX_DELTA_KWH,
    SESSION_RESET_THRESHOLD_KWH,
    STORAGE_VERSION,
    ZONE_DAY,
    ZONE_NIGHT,
    ZONES,
)

_LOGGER = logging.getLogger(__name__)
SAVE_DELAY = 30  # seconds


def _bucket() -> dict[str, float]:
    return {"energy": 0.0, "cost": 0.0}


def _month_key(moment: datetime) -> str:
    return dt_util.as_local(moment).strftime("%Y-%m")


def _empty_month(key: str) -> dict[str, Any]:
    return {"key": key, **{zone: _bucket() for zone in ZONES}}


def _empty_data() -> dict[str, Any]:
    return {
        "last_total": None,
        "last_session_value": None,
        "totals": {zone: _bucket() for zone in ZONES},
        "totals_since": dt_util.utcnow().isoformat(),
        "session": {zone: _bucket() for zone in ZONES},
        "session_started": None,
        "previous_session": None,
        "month": _empty_month(_month_key(dt_util.now())),
        "previous_month": None,
    }


def parse_time(value: str | None, default: str) -> time:
    """Parse 'HH:MM[:SS]' into a time object."""
    parsed = dt_util.parse_time(value or default)
    return parsed if parsed is not None else dt_util.parse_time(default)


def zone_for(moment: time, night_start: time, night_end: time) -> str:
    """Return which tariff zone a local wall-clock time falls into."""
    if night_start < night_end:  # e.g. 01:00-06:00
        is_night = night_start <= moment < night_end
    else:  # crosses midnight, e.g. 23:00-07:00
        is_night = moment >= night_start or moment < night_end
    return ZONE_NIGHT if is_night else ZONE_DAY


class CostTracker:
    """Bills every kWh reported by the charger at the price of its time zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        on_change: CALLBACK_TYPE | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._on_change = on_change
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.data: dict[str, Any] = _empty_data()
        self._unsubs: list[CALLBACK_TYPE] = []
        self.apply_config()

    # ------------------------------------------------------------------ config

    def apply_config(self) -> None:
        """Read prices and tariff hours from the config entry."""
        conf = {**self.entry.data, **self.entry.options}
        self.prices = {
            ZONE_DAY: float(conf[CONF_DAY_PRICE]),
            ZONE_NIGHT: float(conf[CONF_NIGHT_PRICE]),
        }
        self.night_start = parse_time(conf.get(CONF_NIGHT_START), DEFAULT_NIGHT_START)
        self.night_end = parse_time(conf.get(CONF_NIGHT_END), DEFAULT_NIGHT_END)
        self.currency: str = conf.get(CONF_CURRENCY) or DEFAULT_CURRENCY

    # --------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Load saved counters and start the clock listeners."""
        stored = await self._store.async_load()
        if stored:
            self.data.update(stored)
        self._roll_month()

        for boundary in {self.night_start, self.night_end}:
            self._unsubs.append(
                async_track_time_change(
                    self.hass,
                    self._on_zone_boundary,
                    hour=boundary.hour,
                    minute=boundary.minute,
                    second=boundary.second,
                )
            )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._on_midnight, hour=0, minute=0, second=0
            )
        )
        self._save()

    async def async_stop(self) -> None:
        """Stop listeners and flush data to disk."""
        while self._unsubs:
            self._unsubs.pop()()
        await self._store.async_save(self.data)

    # -------------------------------------------------------------- zone info

    def zone_at(self, moment: datetime) -> str:
        """Tariff zone of a datetime, evaluated in Home Assistant's local time."""
        return zone_for(dt_util.as_local(moment).time(), self.night_start, self.night_end)

    @property
    def current_zone(self) -> str:
        """Tariff zone right now."""
        return self.zone_at(dt_util.now())

    @property
    def current_price(self) -> float:
        """Price per kWh right now."""
        return self.prices[self.current_zone]

    def next_zone_change(self) -> datetime:
        """Local datetime of the next switch between day and night."""
        now = dt_util.now()
        candidates = []
        for day_offset in (0, 1):
            day = (now + timedelta(days=day_offset)).date()
            for boundary in (self.night_start, self.night_end):
                candidate = datetime.combine(day, boundary, tzinfo=now.tzinfo)
                if candidate > now:
                    candidates.append(candidate)
        return min(candidates)

    # ----------------------------------------------------------- derived data

    def total(self, key: str, zone: str | None = None) -> float:
        """Lifetime energy/cost for one zone or both."""
        zones = [zone] if zone else list(ZONES)
        return sum(self.data["totals"][z][key] for z in zones)

    def month(self, key: str, zone: str | None = None) -> float:
        """Current calendar-month energy/cost for one zone or both."""
        zones = [zone] if zone else list(ZONES)
        return sum(self.data["month"][z][key] for z in zones)

    def session(self, key: str, zone: str | None = None) -> float:
        """Current-session energy/cost for one zone or both."""
        zones = [zone] if zone else list(ZONES)
        return sum(self.data["session"][z][key] for z in zones)

    @property
    def month_start(self) -> datetime:
        """Local midnight of the 1st day of the tracked month."""
        year, month = (int(x) for x in self.data["month"]["key"].split("-"))
        return dt_util.start_of_local_day(datetime(year, month, 1))

    # -------------------------------------------------------------- accounting

    @callback
    def process(self, total_energy: float | None, session_energy: float | None) -> None:
        """Feed one poll of the charger into the counters."""
        changed = False
        if session_energy is not None:
            changed |= self._process_session(session_energy)
        if total_energy is not None:
            changed |= self._process_total(total_energy)
        if changed:
            self._save()

    def _process_total(self, value: float) -> bool:
        last = self.data.get("last_total")
        self.data["last_total"] = value
        if last is None:
            return True  # first reading: just remember where the meter is

        delta = value - last
        if delta <= 0:
            if delta < 0:
                _LOGGER.info(
                    "Charger energy counter went down (%.3f -> %.3f kWh); "
                    "treating it as a meter reset",
                    last,
                    value,
                )
            return delta < 0
        if delta > MAX_DELTA_KWH:
            _LOGGER.warning("Ignoring implausible jump of %.3f kWh", delta)
            return False

        self._roll_month()
        zone = self.current_zone
        cost = delta * self.prices[zone]
        for bucket in (
            self.data["totals"][zone],
            self.data["session"][zone],
            self.data["month"][zone],
        ):
            bucket["energy"] += delta
            bucket["cost"] += cost
        if self.data.get("session_started") is None:
            self.data["session_started"] = dt_util.utcnow().isoformat()
        return True

    def _process_session(self, value: float) -> bool:
        last = self.data.get("last_session_value")
        self.data["last_session_value"] = value
        if last is not None and value < last - SESSION_RESET_THRESHOLD_KWH:
            self.finish_session()
            return True
        return last is None

    def finish_session(self) -> None:
        """Archive the running session and start a new empty one."""
        if self.session("energy") > 0:
            self.data["previous_session"] = {
                "energy": self.session("energy"),
                "cost": self.session("cost"),
                "day_energy": self.session("energy", ZONE_DAY),
                "night_energy": self.session("energy", ZONE_NIGHT),
                "started": self.data.get("session_started"),
                "ended": dt_util.utcnow().isoformat(),
            }
        self.data["session"] = {zone: _bucket() for zone in ZONES}
        self.data["session_started"] = None

    def _roll_month(self) -> bool:
        """Start a new month bucket if the calendar month changed."""
        key = _month_key(dt_util.now())
        current = self.data.get("month")
        if current and current.get("key") == key:
            return False
        if current and any(current[z]["energy"] > 0 for z in ZONES):
            self.data["previous_month"] = {
                "month": current["key"],
                "energy": sum(current[z]["energy"] for z in ZONES),
                "cost": sum(current[z]["cost"] for z in ZONES),
                "day_energy": current[ZONE_DAY]["energy"],
                "night_energy": current[ZONE_NIGHT]["energy"],
                "day_cost": current[ZONE_DAY]["cost"],
                "night_cost": current[ZONE_NIGHT]["cost"],
            }
        self.data["month"] = _empty_month(key)
        return True

    # ------------------------------------------------------------ manual acts

    @callback
    def new_session(self) -> None:
        """Close the current session manually."""
        self.finish_session()
        self._save()
        self._notify()

    @callback
    def reset_totals(self) -> None:
        """Zero the lifetime totals only."""
        self.data["totals"] = {zone: _bucket() for zone in ZONES}
        self.data["totals_since"] = dt_util.utcnow().isoformat()
        self._save()
        self._notify()

    @callback
    def reset_all(self) -> None:
        """Zero every counter; the meter position is kept."""
        self.data["totals"] = {zone: _bucket() for zone in ZONES}
        self.data["totals_since"] = dt_util.utcnow().isoformat()
        self.data["session"] = {zone: _bucket() for zone in ZONES}
        self.data["session_started"] = None
        self.data["previous_session"] = None
        self.data["month"] = _empty_month(_month_key(dt_util.now()))
        self.data["previous_month"] = None
        self._save()
        self._notify()

    # ---------------------------------------------------------------- helpers

    @callback
    def _on_midnight(self, _now: datetime) -> None:
        if self._roll_month():
            self._save()
        self._notify()

    @callback
    def _on_zone_boundary(self, _now: datetime) -> None:
        self._notify()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: copy.deepcopy(self.data), SAVE_DELAY)

    @callback
    def _notify(self) -> None:
        if self._on_change:
            self._on_change()
