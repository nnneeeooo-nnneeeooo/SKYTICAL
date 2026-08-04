/* AVWIRE Taiwan civil-flight radar.
 *
 * One browser-side Airplanes.live point query every five minutes. The page
 * stores no aircraft positions and filters source-tagged sensitive records
 * before creating any marker or list row.
 */
(function () {
  "use strict";

  const root = document.getElementById("flight-radar");
  if (!root) return;

  const lang = root.dataset.lang === "en" ? "en" : "zh";
  const copy = {
    zh: {
      live: "資料正常", loading: "正在取得最新 ADS-B 觀測資料…",
      error: "目前無法取得航機資料，將保留上次成功畫面並稍後再試。",
      noData: "目前篩選條件下沒有可顯示的民航機。",
      shown: (visible, total, hidden) =>
        `顯示 ${visible} 架｜有效民航 ${total} 架｜安全與品質過濾 ${hidden} 筆`,
      updated: (time) => `資料時間 ${time}`,
      next: (seconds) => `下次更新 ${seconds} 秒`,
      cooldown: (seconds) => `請於 ${seconds} 秒後再手動更新`,
      callsign: "航班代碼", airline: "航空公司", type: "機型",
      route: "起迄點",
      altitude: "高度", speed: "地速", heading: "航向",
      vertical: "垂直速率", freshness: "位置新鮮度",
      ground: "地面", unknown: "未提供", feet: "呎", knots: "節",
      fpm: "呎／分", seconds: "秒前", noCallsign: "無航班代碼",
    },
    en: {
      live: "Data live", loading: "Loading the latest ADS-B observations…",
      error: "Aircraft data is unavailable. The last successful view is retained and the page will retry.",
      noData: "No civil aircraft match the current filters.",
      shown: (visible, total, hidden) =>
        `Showing ${visible} | valid civil ${total} | safety/quality filtered ${hidden}`,
      updated: (time) => `Data time ${time}`,
      next: (seconds) => `Next refresh ${seconds}s`,
      cooldown: (seconds) => `Manual refresh available in ${seconds}s`,
      callsign: "Flight code", airline: "Airline", type: "Aircraft",
      route: "Route",
      altitude: "Altitude", speed: "Ground speed", heading: "Heading",
      vertical: "Vertical rate", freshness: "Position age",
      ground: "Ground", unknown: "Not reported", feet: "ft", knots: "kt",
      fpm: "ft/min", seconds: "s ago", noCallsign: "No flight code",
    },
  }[lang];

  const parseJson = (id, fallback) => {
    try {
      return JSON.parse(document.getElementById(id).textContent);
    } catch (_) {
      return fallback;
    }
  };
  const airlines = parseJson("radar-airlines", {});
  const airlineIataCodes = parseJson("radar-airline-codes", {});
  const aircraftTypes = parseJson("radar-types", {});
  const airports = parseJson("radar-airports", []);
  const refreshMs = Math.max(Number(root.dataset.refreshMs) || 300000, 300000);
  const manualCooldownMs = 30000;
  const routeApiBase = String(root.dataset.routeApiUrl || "").replace(/\/+$/, "");
  const routeCacheKey = "avwire-radar-routes-v1";
  const callsignModeKey = "avwire-radar-callsign-mode";
  const routePositiveTtlMs = 24 * 60 * 60 * 1000;
  const routeNegativeTtlMs = 6 * 60 * 60 * 1000;
  const routeConcurrency = 4;
  const routeCacheLimit = 400;

  const stateEl = document.getElementById("radar-state");
  const countEl = document.getElementById("radar-count");
  const updatedEl = document.getElementById("radar-updated");
  const countdownEl = document.getElementById("radar-countdown");
  const listEl = document.getElementById("radar-list");
  const searchEl = document.getElementById("radar-search");
  const airborneEl = document.getElementById("radar-airborne");
  const refreshEl = document.getElementById("radar-refresh");
  const callsignModeEls = Array.from(
    document.querySelectorAll("[data-callsign-mode]"));

  let map;
  let aircraftLayer;
  let currentRows = [];
  let sourceRows = 0;
  let hiddenRows = 0;
  let nextRefreshAt = Date.now() + refreshMs;
  let lastRequestAt = 0;
  let inFlight = false;
  let loadGeneration = 0;
  const defaultCallsignMode =
    root.dataset.defaultCallsignMode === "icao" ? "icao" : "iata";
  const savedCallsignMode = readStorage(callsignModeKey);
  let callsignMode = ["icao", "iata"].includes(savedCallsignMode) ?
    savedCallsignMode : defaultCallsignMode;
  let routeCache = loadRouteCache();

  const numberOrNull = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const clean = (value, maxLength) =>
    String(value == null ? "" : value).trim().slice(0, maxLength);

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_) {
      // Storage can be disabled; the live view must continue without caching.
    }
  }

  function loadRouteCache() {
    try {
      const parsed = JSON.parse(readStorage(routeCacheKey) || "{}");
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ?
        parsed : {};
    } catch (_) {
      return {};
    }
  }

  function saveRouteCache() {
    const now = Date.now();
    const entries = Object.entries(routeCache)
      .filter(([, value]) => value && Number(value.expiresAt) > now)
      .sort((a, b) => Number(b[1].savedAt) - Number(a[1].savedAt))
      .slice(0, routeCacheLimit);
    routeCache = Object.fromEntries(entries);
    writeStorage(routeCacheKey, JSON.stringify(routeCache));
  }

  function isSensitiveOrStale(ac) {
    if (!ac || typeof ac !== "object") return true;
    const hex = clean(ac.hex, 16);
    if (!hex || hex.startsWith("~")) return true;
    const flags = Number(ac.dbFlags) || 0;
    if (flags & (1 | 4 | 8)) return true; // military, PIA, LADD
    if (["7500", "7600", "7700"].includes(clean(ac.squawk, 8))) return true;
    const emergency = clean(ac.emergency, 24).toLowerCase();
    if (emergency && emergency !== "none") return true;
    if (clean(ac.type, 24).toLowerCase() === "adsb_icao_nt") return true;
    const lat = numberOrNull(ac.lat);
    const lon = numberOrNull(ac.lon);
    const seenPos = numberOrNull(ac.seen_pos);
    const seen = numberOrNull(ac.seen);
    if (lat === null || lon === null || seenPos === null || seenPos > 30) return true;
    if (seen !== null && seen > 60) return true;
    return false;
  }

  function normalize(ac) {
    const callsign = clean(ac.flight, 16).toUpperCase();
    const operator = /^[A-Z]{3}/.test(callsign) ? callsign.slice(0, 3) : "";
    const typeCode = clean(ac.t, 12).toUpperCase();
    const altitude = ac.alt_baro === "ground" ? "ground" : numberOrNull(ac.alt_baro);
    return {
      key: clean(ac.hex, 16),
      callsign,
      operator,
      airline: airlines[operator] || "",
      typeCode,
      typeName: aircraftTypes[typeCode] || "",
      lat: Number(ac.lat),
      lon: Number(ac.lon),
      altitude,
      speed: numberOrNull(ac.gs),
      heading: numberOrNull(ac.track),
      verticalRate: numberOrNull(ac.baro_rate != null ? ac.baro_rate : ac.geom_rate),
      seenPos: numberOrNull(ac.seen_pos),
      route: null,
    };
  }

  function displayCallsign(row) {
    if (callsignMode === "iata") {
      if (row.route && row.route.callsignIata) return row.route.callsignIata;
      const iataPrefix = clean(airlineIataCodes[row.operator], 3).toUpperCase();
      if (iataPrefix && row.callsign.startsWith(row.operator)) {
        return `${iataPrefix}${row.callsign.slice(row.operator.length)}`;
      }
    }
    return row.callsign;
  }

  function airportCode(airport) {
    if (!airport) return "";
    return airport.iata || airport.icao || "";
  }

  function formatRoute(row) {
    if (!row.route) return "";
    const origin = airportCode(row.route.origin);
    const destination = airportCode(row.route.destination);
    return origin && destination ? `${origin}–${destination}` : "";
  }

  function normalizeAirport(value) {
    if (!value || typeof value !== "object") return null;
    const iata = clean(value.iata_code, 4).toUpperCase();
    const icao = clean(value.icao_code, 5).toUpperCase();
    if (!iata && !icao) return null;
    return {
      iata,
      icao,
      name: clean(value.name, 100),
    };
  }

  function normalizeRoutePayload(payload) {
    const flightroute = payload && payload.response &&
      payload.response.flightroute;
    if (!flightroute || typeof flightroute !== "object") return null;
    const origin = normalizeAirport(flightroute.origin);
    const destination = normalizeAirport(flightroute.destination);
    if (!origin || !destination) return null;
    return {
      callsignIcao: clean(flightroute.callsign_icao, 16).toUpperCase(),
      callsignIata: clean(flightroute.callsign_iata, 16).toUpperCase(),
      origin,
      destination,
    };
  }

  function cachedRoute(callsign) {
    const entry = routeCache[callsign];
    if (!entry || Number(entry.expiresAt) <= Date.now()) {
      delete routeCache[callsign];
      return { hit: false, route: null };
    }
    return { hit: true, route: entry.route || null };
  }

  function rememberRoute(callsign, route) {
    const now = Date.now();
    routeCache[callsign] = {
      route,
      savedAt: now,
      expiresAt: now + (route ? routePositiveTtlMs : routeNegativeTtlMs),
    };
  }

  async function fetchRoute(callsign) {
    if (!routeApiBase || !/^[A-Z0-9]{3,12}$/.test(callsign)) {
      return { cacheable: true, route: null };
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(
        `${routeApiBase}/${encodeURIComponent(callsign)}`, {
          method: "GET",
          mode: "cors",
          credentials: "omit",
          cache: "default",
          signal: controller.signal,
        });
      if (response.status === 404) return { cacheable: true, route: null };
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return {
        cacheable: true,
        route: normalizeRoutePayload(await response.json()),
      };
    } catch (_) {
      return { cacheable: false, route: null };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function hydrateRoutes(rows, generation) {
    const byCallsign = new Map();
    rows.forEach((row) => {
      if (/^[A-Z]{3}[A-Z0-9]{1,9}$/.test(row.callsign)) {
        if (!byCallsign.has(row.callsign)) byCallsign.set(row.callsign, []);
        byCallsign.get(row.callsign).push(row);
      }
    });

    const pending = [];
    let changed = false;
    byCallsign.forEach((matchingRows, callsign) => {
      const cached = cachedRoute(callsign);
      if (!cached.hit) {
        pending.push(callsign);
        return;
      }
      matchingRows.forEach((row) => { row.route = cached.route; });
      changed = changed || Boolean(cached.route);
    });
    if (changed && generation === loadGeneration) render();

    let cursor = 0;
    async function worker() {
      while (cursor < pending.length) {
        const callsign = pending[cursor++];
        const result = await fetchRoute(callsign);
        if (!result.cacheable) continue;
        rememberRoute(callsign, result.route);
        (byCallsign.get(callsign) || []).forEach((row) => {
          row.route = result.route;
        });
        changed = changed || Boolean(result.route);
      }
    }
    const workerCount = Math.min(routeConcurrency, pending.length);
    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    if (pending.length) saveRouteCache();
    if (changed && generation === loadGeneration) render();
  }

  function setCallsignMode(mode, persist) {
    callsignMode = mode === "iata" ? "iata" : "icao";
    callsignModeEls.forEach((button) => {
      const active = button.dataset.callsignMode === callsignMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (persist) writeStorage(callsignModeKey, callsignMode);
    if (aircraftLayer) render();
  }

  function formatAltitude(row) {
    if (row.altitude === "ground") return copy.ground;
    return row.altitude === null ? copy.unknown :
      `${Math.round(row.altitude).toLocaleString()} ${copy.feet}`;
  }

  function formatNumber(value, unit) {
    return value === null ? copy.unknown :
      `${Math.round(value).toLocaleString()} ${unit}`;
  }

  function addDetail(container, label, value) {
    const row = document.createElement("div");
    row.className = "radar-popup-row";
    const key = document.createElement("span");
    key.className = "text-muted";
    key.textContent = label;
    const val = document.createElement("b");
    val.textContent = value;
    row.append(key, val);
    container.appendChild(row);
  }

  function popupFor(row) {
    const box = document.createElement("div");
    box.className = "radar-popup";
    const title = document.createElement("strong");
    title.className = "radar-popup-title";
    title.textContent = displayCallsign(row) || copy.noCallsign;
    box.appendChild(title);
    const route = formatRoute(row);
    addDetail(box, copy.route, route || copy.unknown);
    addDetail(box, copy.airline, row.airline || copy.unknown);
    addDetail(box, copy.type,
      [row.typeCode, row.typeName].filter(Boolean).join(" · ") || copy.unknown);
    addDetail(box, copy.altitude, formatAltitude(row));
    addDetail(box, copy.speed, formatNumber(row.speed, copy.knots));
    addDetail(box, copy.heading,
      row.heading === null ? copy.unknown : `${Math.round(row.heading)}°`);
    addDetail(box, copy.vertical, formatNumber(row.verticalRate, copy.fpm));
    addDetail(box, copy.freshness,
      row.seenPos === null ? copy.unknown : `${Math.round(row.seenPos)} ${copy.seconds}`);
    return box;
  }

  function planeIcon(row) {
    const heading = row.heading === null ? 0 :
      ((row.heading % 360) + 360) % 360;
    const ground = row.altitude === "ground" ? " ground" : "";
    return L.divIcon({
      className: "radar-plane-wrap",
      html: `<span class="radar-plane${ground}" style="--heading:${heading}deg">▲</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
  }

  function rowMatches(row, query, airborneOnly) {
    if (airborneOnly && row.altitude === "ground") return false;
    if (!query) return true;
    return [
      row.callsign, displayCallsign(row), formatRoute(row), row.operator,
      row.airline, row.typeCode, row.typeName,
    ].some((value) => value.toUpperCase().includes(query));
  }

  function render() {
    const query = searchEl.value.trim().toUpperCase();
    const rows = currentRows.filter((row) =>
      rowMatches(row, query, airborneEl.checked));
    aircraftLayer.clearLayers();
    listEl.replaceChildren();

    rows.sort((a, b) =>
      (displayCallsign(a) || "ZZZ").localeCompare(
        displayCallsign(b) || "ZZZ"));
    rows.forEach((row) => {
      const visibleCallsign = displayCallsign(row);
      const marker = L.marker([row.lat, row.lon], {
        icon: planeIcon(row),
        keyboard: true,
        title: visibleCallsign || copy.noCallsign,
        alt: visibleCallsign || row.typeCode || copy.noCallsign,
      }).addTo(aircraftLayer);
      const tooltip = document.createElement("span");
      tooltip.textContent = visibleCallsign || row.typeCode || copy.noCallsign;
      marker.bindTooltip(tooltip, { direction: "top", offset: [0, -10] });
      marker.bindPopup(popupFor(row), { minWidth: 230 });

      const item = document.createElement("button");
      item.type = "button";
      item.className = "radar-list-item";
      const name = document.createElement("strong");
      name.textContent = visibleCallsign || copy.noCallsign;
      const meta = document.createElement("span");
      meta.className = "text-muted";
      meta.textContent = [
        formatRoute(row), row.airline, row.typeCode, formatAltitude(row),
      ].filter(Boolean).join(" · ");
      item.append(name, meta);
      item.addEventListener("click", () => {
        map.setView([row.lat, row.lon], Math.max(map.getZoom(), 9));
        marker.openPopup();
      });
      listEl.appendChild(item);
    });

    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "text-muted radar-empty";
      empty.textContent = copy.noData;
      listEl.appendChild(empty);
    }
    countEl.textContent = copy.shown(rows.length, currentRows.length, hiddenRows);
  }

  function setStatus(kind, text) {
    stateEl.className = `radar-state ${kind}`;
    stateEl.textContent = text;
  }

  async function loadAircraft(manual) {
    const now = Date.now();
    if (inFlight) return;
    if (manual && now - lastRequestAt < manualCooldownMs) {
      setStatus("loading",
        copy.cooldown(Math.ceil((manualCooldownMs - (now - lastRequestAt)) / 1000)));
      return;
    }

    inFlight = true;
    lastRequestAt = now;
    refreshEl.disabled = true;
    setStatus("loading", copy.loading);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(root.dataset.apiUrl, {
        method: "GET",
        mode: "cors",
        credentials: "omit",
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const raw = Array.isArray(payload.ac) ? payload.ac : [];
      sourceRows = raw.length;
      currentRows = raw.filter((ac) => !isSensitiveOrStale(ac)).map(normalize);
      hiddenRows = sourceRows - currentRows.length;
      const generation = ++loadGeneration;
      render();
      void hydrateRoutes(currentRows, generation);

      const sourceTime = numberOrNull(payload.now);
      const dataTime = sourceTime === null ? new Date() :
        new Date(sourceTime > 1e12 ? sourceTime : sourceTime * 1000);
      updatedEl.textContent = copy.updated(new Intl.DateTimeFormat(
        "en-US",
        { hour: "numeric", minute: "2-digit", hour12: true }
      ).format(dataTime));
      setStatus("live", copy.live);
      nextRefreshAt = Date.now() + refreshMs;
    } catch (_) {
      setStatus("error", copy.error);
      nextRefreshAt = Date.now() + refreshMs;
    } finally {
      window.clearTimeout(timeout);
      inFlight = false;
      refreshEl.disabled = false;
    }
  }

  function initMap() {
    if (!window.L) {
      setStatus("error", copy.error);
      return false;
    }
    map = L.map("radar-map", {
      center: [23.7, 120.9],
      zoom: 7,
      minZoom: 5,
      maxZoom: 13,
      zoomSnap: 0.5,
      maxBounds: [[17.5, 114.5], [30, 128]],
      maxBoundsViscosity: 0.65,
    });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    L.circle([23.7, 120.9], {
      radius: 250 * 1852,
      color: "#ec3013",
      weight: 1,
      opacity: 0.45,
      fill: false,
      dashArray: "5 7",
      interactive: false,
    }).addTo(map);
    airports.forEach((airport) => {
      if (!Number.isFinite(Number(airport.lat)) ||
          !Number.isFinite(Number(airport.lon))) return;
      const marker = L.circleMarker([Number(airport.lat), Number(airport.lon)], {
        radius: 3.5,
        color: "#111",
        weight: 1,
        fillColor: "#fff",
        fillOpacity: 1,
      }).addTo(map);
      const label = document.createElement("span");
      label.textContent = `${clean(airport.iata, 4)} · ${clean(airport.name, 80)}`;
      marker.bindTooltip(label);
    });
    aircraftLayer = L.layerGroup().addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    return true;
  }

  searchEl.addEventListener("input", render);
  airborneEl.addEventListener("change", render);
  refreshEl.addEventListener("click", () => loadAircraft(true));
  callsignModeEls.forEach((button) => {
    button.addEventListener("click", () =>
      setCallsignMode(button.dataset.callsignMode, true));
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() >= nextRefreshAt) loadAircraft(false);
  });
  window.setInterval(() => {
    const seconds = Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000));
    countdownEl.textContent = copy.next(seconds);
    if (!document.hidden && seconds === 0) loadAircraft(false);
  }, 1000);

  setCallsignMode(callsignMode, false);
  if (initMap()) loadAircraft(false);
})();
