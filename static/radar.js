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
      callsign: "航班呼號", airline: "航空公司", type: "機型",
      altitude: "高度", speed: "地速", heading: "航向",
      vertical: "垂直速率", freshness: "位置新鮮度",
      ground: "地面", unknown: "未提供", feet: "呎", knots: "節",
      fpm: "呎／分", seconds: "秒前", noCallsign: "無呼號",
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
      callsign: "Callsign", airline: "Airline", type: "Aircraft",
      altitude: "Altitude", speed: "Ground speed", heading: "Heading",
      vertical: "Vertical rate", freshness: "Position age",
      ground: "Ground", unknown: "Not reported", feet: "ft", knots: "kt",
      fpm: "ft/min", seconds: "s ago", noCallsign: "No callsign",
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
  const aircraftTypes = parseJson("radar-types", {});
  const airports = parseJson("radar-airports", []);
  const refreshMs = Math.max(Number(root.dataset.refreshMs) || 300000, 300000);
  const manualCooldownMs = 30000;

  const stateEl = document.getElementById("radar-state");
  const countEl = document.getElementById("radar-count");
  const updatedEl = document.getElementById("radar-updated");
  const countdownEl = document.getElementById("radar-countdown");
  const listEl = document.getElementById("radar-list");
  const searchEl = document.getElementById("radar-search");
  const airborneEl = document.getElementById("radar-airborne");
  const refreshEl = document.getElementById("radar-refresh");

  let map;
  let aircraftLayer;
  let currentRows = [];
  let sourceRows = 0;
  let hiddenRows = 0;
  let nextRefreshAt = Date.now() + refreshMs;
  let lastRequestAt = 0;
  let inFlight = false;

  const numberOrNull = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const clean = (value, maxLength) =>
    String(value == null ? "" : value).trim().slice(0, maxLength);

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
    };
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
    title.textContent = row.callsign || copy.noCallsign;
    box.appendChild(title);
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
      row.callsign, row.operator, row.airline, row.typeCode, row.typeName,
    ].some((value) => value.toUpperCase().includes(query));
  }

  function render() {
    const query = searchEl.value.trim().toUpperCase();
    const rows = currentRows.filter((row) =>
      rowMatches(row, query, airborneEl.checked));
    aircraftLayer.clearLayers();
    listEl.replaceChildren();

    rows.sort((a, b) =>
      (a.callsign || "ZZZ").localeCompare(b.callsign || "ZZZ"));
    rows.forEach((row) => {
      const marker = L.marker([row.lat, row.lon], {
        icon: planeIcon(row),
        keyboard: true,
        title: row.callsign || copy.noCallsign,
        alt: row.callsign || row.typeCode || copy.noCallsign,
      }).addTo(aircraftLayer);
      const tooltip = document.createElement("span");
      tooltip.textContent = row.callsign || row.typeCode || copy.noCallsign;
      marker.bindTooltip(tooltip, { direction: "top", offset: [0, -10] });
      marker.bindPopup(popupFor(row), { minWidth: 230 });

      const item = document.createElement("button");
      item.type = "button";
      item.className = "radar-list-item";
      const name = document.createElement("strong");
      name.textContent = row.callsign || copy.noCallsign;
      const meta = document.createElement("span");
      meta.className = "text-muted";
      meta.textContent = [
        row.airline, row.typeCode, formatAltitude(row),
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
      render();

      const sourceTime = numberOrNull(payload.now);
      const dataTime = sourceTime === null ? new Date() :
        new Date(sourceTime > 1e12 ? sourceTime : sourceTime * 1000);
      updatedEl.textContent = copy.updated(new Intl.DateTimeFormat(
        lang === "zh" ? "zh-TW" : "en-GB",
        { hour: "2-digit", minute: "2-digit", second: "2-digit" }
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
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() >= nextRefreshAt) loadAircraft(false);
  });
  window.setInterval(() => {
    const seconds = Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000));
    countdownEl.textContent = copy.next(seconds);
    if (!document.hidden && seconds === 0) loadAircraft(false);
  }, 1000);

  if (initMap()) loadAircraft(false);
})();
