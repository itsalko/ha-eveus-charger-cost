# ⚡ Eveus EV Charger + Cost

[![hacs][hacs-badge]][hacs-url]
[![validate][validate-badge]][validate-url]

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[validate-badge]: https://github.com/itsalko/ha-eveus-charger-cost/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/itsalko/ha-eveus-charger-cost/actions/workflows/validate.yml

Standalone Home Assistant integration for **Eveus / Energy Star EVSE** chargers
(Lite+, Pro, …). It talks to the charger directly over your local network and
adds **two-zone (day / night) cost accounting** on top.

## What it does

* Polls the charger's own web API (`/init`, `/main`) every few seconds.
* Controls the charger (`/pageEvent`): charging current, enable/disable charging,
  one-charge mode, adaptive mode, ground control.
* Counts every kWh the charger reports and bills it at the **day** or **night**
  price depending on when it was consumed – a charge from 21:00 to 03:00 is
  split correctly between the two prices.
* Keeps session, calendar-month and lifetime counters. They survive restarts
  (stored in `.storage/evse_charging_cost.<entry_id>`) and keep working while
  the charger is offline or unplugged.

## Installation

**HACS (recommended):** HACS → ⋮ (top right) → Custom repositories → paste this
repository's URL, type *Integration* → Add → open it in the list → Download →
restart Home Assistant.

**Manual:** copy `custom_components/evse_charging_cost` into
`<config>/custom_components/` and restart.

Then *Settings → Devices & services → Add integration → Eveus EV Charger + Cost*.

### Step 1 – charger

| Field | Example |
|---|---|
| Device name | `Eveus` |
| IP address | `192.168.1.50` (give the charger a static/reserved address) |
| User name / password | only if the charger's web interface asks for them |
| Phases | `1` or `3` |
| Maximum charging current | `16` A – prefilled from the charger's design current |
| Re-apply current after the car connects | on, after `15` s |
| Polling interval | `15` s (can go down to 1 s; below ~5 s some chargers get slow to answer) |

The address is tested before the entry is created.

### Step 2 – tariff

| Field | Example |
|---|---|
| Day price per kWh | `4.32` |
| Night price per kWh | `2.16` |
| Night starts / ends | `23:00` / `07:00` (crossing midnight is supported) |
| Currency | `UAH` |

Everything can be changed later under **Configure** – including the IP address,
credentials, polling interval and prices. New prices apply only to energy
charged afterwards; already counted costs are never recalculated.

## Entities

**Charger**

| Entity | Notes |
|---|---|
| Status | power up / self test / standby / car connected / charging / complete / disabled / error |
| Power | watts (computed from voltage × current if the charger reports no power) |
| Voltage L1–L3, Current L1–L3 | L2/L3 only in three-phase mode |
| Session energy, Session time, Total energy | as reported by the charger |
| Box temperature / Plug temperature | from the charger's two sensors, also shown on the card |
| Leakage current, Current setpoint, Charger time | disabled by default, enable in the entity settings |
| Charging (binary) | on while the car is actually charging |
| Ground problem (binary) | on when the ground check fails |
| Charging current (number) | 6 A … your configured maximum (never above the charger's design current) |
| Charging enabled, One charge, Adaptive mode, Ground control (switches) | written to the charger |

**Cost**

| Entity | Notes |
|---|---|
| Current tariff / Current price | day or night; price per kWh right now |
| Session cost | attributes: day/night kWh and cost, average price, start time |
| Last session cost | the previous finished session |
| Current month cost / Current month energy | reset on the 1st, previous month kept in attributes |
| Energy this month (day) / (night) | per-zone kWh this month |
| Total cost, Total day cost, Total night cost | since the last reset |
| End charging session (button) | stops charging and re-arms the charger once the cable is unplugged |
| Re-apply current (button) | sends the limit to the car again, on demand |
| Start new session, Reset counts, Reset totals (buttons) | Reset counts zeroes everything, Reset totals only the lifetime figures |

A new session is detected automatically when the charger's session counter drops
back to zero.

## Dashboard card

The integration ships a Lovelace card and registers it itself: on UI-managed
dashboards it adds (and keeps up to date) an entry in
Settings → Dashboards → Resources, which is what makes Lovelace wait for the
card before drawing. In YAML mode it falls back to an extra module URL, and you
may want to add `/evse_charging_cost/eveus-flow-card.js` to `lovelace.resources`
yourself. After a restart, add a card to your dashboard, choose
**Manual** and paste:

```yaml
type: custom:eveus-flow-card
```

That is all it needs: the card finds the charger's entities in the entity
registry, so it works whatever language your entity_ids were created in.

It shows an animated grid → charger → car flow (the pulse speeds up with the
power), the live kW with voltage and current, a day/night tariff chip with the
current price, session cost/energy/duration, this month's cost and energy split
into day and night, a slider plus 6/10/16/20/32 A presets for the charging
current (presets above your maximum are hidden), a re-apply button, a Start/Stop
button and the box and plug temperatures (the chip turns red above 60 °C). Tapping a tile opens the entity's history.

Options, all optional:

```yaml
type: custom:eveus-flow-card
title: Garage charger      # default: the device name
device: 1a2b3c…            # device id, if you have more than one charger
prefix: eveus              # fallback entity_id prefix
entities:                  # override individual entities
  limit: number.eveus_charging_current
  enabled: switch.eveus_charging_enabled
```

If the card does not appear after updating, empty the browser cache
(Ctrl+Shift+R) so the new JavaScript is loaded.

## Cars that stay at 6 A

Many cars read the charger's limit only once, when the cable is plugged in, and
some ignore it then — so a car plugged in with a 13 A limit keeps charging at
6 A, while changing the limit *after* it is connected works immediately.

The integration handles this: whenever a charge is about to start — the cable is
plugged in, delayed charging kicks in, you press Stop and then Start, or the
charger itself comes back (switched on at the socket, rebooted, or Home
Assistant restarted) while a car is already connected — it
waits (15 s by default), steps the limit up by 1 A (down, if it is already at
your maximum), waits three seconds and writes the original value back. A minute
later it checks the measured current, and if the car is still drawing far less
than allowed it tries once more (up to three attempts per charge). The change is what the car reacts
to. Turn it off, or change the delay, under **Configure**; the
*Re-apply current* button (and the ⟳ button on the card) does the same on demand.

## Stopping a charge and unplugging

The connector lock is not something the charger can open: on Type 2 the locking
pin sits in the car's inlet and only the car releases it, usually when the
session has ended and the car is unlocked.

What the integration can do is end the session cleanly. *End charging session*
(and the Stop button on the card) writes `evseEnabled=1`, which removes the
signal to the car; the car finishes the session and then allows the plug to come
out. Once the charger reports that the cable is gone, the integration writes
`evseEnabled=0` again so the next plug-in starts normally — otherwise the
charger would stay disabled. If the cable is never unplugged, it re-arms after
30 minutes anyway.

If the plug still will not come out, it is the car holding it: unlock the car
(or use its own unlock button / app), and check its "unlock when charging
stops" setting.

## Tips

**Daily / weekly cost** – monthly is built in, for other periods use utility meters:

```yaml
utility_meter:
  ev_cost_daily:
    source: sensor.eveus_total_cost
    cycle: daily
```

**Energy dashboard** – add *Total energy* as an individual device and pick
*Use an entity with current price* → `sensor.eveus_current_price`.

**Cheap-hours automation** – use `sensor.eveus_current_tariff` (`day`/`night`)
with `switch.eveus_charging_enabled`.

## Upgrading from 1.x

Version 1.x read the energy from another integration's sensors. Version 2 talks
to the charger itself, so an old entry cannot be migrated: delete it and add the
integration again with the charger's IP address. The `ha-evse-charger`
integration can then be removed.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```
