"""Config flow: charger connection + two-zone tariff."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .api import EveusAuthError, EveusClient, EveusError
from .const import (
    CONF_CURRENCY,
    CONF_DAY_PRICE,
    CONF_DEVICE_NAME,
    CONF_HOST,
    CONF_MAX_CURRENT,
    CONF_NIGHT_END,
    CONF_NIGHT_PRICE,
    CONF_NIGHT_START,
    CONF_PASSWORD,
    CONF_PHASES,
    CONF_REAPPLY,
    CONF_REAPPLY_DELAY,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_CURRENCY,
    DEFAULT_DAY_PRICE,
    DEFAULT_DEVICE_NAME,
    DEFAULT_MAX_CURRENT,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_PRICE,
    DEFAULT_NIGHT_START,
    DEFAULT_PHASES,
    DEFAULT_REAPPLY,
    DEFAULT_REAPPLY_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_CURRENT,
    MAX_REAPPLY_DELAY,
    MAX_SCAN_INTERVAL,
    MIN_CURRENT,
    MIN_SCAN_INTERVAL,
    PHASES,
)

PRICE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=1000, step="any", mode=selector.NumberSelectorMode.BOX
    )
)
INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        unit_of_measurement="s",
        mode=selector.NumberSelectorMode.BOX,
    )
)
CURRENT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_CURRENT,
        max=MAX_CURRENT,
        step=1,
        unit_of_measurement="A",
        mode=selector.NumberSelectorMode.BOX,
    )
)
PHASES_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=PHASES, translation_key="phases")
)
DELAY_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=MAX_REAPPLY_DELAY,
        step=1,
        unit_of_measurement="s",
        mode=selector.NumberSelectorMode.BOX,
    )
)
BOOL_SELECTOR = selector.BooleanSelector()
TIME_SELECTOR = selector.TimeSelector()
TEXT_SELECTOR = selector.TextSelector()
PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _connection_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(
            CONF_DEVICE_NAME, default=defaults.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
        ): TEXT_SELECTOR,
        vol.Required(
            CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)
        ): TEXT_SELECTOR,
        vol.Optional(
            CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
        ): TEXT_SELECTOR,
        vol.Optional(
            CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")
        ): PASSWORD_SELECTOR,
        vol.Required(
            CONF_PHASES, default=str(defaults.get(CONF_PHASES, DEFAULT_PHASES))
        ): PHASES_SELECTOR,
        vol.Required(
            CONF_MAX_CURRENT,
            default=defaults.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT),
        ): CURRENT_SELECTOR,
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): INTERVAL_SELECTOR,
        vol.Required(
            CONF_REAPPLY, default=defaults.get(CONF_REAPPLY, DEFAULT_REAPPLY)
        ): BOOL_SELECTOR,
        vol.Required(
            CONF_REAPPLY_DELAY,
            default=defaults.get(CONF_REAPPLY_DELAY, DEFAULT_REAPPLY_DELAY),
        ): DELAY_SELECTOR,
    }


def _tariff_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(
            CONF_DAY_PRICE, default=defaults.get(CONF_DAY_PRICE, DEFAULT_DAY_PRICE)
        ): PRICE_SELECTOR,
        vol.Required(
            CONF_NIGHT_PRICE,
            default=defaults.get(CONF_NIGHT_PRICE, DEFAULT_NIGHT_PRICE),
        ): PRICE_SELECTOR,
        vol.Required(
            CONF_NIGHT_START,
            default=defaults.get(CONF_NIGHT_START, DEFAULT_NIGHT_START),
        ): TIME_SELECTOR,
        vol.Required(
            CONF_NIGHT_END, default=defaults.get(CONF_NIGHT_END, DEFAULT_NIGHT_END)
        ): TIME_SELECTOR,
        vol.Required(
            CONF_CURRENCY, default=defaults.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        ): TEXT_SELECTOR,
    }


def _validate_tariff(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    start = dt_util.parse_time(user_input[CONF_NIGHT_START])
    end = dt_util.parse_time(user_input[CONF_NIGHT_END])
    if start is None or end is None:
        errors["base"] = "invalid_time"
    elif start == end:
        errors["base"] = "same_time"
    return errors


async def _test_connection(
    hass, user_input: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    """Return (error key or None, the data the charger sent back)."""
    client = EveusClient(
        hass,
        user_input[CONF_HOST].strip(),
        user_input.get(CONF_USERNAME) or None,
        user_input.get(CONF_PASSWORD) or None,
    )
    try:
        data = await client.async_get_data()
    except EveusAuthError:
        return "invalid_auth", {}
    except EveusError:
        return "cannot_connect", {}
    return None, data


def _design_current(data: dict[str, Any]) -> int | None:
    """What the charger says its wiring is designed for."""
    try:
        value = int(float(data.get("curDesign")))
    except (TypeError, ValueError):
        return None
    return value if MIN_CURRENT <= value <= MAX_CURRENT else None


class EveusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two steps: connect to the charger, then set the tariff."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            error, data = await _test_connection(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                self._data.update(user_input)
                return await self.async_step_tariff()
            self._suggested_max = _design_current(data)

        defaults = dict(user_input or {})
        if not user_input and getattr(self, "_suggested_max", None):
            defaults[CONF_MAX_CURRENT] = self._suggested_max

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(_connection_schema(defaults)),
            errors=errors,
        )

    async def async_step_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_CURRENCY] = user_input[CONF_CURRENCY].strip().upper()
            errors = _validate_tariff(user_input)
            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(
                    title=self._data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
                    data=self._data,
                )

        return self.async_show_form(
            step_id="tariff",
            data_schema=vol.Schema(_tariff_schema(user_input or {})),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**entry.data, **user_input}
            error, _ = await _test_connection(self.hass, merged)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=merged)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME, default=""): TEXT_SELECTOR,
                    vol.Optional(CONF_PASSWORD, default=""): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EveusOptionsFlow()


class EveusOptionsFlow(OptionsFlow):
    """Everything is editable after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            user_input[CONF_CURRENCY] = user_input[CONF_CURRENCY].strip().upper()
            errors = _validate_tariff(user_input)
            if not errors and user_input[CONF_HOST] != current.get(CONF_HOST):
                error, _ = await _test_connection(self.hass, user_input)
                if error:
                    errors["base"] = error
            if not errors:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    **_connection_schema(user_input or current),
                    **_tariff_schema(user_input or current),
                }
            ),
            errors=errors,
        )
