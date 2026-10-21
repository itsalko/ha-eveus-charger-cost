"""Polling coordinator for the Eveus charger."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EveusAuthError, EveusClient, EveusError, as_float
from .const import (
    CONF_DEVICE_NAME,
    CONF_MAX_CURRENT,
    CONF_REAPPLY,
    CONF_REAPPLY_DELAY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PHASES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_DEVICE_NAME,
    DEFAULT_PHASES,
    CHARGING_STATE,
    CONNECTED_STATES,
    DEFAULT_MAX_CURRENT,
    DEFAULT_REAPPLY,
    DEFAULT_REAPPLY_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MAX_REAPPLY_ATTEMPTS,
    MIN_CURRENT,
    MODEL,
    NUDGE_PAUSE,
    REARM_TIMEOUT,
    VERIFY_DELAY,
    VERIFY_TOLERANCE_A,
)
from .tracker import CostTracker

_LOGGER = logging.getLogger(__name__)


class EveusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the charger and feeds the cost tracker."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=int(conf.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self.entry = entry
        self.client = EveusClient(
            hass,
            conf[CONF_HOST],
            conf.get(CONF_USERNAME) or None,
            conf.get(CONF_PASSWORD) or None,
        )
        self.phases = int(conf.get(CONF_PHASES, DEFAULT_PHASES))
        self.device_name = conf.get(CONF_DEVICE_NAME) or DEFAULT_DEVICE_NAME
        self.max_current = int(conf.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT))
        self.reapply = bool(conf.get(CONF_REAPPLY, DEFAULT_REAPPLY))
        self.reapply_delay = float(
            conf.get(CONF_REAPPLY_DELAY, DEFAULT_REAPPLY_DELAY)
        )
        self._last_state: int | None = None
        self._rearm_after: float | None = None
        self._cancel_reapply: CALLBACK_TYPE | None = None
        self._attempts = 0
        self.tracker = CostTracker(hass, entry, on_change=self._on_tracker_change)

    @property
    def device_info(self) -> DeviceInfo:
        """Device shown in Home Assistant for this charger."""
        data = self.data or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=str(data.get("verFWMain") or data.get("fwVersion") or "")
            or None,
            configuration_url=self.client.base_url,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.async_get_data()
        except EveusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EveusError as err:
            # The charger is unreachable (powered off, rebooting, off the
            # network), so coming back counts as a fresh start: forget the
            # last state and let the limit be sent again.
            self._last_state = None
            raise UpdateFailed(str(err)) from err

        self.tracker.process(
            as_float(data.get("totalEnergy")), as_float(data.get("sessionEnergy"))
        )
        self._check_charge_start(data)
        await self._check_rearm(data)
        return data

    # ------------------------------------------------ re-applying the current

    def _check_charge_start(self, data: dict[str, Any]) -> None:
        """Re-apply whenever a charge is about to start.

        A car reads the limit when it starts drawing power, which is not only
        at plug-in: delayed charging, "Stop" then "Start", or the car waking up
        on its own all start a charge later, and each of those needs the limit
        sent again.
        """
        raw = as_float(data.get("state"))
        state = int(raw) if raw is not None else None
        previous, self._last_state = self._last_state, state
        if not self.reapply or state is None:
            return

        if previous is None:
            # First reading after the charger came up (switched on at the
            # socket, rebooted, or Home Assistant restarted). A car plugged in
            # before that never saw the limit and sits at the default 6 A.
            if state in CONNECTED_STATES:
                self._attempts = 0
                _LOGGER.info(
                    "Charger came up with a car connected (state %s); "
                    "re-applying the current limit in %.0f s",
                    state,
                    self.reapply_delay,
                )
                self.schedule_reapply(self.reapply_delay)
            return

        if state != CHARGING_STATE and previous == CHARGING_STATE:
            self._attempts = 0  # charge ended, start counting again next time

        plugged_in = state in CONNECTED_STATES and previous not in CONNECTED_STATES
        charge_started = state == CHARGING_STATE and previous != CHARGING_STATE
        if not (plugged_in or charge_started):
            return

        self._attempts = 0
        _LOGGER.info(
            "%s (state %s -> %s); re-applying the current limit in %.0f s",
            "Charging started" if charge_started else "Car connected",
            previous,
            state,
            self.reapply_delay,
        )
        self.schedule_reapply(self.reapply_delay)

    # ------------------------------------------------------- ending a session

    async def async_end_session(self) -> None:
        """Stop charging so the car ends the session and can release the plug.

        The charger has no command for the connector lock — the lock pin sits in
        the car's inlet and only the car can open it. Removing the signal makes
        the car finish the session, which is what lets it unlock. The charger is
        armed again by itself once the cable is unplugged.
        """
        self.cancel_reapply()
        await self.client.async_set_value("evseEnabled", 1)
        self._rearm_after = self.hass.loop.time() + REARM_TIMEOUT
        _LOGGER.info("Charging stopped; waiting for the cable to be unplugged")
        await self.async_request_refresh()

    async def _check_rearm(self, data: dict[str, Any]) -> None:
        """Re-enable the charger once the car is gone, so the next plug-in works."""
        if self._rearm_after is None:
            return
        raw = as_float(data.get("state"))
        state = int(raw) if raw is not None else None
        unplugged = state is not None and state not in CONNECTED_STATES
        if not unplugged and self.hass.loop.time() < self._rearm_after:
            return
        self._rearm_after = None
        try:
            await self.client.async_set_value("evseEnabled", 0)
        except EveusError as err:
            _LOGGER.warning("Could not re-arm the charger: %s", err)
            return
        _LOGGER.info("Charger re-armed and ready for the next session")

    def schedule_reapply(self, delay: float) -> None:
        """Re-send the current limit a little after the car connects."""
        self.cancel_reapply()

        async def _run(_now) -> None:
            self._cancel_reapply = None
            await self.async_reapply_current()

        self._cancel_reapply = async_call_later(self.hass, delay, _run)

    def cancel_reapply(self) -> None:
        """Drop a pending re-apply."""
        if self._cancel_reapply:
            self._cancel_reapply()
            self._cancel_reapply = None

    async def async_reapply_current(self) -> None:
        """Step the current limit by 1 A and back so the car sees the change."""
        target = as_float((self.data or {}).get("currentSet"))
        if target is None:
            return
        target = int(target)
        design = as_float((self.data or {}).get("curDesign"))
        ceiling = int(min(self.max_current, design) if design else self.max_current)
        # Step up by 1 A when there is room, otherwise down — the car reacts to
        # the change itself, not to its direction.
        if target + 1 <= ceiling:
            nudge = target + 1
        elif target - 1 >= MIN_CURRENT:
            nudge = target - 1
        else:
            _LOGGER.warning("No room to step the current limit around %s A", target)
            return
        try:
            await self.client.async_set_value("currentSet", nudge)
            await asyncio.sleep(NUDGE_PAUSE)
            await self.client.async_set_value("currentSet", target)
        except EveusError as err:
            _LOGGER.warning("Could not re-apply the current limit: %s", err)
            return
        self._attempts += 1
        _LOGGER.info(
            "Re-applied the charging current: %s A (attempt %s)",
            target,
            self._attempts,
        )
        await self.async_request_refresh()
        if self.reapply and self._attempts < MAX_REAPPLY_ATTEMPTS:
            self.schedule_verify(VERIFY_DELAY)

    def schedule_verify(self, delay: float) -> None:
        """Check later whether the car actually took the higher current."""
        self.cancel_reapply()

        async def _run(_now) -> None:
            self._cancel_reapply = None
            await self._async_verify_current()

        self._cancel_reapply = async_call_later(self.hass, delay, _run)

    async def _async_verify_current(self) -> None:
        """If the car is still stuck near 6 A, send the limit once more."""
        data = self.data or {}
        raw = as_float(data.get("state"))
        if raw is None or int(raw) != CHARGING_STATE:
            return
        target = as_float(data.get("currentSet"))
        measured = max(
            (as_float(data.get(f"curMeas{phase}")) or 0) for phase in (1, 2, 3)
        )
        if target is None or measured >= target - VERIFY_TOLERANCE_A:
            return
        _LOGGER.info(
            "Car is drawing %.1f A of the %.0f A allowed; trying again",
            measured,
            target,
        )
        await self.async_reapply_current()

    async def async_write(self, key: str, value: Any) -> None:
        """Write a setting to the charger and refresh."""
        await self.client.async_set_value(key, value)
        await self.async_request_refresh()

    @callback
    def _on_tracker_change(self) -> None:
        """Push cost-sensor updates that did not come from a poll."""
        self.async_update_listeners()
