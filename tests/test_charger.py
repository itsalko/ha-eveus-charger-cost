from datetime import datetime, time, timedelta
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.evse_charging_cost.const import DOMAIN
from custom_components.evse_charging_cost.tracker import zone_for

HOST = "192.168.1.50"
INIT_URL = f"http://{HOST}/init"
MAIN_URL = f"http://{HOST}/main"
EVENT_URL = f"http://{HOST}/pageEvent"

CONN = {
    "device_name": "Eveus",
    "host": HOST,
    "username": "",
    "password": "",
    "phases": "1",
    "max_current": 16,
    "scan_interval": 15,
    "reapply_current": True,
    "reapply_delay": 15,
}
TARIFF = {
    "day_price": 4.32,
    "night_price": 2.16,
    "night_start": "23:00:00",
    "night_end": "07:00:00",
    "currency": "UAH",
}
DATA = {**CONN, **TARIFF}


def last_write(aioclient_mock):
    """Body of the most recent /pageEvent request."""
    writes = [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    return writes[-1][2]


def state(total=100.0, session=0.0, **extra):
    return {
        "state": 4,
        "currentSet": 16,
        "curDesign": 32,
        "voltMeas1": 230,
        "curMeas1": 16,
        "powerMeas": 3680,
        "sessionEnergy": session,
        "totalEnergy": total,
        "sessionTime": 600,
        "temperature1": 30,
        "temperature2": 35,
        "ground": 1,
        "evseEnabled": 0,
        "oneCharge": 0,
        **extra,
    }


def mock_device(aioclient_mock, **kwargs):
    aioclient_mock.clear_requests()
    aioclient_mock.post(INIT_URL, json={"verFWMain": "1.2.3"})
    aioclient_mock.post(MAIN_URL, json=state(**kwargs))
    aioclient_mock.post(EVENT_URL, text="OK")


async def setup_entry(hass, aioclient_mock, **kwargs):
    mock_device(aioclient_mock, **kwargs)
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, title="Eveus", version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_zone_for():
    s, e = time(23), time(7)
    assert zone_for(time(23, 30), s, e) == "night"
    assert zone_for(time(3), s, e) == "night"
    assert zone_for(time(7), s, e) == "day"
    assert zone_for(time(2), time(1), time(6)) == "night"


async def test_config_flow(hass: HomeAssistant, aioclient_mock):
    mock_device(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONN)
    assert result["step_id"] == "tariff"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], TARIFF)
    assert result["type"] == "create_entry"
    assert result["data"]["host"] == HOST
    await hass.async_block_till_done()

    assert hass.states.get("sensor.eveus_power").state == "3680.0"
    assert hass.states.get("sensor.eveus_status").state == "charging"
    limit = hass.states.get("number.eveus_charging_current")
    assert limit.state == "16.0"
    assert limit.attributes["max"] == 16  # configured, not the charger's 32 A design


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(INIT_URL, status=500)
    aioclient_mock.post(MAIN_URL, status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONN)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_billing_and_controls(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, total=100, session=0)
    coordinator = entry.runtime_data
    day = dt_util.as_local(dt_util.now()).replace(hour=12, minute=0, second=0)
    night = day.replace(hour=1)

    with patch("custom_components.evse_charging_cost.tracker.dt_util.now", return_value=day):
        mock_device(aioclient_mock, total=102, session=2)
        await coordinator.async_refresh()
    with patch("custom_components.evse_charging_cost.tracker.dt_util.now", return_value=night):
        mock_device(aioclient_mock, total=105, session=5)
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert float(hass.states.get("sensor.eveus_session_cost").state) == pytest.approx(15.12)
    assert float(hass.states.get("sensor.eveus_energy_this_month_night").state) == 3
    assert float(hass.states.get("sensor.eveus_total_cost").state) == pytest.approx(15.12)

    # new session detected from the charger's own session counter
    with patch("custom_components.evse_charging_cost.tracker.dt_util.now", return_value=day):
        mock_device(aioclient_mock, total=106, session=1)
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.eveus_last_session_cost").state) == pytest.approx(15.12)
    assert float(hass.states.get("sensor.eveus_session_cost").state) == pytest.approx(4.32)

    # writing settings
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.eveus_charging_current", "value": 10}, blocking=True
    )
    assert last_write(aioclient_mock) == "currentSet=10"

    # evseEnabled is inverted in the firmware: 0 = running, 1 = stopped
    assert hass.states.get("switch.eveus_charging_enabled").state == "on"
    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.eveus_charging_enabled"}, blocking=True
    )
    assert last_write(aioclient_mock) == "evseEnabled=1"

    mock_device(aioclient_mock, total=106, session=1, evseEnabled=1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.eveus_charging_enabled").state == "off"
    await hass.services.async_call(
        "switch", "turn_on",
        {"entity_id": "switch.eveus_charging_enabled"}, blocking=True
    )
    assert last_write(aioclient_mock) == "evseEnabled=0"

    # counters survive a reload, buttons work offline
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.eveus_total_cost").state) == pytest.approx(19.44)

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.eveus_reset_counts"}, blocking=True
    )
    assert float(hass.states.get("sensor.eveus_total_cost").state) == 0


async def test_max_current_follows_options(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock)
    assert hass.states.get("number.eveus_charging_current").attributes["max"] == 16

    hass.config_entries.async_update_entry(entry, options={**DATA, "max_current": 25})
    await hass.async_block_till_done()
    assert hass.states.get("number.eveus_charging_current").attributes["max"] == 25

    # never above what the charger says its wiring is designed for
    hass.config_entries.async_update_entry(entry, options={**DATA, "max_current": 32})
    mock_device(aioclient_mock, total=100, session=0)
    await hass.async_block_till_done()
    assert hass.states.get("number.eveus_charging_current").attributes["max"] == 32


async def test_offline_keeps_cost_sensors(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, total=100, session=0)
    aioclient_mock.clear_requests()
    aioclient_mock.post(INIT_URL, exc=TimeoutError())
    aioclient_mock.post(MAIN_URL, exc=TimeoutError())
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.eveus_power").state == "unavailable"
    assert hass.states.get("sensor.eveus_total_cost").state == "0.0"
    assert hass.states.get("sensor.eveus_current_tariff").state in ("day", "night")


async def test_card_is_served(hass: HomeAssistant, aioclient_mock, hass_client):
    await setup_entry(hass, aioclient_mock)
    client = await hass_client()
    response = await client.get("/evse_charging_cost/eveus-flow-card.js")
    assert response.status == 200
    body = await response.text()
    assert "customElements.define(\"eveus-flow-card\"" in body


async def test_reapply_after_plug_in(hass: HomeAssistant, aioclient_mock):
    """A car that connects while a limit is set must be told about it again."""
    entry = await setup_entry(hass, aioclient_mock, state=2)  # standby
    coordinator = entry.runtime_data

    mock_device(aioclient_mock, state=3)  # car connected
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    # already at the configured maximum of 16 A, so the nudge goes down
    assert writes[-2:] == ["currentSet=15", "currentSet=16"]


async def test_reapply_steps_up_when_there_is_room(hass: HomeAssistant, aioclient_mock):
    """Below the maximum, the nudge goes up first."""
    entry = await setup_entry(hass, aioclient_mock, state=2, currentSet=13)

    mock_device(aioclient_mock, state=3, currentSet=13)
    await entry.runtime_data.async_refresh()
    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    assert writes[-2:] == ["currentSet=14", "currentSet=13"]


async def test_reapply_waits_for_the_full_delay(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, state=2)
    mock_device(aioclient_mock, state=4)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=13))
        await hass.async_block_till_done()
        assert not [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
        await hass.async_block_till_done()
        assert [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]


async def test_no_reapply_when_disabled(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, state=2)
    hass.config_entries.async_update_entry(
        entry, options={**DATA, "reapply_current": False}
    )
    await hass.async_block_till_done()

    mock_device(aioclient_mock, state=3)
    await entry.runtime_data.async_refresh()
    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    assert not [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]


async def test_card_url_registered(hass: HomeAssistant, aioclient_mock):
    """The card must end up in the frontend's module list."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager

    # The real frontend needs the hass_frontend package, so stand in for it.
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda urls: None, [])
    hass.config.components.add("frontend")

    await setup_entry(hass, aioclient_mock)
    await hass.async_block_till_done()

    assert any(
        "eveus-flow-card.js" in url
        for url in hass.data[DATA_EXTRA_MODULE_URL].urls
    )


async def test_end_session_stops_then_rearms(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, state=4, evseEnabled=0)
    coordinator = entry.runtime_data

    await hass.services.async_call(
        "button", "press",
        {"entity_id": "button.eveus_end_charging_session"}, blocking=True
    )
    assert last_write(aioclient_mock) == "evseEnabled=1"

    # car still plugged in: nothing happens yet
    mock_device(aioclient_mock, state=3, evseEnabled=1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]

    # cable unplugged -> the charger is armed again for the next session
    mock_device(aioclient_mock, state=2, evseEnabled=1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert last_write(aioclient_mock) == "evseEnabled=0"


async def test_card_added_as_lovelace_resource(hass: HomeAssistant, aioclient_mock):
    """Lovelace waits for its resources, so the card must land in that list."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    resources = SimpleNamespace(
        async_get_info=AsyncMock(),
        async_items=lambda: [],
        async_create_item=AsyncMock(),
        async_update_item=AsyncMock(),
    )
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    hass.config.components.add("frontend")

    await setup_entry(hass, aioclient_mock)
    await hass.async_block_till_done()

    created = resources.async_create_item.call_args[0][0]
    assert created["res_type"] == "module"
    assert created["url"].startswith("/evse_charging_cost/eveus-flow-card.js?v=")


async def test_reapply_when_charging_starts_later(hass: HomeAssistant, aioclient_mock):
    """Delayed charging: the car connects first and only starts drawing later."""
    entry = await setup_entry(hass, aioclient_mock, state=3, currentSet=13)
    coordinator = entry.runtime_data

    # plug-in re-apply happens first
    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        mock_device(aioclient_mock, state=3, currentSet=13)
        await coordinator.async_refresh()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

        # ...and again when the charge actually begins
        mock_device(aioclient_mock, state=4, currentSet=13, curMeas1=6)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        aioclient_mock.mock_calls.clear()

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    assert writes[-2:] == ["currentSet=14", "currentSet=13"]


async def test_reapply_retries_when_car_stays_at_six_amps(
    hass: HomeAssistant, aioclient_mock
):
    entry = await setup_entry(hass, aioclient_mock, state=3, currentSet=13)
    coordinator = entry.runtime_data

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        mock_device(aioclient_mock, state=4, currentSet=13, curMeas1=6)
        await coordinator.async_refresh()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()
        aioclient_mock.mock_calls.clear()

        # a minute later the car is still stuck at 6 A -> one more try
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=70))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    assert writes[-2:] == ["currentSet=14", "currentSet=13"]


async def test_reapply_when_charger_powers_up_with_car_connected(
    hass: HomeAssistant, aioclient_mock
):
    """Cable plugged into the car first, charger switched on afterwards."""
    await setup_entry(hass, aioclient_mock, state=4, currentSet=13, curMeas1=6)
    aioclient_mock.mock_calls.clear()

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    assert writes[-2:] == ["currentSet=14", "currentSet=13"]


async def test_no_reapply_when_powering_up_without_a_car(
    hass: HomeAssistant, aioclient_mock
):
    await setup_entry(hass, aioclient_mock, state=2, currentSet=13)
    aioclient_mock.mock_calls.clear()

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    assert not [c for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]


async def test_reapply_after_charger_power_cycle(hass: HomeAssistant, aioclient_mock):
    """A charger that drops off the network and returns gets the limit again."""
    entry = await setup_entry(hass, aioclient_mock, state=2, currentSet=13)
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.post(INIT_URL, exc=TimeoutError())
    aioclient_mock.post(MAIN_URL, exc=TimeoutError())
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    mock_device(aioclient_mock, state=4, currentSet=13, curMeas1=6)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    aioclient_mock.mock_calls.clear()

    with patch("custom_components.evse_charging_cost.coordinator.NUDGE_PAUSE", 0):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()

    writes = [c[2] for c in aioclient_mock.mock_calls if c[1].path == "/pageEvent"]
    assert writes[-2:] == ["currentSet=14", "currentSet=13"]
