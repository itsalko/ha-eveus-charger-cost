"""Minimal HTTP client for Eveus / Energy Star EVSE chargers.

The charger exposes three endpoints on its local web interface:

* ``POST /init``                      – static configuration (firmware, design current, ...)
* ``POST /main`` ``{"getState": true}`` – live state (voltage, current, energy, ...)
* ``POST /pageEvent`` ``key=value``    – write a setting, the key repeated in a ``pageEvent`` header
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=10)


class EveusError(Exception):
    """The charger could not be reached or answered with garbage."""


class EveusAuthError(EveusError):
    """Wrong user name or password."""


class EveusClient:
    """Talks to one charger."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._hass = hass
        self.host = host
        self._auth = (
            aiohttp.BasicAuth(username, password or "") if username else None
        )
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Root URL of the charger's web interface."""
        return f"http://{self.host}"

    async def async_get_data(self) -> dict[str, Any]:
        """Return /init and /main merged into one dict."""
        data: dict[str, Any] = {}
        try:
            data.update(await self._post_json("/init"))
        except EveusAuthError:
            raise
        except EveusError as err:  # /init is optional, /main is not
            _LOGGER.debug("Could not read /init from %s: %s", self.host, err)
        data.update(await self._post_json("/main", {"getState": True}))
        if not data:
            raise EveusError("Charger returned no data")
        return data

    async def async_set_value(self, key: str, value: Any) -> None:
        """Write a single setting to the charger."""
        session = async_get_clientsession(self._hass)
        async with self._lock:
            try:
                async with session.post(
                    f"{self.base_url}/pageEvent",
                    data=f"{key}={value}",
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "pageEvent": key,
                    },
                    auth=self._auth,
                    timeout=TIMEOUT,
                ) as response:
                    if response.status in (401, 403):
                        raise EveusAuthError("Authentication failed")
                    if response.status != 200:
                        raise EveusError(f"{key}: HTTP {response.status}")
            except TimeoutError as err:
                raise EveusError(f"{key}: timeout") from err
            except aiohttp.ClientError as err:
                raise EveusError(f"{key}: {err}") from err

    async def _post_json(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session = async_get_clientsession(self._hass)
        try:
            async with session.post(
                f"{self.base_url}{path}",
                json=payload,
                auth=self._auth,
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise EveusAuthError("Authentication failed")
                if response.status != 200:
                    raise EveusError(f"{path}: HTTP {response.status}")
                try:
                    result = await response.json(content_type=None)
                except ValueError as err:
                    raise EveusError(f"{path}: invalid JSON") from err
        except TimeoutError as err:
            raise EveusError(f"{path}: timeout") from err
        except aiohttp.ClientError as err:
            raise EveusError(f"{path}: {err}") from err

        if not isinstance(result, dict):
            raise EveusError(f"{path}: unexpected payload")
        return result


def as_float(value: Any) -> float | None:
    """Best-effort float conversion of a charger field."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool:
    """Best-effort bool conversion of a charger field."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)
