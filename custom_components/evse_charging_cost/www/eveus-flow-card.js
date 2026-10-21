/**
 * Eveus flow card — live charging flow, costs and current control.
 *
 * Minimal config:
 *   type: custom:eveus-flow-card
 *
 * Full config:
 *   type: custom:eveus-flow-card
 *   prefix: eveus            # entity_id prefix, e.g. sensor.eveus_power
 *   title: Garage charger    # optional, defaults to the device name
 *   entities:                # optional per-entity overrides
 *     power: sensor.eveus_power
 */

const FLOW_CARD_VERSION = "2.14.0";

// translation_key of each entity, used to find it in the entity registry no
// matter which language the entity_ids were generated in.
const TKEYS = {
  status: "status",
  power: "power",
  voltage: "voltage_l1",
  current: "current_l1",
  session_energy: "session_energy",
  session_time: "session_time",
  session_cost: "session_cost",
  month_cost: "month_cost",
  month_energy: "month_energy",
  month_day: "month_day_energy",
  month_night: "month_night_energy",
  tariff: "current_tariff",
  price: "current_price",
  plug_temperature: "plug_temperature",
  box_temperature: "box_temperature",
  limit: "current_limit",
  enabled: "charging_enabled",
  reapply: "reapply_current",
  end_session: "end_session",
};

const PLATFORM = "evse_charging_cost";

const KEYS = {
  status: "sensor.{p}_status",
  power: "sensor.{p}_power",
  voltage: "sensor.{p}_voltage_l1",
  current: "sensor.{p}_current_l1",
  session_energy: "sensor.{p}_session_energy",
  session_time: "sensor.{p}_session_time",
  session_cost: "sensor.{p}_session_cost",
  month_cost: "sensor.{p}_current_month_cost",
  month_energy: "sensor.{p}_current_month_energy",
  month_day: "sensor.{p}_energy_this_month_day",
  month_night: "sensor.{p}_energy_this_month_night",
  tariff: "sensor.{p}_current_tariff",
  price: "sensor.{p}_current_price",
  plug_temperature: "sensor.{p}_plug_temperature",
  box_temperature: "sensor.{p}_box_temperature",
  limit: "number.{p}_charging_current",
  enabled: "switch.{p}_charging_enabled",
  reapply: "button.{p}_reapply_current",
  end_session: "button.{p}_end_charging_session",
};

const LABELS = {
  en: {
    grid: "Grid", charger: "Charger", car: "Car", no_car: "Not connected",
    session: "Session", month: "This month", day: "Day", night: "Night",
    this_month: "this month", start: "Start", stop: "Stop",
    box: "Box", plug: "Plug", reapply: "Re-apply current",
    fallback_title: "EV charger", missing: 'No entities found for prefix "{p}"',
  },
  uk: {
    grid: "Мережа", charger: "Станція", car: "Авто", no_car: "Не підключено",
    session: "Сесія", month: "Цей місяць", day: "День", night: "Ніч",
    this_month: "цього місяця", start: "Пуск", stop: "Стоп",
    box: "Корпус", plug: "Роз'єм", reapply: "Перезадати струм",
    fallback_title: "Зарядна станція", missing: 'Не знайдено сутностей для префікса "{p}"',
  },
};

const CHARGING_STATES = new Set(["charging"]);
const CONNECTED_STATES = new Set(["charging", "car_connected", "charging_complete"]);

const css = `
:host { --flow-accent: var(--primary-color, #03a9f4); }
ha-card { padding: 16px; overflow: hidden; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.title { font-size: 1.1rem; font-weight: 600; }
.chip {
  font-size: .75rem; padding: 3px 10px; border-radius: 999px; white-space: nowrap;
  background: var(--secondary-background-color); color: var(--secondary-text-color);
}
.chip.on { background: rgba(3, 169, 244, .22); color: var(--flow-accent); }
.chip.on { background: color-mix(in srgb, var(--flow-accent) 22%, transparent); }
.chip.night { background: rgba(92, 107, 192, .24); color: #7986cb; }
.chip.warn { background: rgba(219, 68, 55, .2); color: var(--error-color, #db4437); }

.flow { display: flex; align-items: flex-start; justify-content: space-between;
  gap: 4px; margin: 10px 0 2px; }
.node { display: flex; flex-direction: column; align-items: center; gap: 6px; width: 76px; }
.ring { width: 56px; height: 56px; border-radius: 50%; box-sizing: border-box;
  border: 2px solid var(--divider-color, #cfd8dc); display: flex; align-items: center;
  justify-content: center; }
.node.active .ring { border-color: var(--flow-accent); }
.node ha-icon { --mdc-icon-size: 26px; width: 26px; height: 26px; display: block;
  color: var(--secondary-text-color); }
.node.active ha-icon { color: var(--flow-accent); }
.node .label { font-size: .72rem; color: var(--secondary-text-color); text-align: center;
  line-height: 1.2; }
.link { flex: 1; height: 3px; margin-top: 26px; border-radius: 2px; position: relative;
  background: var(--divider-color, #cfd8dc); overflow: hidden; }
.link .dash { position: absolute; top: 0; bottom: 0; left: -28px; width: calc(100% + 28px);
  background-image: repeating-linear-gradient(90deg, var(--flow-accent) 0 12px,
    transparent 12px 28px);
  animation: flow var(--flow-speed, 2.6s) linear infinite;
  will-change: transform; }
@keyframes flow { from { transform: translateX(0); } to { transform: translateX(28px); } }
.bigwrap { text-align: center; margin-top: 12px; }
.bigwrap .big, .bigwrap .sub span { cursor: pointer; }
.big { font-size: 2rem; font-weight: 600; line-height: 1.1; }
.big small { font-size: .95rem; font-weight: 400; color: var(--secondary-text-color); margin-left: 4px; }
.sub { color: var(--secondary-text-color); font-size: .85rem; }

.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 10px; margin-top: 14px; }
.cell { background: var(--secondary-background-color); border-radius: 12px; padding: 10px 12px; cursor: pointer; }
.cell .k { font-size: .72rem; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .03em; }
.cell .v { font-size: 1.05rem; font-weight: 600; margin-top: 2px; }
.cell .x { font-size: .72rem; color: var(--secondary-text-color); }

.temps { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.temps .chip { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.temps ha-icon { --mdc-icon-size: 16px; width: 16px; height: 16px; }
.temps .chip.hot { background: rgba(219, 68, 55, .18); color: var(--error-color, #db4437); }

.controls { margin-top: 16px; }
.row { display: flex; align-items: center; gap: 12px; }
.amp { font-size: 1.05rem; font-weight: 600; min-width: 46px; text-align: right; }
input[type=range] { -webkit-appearance: none; appearance: none; flex: 1; height: 6px; border-radius: 3px;
  background: var(--secondary-background-color); outline: none; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%;
  background: var(--flow-accent); cursor: pointer; border: 3px solid var(--card-background-color, #fff);
  box-shadow: 0 1px 4px rgba(0,0,0,.3); }
input[type=range]::-moz-range-thumb { width: 18px; height: 18px; border-radius: 50%; background: var(--flow-accent);
  cursor: pointer; border: 3px solid var(--card-background-color, #fff); }
input[type=range]:disabled { opacity: .5; }
button:disabled { opacity: .45; cursor: default; filter: none; }
.presets { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
button { font: inherit; border: none; border-radius: 10px; padding: 7px 14px; cursor: pointer;
  background: var(--secondary-background-color); color: var(--primary-text-color); }
button:hover { filter: brightness(1.08); }
button.sel { background: var(--flow-accent); color: var(--text-primary-color, #fff); }
button.icon-btn { padding: 7px 10px; margin-left: auto; }
button.stop { margin-left: 8px; background: rgba(219, 68, 55, .18); color: var(--error-color, #db4437); }
button.start { margin-left: 8px; background: rgba(67, 160, 71, .18); color: var(--success-color, #43a047); }
button.icon-btn + button { margin-left: 0; }
button.icon-btn ha-icon { --mdc-icon-size: 18px; width: 18px; height: 18px; display: block; }
.missing { color: var(--error-color, #db4437); font-size: .85rem; }
`;

/** Set a style property only when it changes, so animations are not restarted. */
function _set(el, prop, value) {
  if (el.style[prop] !== value) el.style[prop] = value;
}

function _setVar(el, name, value) {
  if (el.style.getPropertyValue(name) !== value) el.style.setProperty(name, value);
}

/** Replace innerHTML only when the markup changed, to avoid layout thrash. */
function _html(el, markup) {
  if (el._last === markup) return false;
  el._last = markup;
  el.innerHTML = markup;
  return true;
}

class EveusFlowCard extends HTMLElement {
  static getStubConfig() {
    return { prefix: "eveus" };
  }

  setConfig(config) {
    this._config = { prefix: "eveus", entities: {}, ...config };
    this._ids = {};
    this._resolved = false;
    this._root = this._root || this.attachShadow({ mode: "open" });
    this._built = false;
  }

  /**
   * Find the charger's entities. The registry is authoritative (entity_ids are
   * generated from translated names, so they differ per language); the prefix
   * patterns are only a fallback.
   */
  _resolve() {
    const ids = {};
    const registry = this._hass.entities || {};
    const wanted = this._config.device;
    for (const [entityId, entry] of Object.entries(registry)) {
      if (entry.platform !== PLATFORM) continue;
      if (wanted && entry.device_id !== wanted) continue;
      for (const [key, tkey] of Object.entries(TKEYS)) {
        if (entry.translation_key === tkey && !ids[key]) ids[key] = entityId;
      }
    }
    for (const [key, pattern] of Object.entries(KEYS)) {
      const fallback = pattern.replace("{p}", this._config.prefix);
      ids[key] =
        this._config.entities[key] ||
        ids[key] ||
        (this._hass.states[fallback] ? fallback : ids[key] || fallback);
    }
    this._ids = ids;
    this._resolved = Boolean(ids.status || ids.limit);
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Home Assistant sets hass before setConfig in some code paths.
    if (!this._config) return;
    try {
      if (first || !this._resolved) this._resolve();
      if (!this._built) this._build();
      this._render();
    } catch (err) {
      console.error("eveus-flow-card:", err);
      this._fail(err);
    }
  }

  /** Show the problem inside the card instead of leaving it blank. */
  _fail(err) {
    const title = this._built && this._root.querySelector(".title");
    if (title) {
      title.innerHTML = `<span class="missing">${err.message || err}</span>`;
      return;
    }
    this._root.innerHTML = `<style>${css}</style>
      <ha-card><div class="missing" style="padding:16px">
        eveus-flow-card: ${err.message || err}
      </div></ha-card>`;
  }

  // ---------------------------------------------------------------- helpers

  get _t() {
    const lang = (this._hass && this._hass.language) || "en";
    return LABELS[lang.slice(0, 2)] || LABELS.en;
  }

  _st(key) {
    return this._hass && this._hass.states[this._ids[key]];
  }

  _num(key) {
    const s = this._st(key);
    const v = s ? Number(s.state) : NaN;
    return Number.isFinite(v) ? v : null;
  }

  _unit(key) {
    const s = this._st(key);
    return (s && s.attributes.unit_of_measurement) || "";
  }

  _label(key) {
    const s = this._st(key);
    if (!s) return "—";
    try {
      // Must stay bound to hass — calling a detached reference throws.
      return this._hass.formatEntityState
        ? this._hass.formatEntityState(s)
        : s.state;
    } catch (err) {
      return s.state;
    }
  }

  _fmt(value, digits = 2) {
    return value === null ? "—" : value.toLocaleString(this._hass.locale?.language, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  /** kWh actually billed in this session (what the cost figure is based on). */
  _billed() {
    const cost = this._st("session_cost");
    const billed = cost && Number(cost.attributes.energy_kwh);
    return Number.isFinite(billed) ? billed : this._num("session_energy");
  }

  _duration(seconds) {
    if (seconds === null) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h ? `${h} h ${m} min` : `${m} min`;
  }

  _more(key) {
    const id = this._ids[key];
    if (!id || !this._hass.states[id]) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId: id },
        bubbles: true,
        composed: true,
      })
    );
  }

  // ------------------------------------------------------------------ build

  _build() {
    this._root.innerHTML = `
      <style>${css}</style>
      <ha-card>
        <div class="head">
          <div class="title"></div>
          <div class="chips">
            <span class="chip tariff"></span>
            <span class="chip status"></span>
          </div>
        </div>

        <div class="flow">
          <div class="node source">
            <div class="ring"><ha-icon icon="mdi:transmission-tower"></ha-icon></div>
            <span class="label source-label">Grid</span>
          </div>
          <div class="link l1"><span class="dash"></span></div>
          <div class="node station">
            <div class="ring"><ha-icon icon="mdi:ev-station"></ha-icon></div>
            <span class="label station-label">Charger</span>
          </div>
          <div class="link l2"><span class="dash"></span></div>
          <div class="node car">
            <div class="ring"><ha-icon icon="mdi:car-electric"></ha-icon></div>
            <span class="label car-label">Car</span>
          </div>
        </div>

        <div class="bigwrap">
          <div class="big"></div>
          <div class="sub"></div>
        </div>

        <div class="metrics"></div>
        <div class="temps"></div>

        <div class="controls">
          <div class="row">
            <ha-icon icon="mdi:current-ac"></ha-icon>
            <input type="range" min="6" max="32" step="1" />
            <span class="amp"></span>
          </div>
          <div class="presets"></div>
        </div>
      </ha-card>
    `;

    const slider = this._root.querySelector("input[type=range]");
    slider.addEventListener("input", () => {
      this._pending = Number(slider.value);
      this._root.querySelector(".amp").textContent = `${slider.value} A`;
    });
    slider.addEventListener("change", () => this._setCurrent(Number(slider.value)));

    this._root
      .querySelector(".metrics")
      .addEventListener("click", (event) => {
        const cell = event.target.closest(".cell");
        if (cell) this._more(cell.dataset.key);
      });

    this._root.querySelector(".bigwrap").addEventListener("click", (event) => {
      const target = event.target.closest("[data-key]");
      this._more(target ? target.dataset.key : "power");
    });

    this._root.querySelector(".temps").addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (chip) this._more(chip.dataset.key);
    });

    this._built = true;
  }

  // ----------------------------------------------------------------- render

  _render() {
    const status = this._st("status");
    const state = status ? status.state : null;
    const offline =
      !status || status.state === "unavailable" || status.state === "unknown";
    const charging = CHARGING_STATES.has(state);
    const connected = CONNECTED_STATES.has(state);
    const power = this._num("power");
    const limit = this._st("limit");

    const card = this._root.querySelector("ha-card");
    if (!status && !limit) {
      card.querySelector(".title").innerHTML = `<span class="missing">${this._t.missing.replace(
        "{p}",
        this._config.prefix
      )}</span>`;
      return;
    }

    card.querySelector(".title").textContent =
      this._config.title ||
      (status && status.attributes.friendly_name
        ? status.attributes.friendly_name.replace(/\s+\S+$/, "")
        : this._t.fallback_title);

    // chips
    const statusChip = card.querySelector(".chip.status");
    statusChip.textContent = this._label("status");
    statusChip.className = `chip status${charging ? " on" : ""}${
      state === "error" || offline ? " warn" : ""
    }`;

    const tariff = this._st("tariff");
    const tariffChip = card.querySelector(".chip.tariff");
    if (tariff) {
      const price = this._num("price");
      tariffChip.textContent = `${this._label("tariff")} · ${this._fmt(price)} ${this._unit(
        "price"
      )}`;
      tariffChip.className = `chip tariff${tariff.state === "night" ? " night" : ""}`;
      tariffChip.style.display = "";
    } else {
      tariffChip.style.display = "none";
    }

    // flow: the charger is live unless it is switched off or in error, the car
    // node lights up whenever a car is plugged in, and the second segment only
    // animates while energy is actually flowing into the car.
    const off =
      offline ||
      state === "disabled" ||
      state === "error" ||
      (this._st("enabled") && this._st("enabled").state === "off");
    const live = !off;
    const flowing = live && charging && Boolean(power);

    const p1 = card.querySelector(".l1 .dash");
    const p2 = card.querySelector(".l2 .dash");
    const speed = `${Math.max(0.45, 2.6 - (power || 0) / 4000).toFixed(2)}s`;
    _set(p1, "display", live ? "" : "none");
    _set(p2, "display", flowing ? "" : "none");
    // Writing the same value again would restart the animation mid-stride.
    _setVar(p1, "--flow-speed", flowing ? speed : "2.60s");
    _setVar(p2, "--flow-speed", speed);

    card.querySelector(".node.source").classList.toggle("active", live);
    card.querySelector(".node.station").classList.toggle("active", live);
    card.querySelector(".node.car").classList.toggle("active", live && connected);
    card.querySelector(".source-label").textContent = this._t.grid;
    card.querySelector(".station-label").textContent = this._t.charger;
    card.querySelector(".car-label").textContent =
      offline || connected ? this._t.car : this._t.no_car;

    const kw = power !== null ? power / 1000 : null;
    card.querySelector(".big").innerHTML = `${this._fmt(
      kw === null ? 0 : kw,
      kw !== null && kw >= 10 ? 1 : 2
    )}<small>kW</small>`;
    // Keep voltage and current on screen even when the charger is unreachable
    // (they read 0), so they stay one tap away from their history.
    const volt = this._num("voltage");
    const amps = this._num("current");
    _html(
      card.querySelector(".sub"),
      `<span data-key="voltage">${this._fmt(volt === null ? 0 : volt, 0)} V</span>` +
        ` · <span data-key="current">${this._fmt(
          amps === null ? 0 : amps,
          1
        )} A</span>`
    );

    // metrics
    const cells = [
      {
        key: "session_cost",
        k: this._t.session,
        v: `${this._fmt(this._num("session_cost"))} ${this._unit("session_cost")}`,
        x: `${this._fmt(this._billed())} kWh · ${this._duration(
          this._num("session_time")
        )}`,
      },
      {
        key: "month_cost",
        k: this._t.month,
        v: `${this._fmt(this._num("month_cost"))} ${this._unit("month_cost")}`,
        x: `${this._fmt(this._num("month_energy"))} kWh`,
      },
      {
        key: "month_day",
        k: this._t.day,
        v: `${this._fmt(this._num("month_day"))} kWh`,
        x: this._t.this_month,
      },
      {
        key: "month_night",
        k: this._t.night,
        v: `${this._fmt(this._num("month_night"))} kWh`,
        x: this._t.this_month,
      },
    ].filter((cell) => this._st(cell.key));

    _html(
      card.querySelector(".metrics"),
      cells
      .map(
        (c) => `<div class="cell" data-key="${c.key}">
                  <div class="k">${c.k}</div>
                  <div class="v">${c.v}</div>
                  <div class="x">${c.x}</div>
                </div>`
      )
      .join("")
    );

    // temperatures
    const temps = [
      { key: "box_temperature", label: this._t.box, icon: "mdi:thermometer" },
      { key: "plug_temperature", label: this._t.plug, icon: "mdi:ev-plug-type2" },
    ].filter((t) => this._st(t.key) && this._num(t.key) !== null);

    _html(
      card.querySelector(".temps"),
      temps
      .map(
        (t) => `<span class="chip${this._num(t.key) >= 60 ? " hot" : ""}" data-key="${t.key}">
                  <ha-icon icon="${t.icon}"></ha-icon>${t.label} ${this._fmt(
                    this._num(t.key),
                    0
                  )} ${this._unit(t.key) || "°C"}
                </span>`
      )
      .join("")
    );

    // current control
    const slider = card.querySelector("input[type=range]");
    const controls = card.querySelector(".controls");
    if (!limit) {
      controls.style.display = "none";
      return;
    }
    controls.style.display = "";
    const min = Number(limit.attributes.min ?? 6);
    const max = Number(limit.attributes.max ?? 32);
    slider.min = min;
    slider.max = max;
    const unreachable = offline || !Number.isFinite(Number(limit.state));
    slider.disabled = unreachable;
    const value = this._pending ?? Number(limit.state);
    if (Number.isFinite(value)) {
      slider.value = value;
      card.querySelector(".amp").textContent = `${Math.round(value)} A`;
    } else {
      card.querySelector(".amp").textContent = "—";
    }

    const presets = [6, 10, 16, 20, 32].filter((a) => a >= min && a <= max);
    const enabled = this._st("enabled");
    const running = enabled && enabled.state === "on";
    const presetsHtml =
      presets
        .map(
          (a) =>
            `<button data-amp="${a}" class="${
              Math.round(value) === a ? "sel" : ""
            }">${a} A</button>`
        )
        .join("") +
      (this._st("reapply")
        ? `<button class="icon-btn" data-reapply="1" title="${this._t.reapply}"
                   aria-label="${this._t.reapply}">
             <ha-icon icon="mdi:refresh-auto"></ha-icon>
           </button>`
        : "") +
      (enabled
        ? `<button class="${running ? "stop" : "start"}" data-toggle="1">
             ${running ? this._t.stop : this._t.start}
           </button>`
        : "");

    if (_html(card.querySelector(".presets"), presetsHtml)) {
      for (const button of card.querySelectorAll(".presets button")) {
        button.onclick = () => {
          if (button.dataset.toggle) this._toggle(running);
          else if (button.dataset.reapply) this._reapply();
          else this._setCurrent(Number(button.dataset.amp));
        };
      }
    }
    // availability is not part of the markup, so apply it every time
    for (const button of card.querySelectorAll(".presets button")) {
      button.disabled = unreachable;
    }
  }

  // --------------------------------------------------------------- services

  _setCurrent(value) {
    this._pending = value;
    clearTimeout(this._clear);
    this._clear = setTimeout(() => {
      this._pending = null;
    }, 4000);
    this._hass.callService("number", "set_value", {
      entity_id: this._ids.limit,
      value,
    });
  }

  _toggle(running) {
    // Stopping goes through the end-session button when it exists: it also
    // re-arms the charger once the cable is unplugged.
    if (running && this._st("end_session")) {
      this._hass.callService("button", "press", {
        entity_id: this._ids.end_session,
      });
      return;
    }
    this._hass.callService("switch", "toggle", { entity_id: this._ids.enabled });
  }

  _reapply() {
    this._hass.callService("button", "press", { entity_id: this._ids.reapply });
  }

}

// The file can be loaded twice (registered by the integration and added as a
// Lovelace resource by hand); defining the element again would throw.
if (!customElements.get("eveus-flow-card")) {
  customElements.define("eveus-flow-card", EveusFlowCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "eveus-flow-card",
    name: "Eveus flow card",
    description: "Charging flow, costs and current control for an Eveus charger",
    preview: false,
  });
}

console.info(`%c EVEUS-FLOW-CARD %c ${FLOW_CARD_VERSION} `,
  "color:#fff;background:#03a9f4;font-weight:700", "color:#03a9f4;background:#fff");
