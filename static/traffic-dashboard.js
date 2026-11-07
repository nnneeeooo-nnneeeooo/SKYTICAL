(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CLIENT_KEY = "skytical-ga4-oauth-client-v1";
  const PROPERTY_KEY = "skytical-ga4-property-v1";
  const SCOPE = "https://www.googleapis.com/auth/analytics.readonly";
  const API = "https://analyticsdata.googleapis.com/v1beta/properties/";
  const REFRESH_INTERVAL = 10 * 60 * 1000;
  const serverMode = Boolean(document.documentElement && document.documentElement.dataset.trafficTransport === "apps-script");
  const DAY = 86400000;
  const fmt = new Intl.NumberFormat("zh-TW");
  const percent = new Intl.NumberFormat("zh-TW", {style:"percent", minimumFractionDigits:1, maximumFractionDigits:1});
  const dateFmt = new Intl.DateTimeFormat("zh-TW", {timeZone:"UTC", month:"numeric", day:"numeric"});
  const fullDateFmt = new Intl.DateTimeFormat("zh-TW", {timeZone:"UTC", year:"numeric", month:"2-digit", day:"2-digit"});
  const metrics = {sessions:"工作階段", screenPageViews:"頁面瀏覽量", activeUsers:"活躍使用者"};
  let tokenClient = null, accessToken = "", tokenExpires = 0;
  let refreshBusy = false, refreshAgain = false, revision = 0;
  let days = 7, custom = null, snapshot = null, chartRows = [], chartIndex = 0;
  let sourceExpanded = false, pagesExpanded = false, chartGeometry = null;
  let lastGood = "";

  function readSaved(key) { try { return localStorage.getItem(key) || ""; } catch (_) { return ""; } }
  function save(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* optional */ } }
  function numeric(value) { const n = Number(value); return Number.isFinite(n) ? Math.max(0, n) : 0; }
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function alertMessage(message) { $("error").textContent = message; $("error").hidden = !message; }
  function authState(message, connected) {
    $("auth-state").textContent = message;
    $("auth-state").classList.toggle("connected", Boolean(connected));
    $("auth-action").textContent = connected ? "連線設定" : "連接 Google";
    $("refresh").disabled = !connected || refreshBusy;
  }
  function utcDate(iso) { return new Date(iso + "T00:00:00Z"); }
  function isoDate(date) { return date.toISOString().slice(0, 10); }
  function today() {
    const parts = new Intl.DateTimeFormat("en-US", {timeZone:"Asia/Taipei", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
    const value = (type) => parts.find(p => p.type === type).value;
    return value("year") + "-" + value("month") + "-" + value("day");
  }
  function validDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(utcDate(value).getTime()) && isoDate(utcDate(value)) === value;
  }
  function rangeError(start, end) {
    if (!validDate(start) || !validDate(end)) return "請填寫完整的開始與結束日期。";
    if (start > end) return "開始日期不能晚於結束日期。";
    if (end > today()) return "結束日期不能晚於今天。";
    if ((utcDate(end) - utcDate(start)) / DAY >= 366) return "每次最多可查看 366 天，請縮短日期範圍。";
    return "";
  }
  function selectedRange() {
    if (custom) return {...custom};
    const end = today();
    return {start:isoDate(new Date(utcDate(end).getTime() - (days - 1) * DAY)), end:end};
  }
  function rangeLabel(range) {
    return fullDateFmt.format(utcDate(range.start)) + " — " + fullDateFmt.format(utcDate(range.end)) + (range.end === today() ? "（含今天，數據尚未完整）" : "");
  }
  function updatePeriodButtons() {
    document.querySelectorAll(".period").forEach(function (button) {
      const active = custom ? button.id === "custom-period" : Number(button.dataset.days) === days;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (!snapshot) $("report-period").textContent = rangeLabel(selectedRange());
  }
  function syncUrl() {
    try {
      if (serverMode && window.google && window.google.script && window.google.script.history) {
        const params = custom ? {...custom} : {days:String(days)};
        params.metric = $("trend-metric").value;
        window.google.script.history.replace({}, params, "");
        return;
      }
      const url = new URL(location.href);
      ["days", "start", "end", "metric"].forEach(k => url.searchParams.delete(k));
      if (custom) { url.searchParams.set("start", custom.start); url.searchParams.set("end", custom.end); }
      else url.searchParams.set("days", String(days));
      url.searchParams.set("metric", $("trend-metric").value);
      history.replaceState(null, "", url);
    } catch (_) { /* local previews may not support history */ }
  }
  function openCustom(open) {
    $("custom-range").hidden = !open;
    $("custom-period").setAttribute("aria-expanded", String(open));
  }
  function empty(container, message) { container.replaceChildren(node("p", "empty", message)); }
  function safePath(value) {
    if (!value || !/^\/(?!\/)/.test(value)) return null;
    try {
      const url = new URL(value, "https://skytical.tech");
      if (url.origin !== "https://skytical.tech") return null;
      const decoded = decodeURIComponent(url.pathname);
      if (/^\/(?:[a-z]{2}\/)?(?:m|u)(?:\/|$)/i.test(decoded)) return null;
      return url.pathname;
    } catch (_) { return null; }
  }
  function pageLabel(path) {
    if (path === "/") return "中文首頁";
    if (path === "/en/" || path === "/en") return "英文首頁";
    if (/^\/(en\/)?news\//.test(path)) return "新聞閱讀";
    if (/\/radar\//.test(path)) return "航班雷達";
    try { return decodeURIComponent(path); } catch (_) { return path; }
  }
  function renderRankings() {
    if (!snapshot) return;
    const sourceList = $("sources-list"), pagesList = $("pages-list");
    sourceList.replaceChildren(); pagesList.replaceChildren();
    snapshot.sources.slice(0, sourceExpanded ? 20 : 5).forEach(function (item) {
      const row = node("div", "rank-row source-row");
      const label = node("div", "label", item.label);
      const track = node("div", "source-bar"), fill = node("div", "source-fill");
      fill.style.transform = "scaleX(" + (snapshot.sessions ? Math.min(1, item.count / snapshot.sessions) : 0) + ")";
      track.setAttribute("aria-hidden", "true"); track.appendChild(fill); label.appendChild(track);
      const count = node("div", "count", fmt.format(item.count));
      count.appendChild(node("small", "", snapshot.sessions ? percent.format(item.count / snapshot.sessions) : "—"));
      row.append(label, count); sourceList.appendChild(row);
    });
    if (!snapshot.sources.length) empty(sourceList, "所選期間沒有來源資料。");
    $("more-sources").hidden = snapshot.sources.length <= 5;
    $("more-sources").textContent = sourceExpanded ? "收合來源" : "顯示更多來源（" + snapshot.sources.length + "）";
    snapshot.pages.slice(0, pagesExpanded ? 50 : 5).forEach(function (item, i) {
      const row = node("div", "rank-row"), label = node("div", "label");
      const link = node("a", "", pageLabel(item.path));
      link.href = "https://skytical.tech" + item.path; link.target = "_blank"; link.rel = "noopener noreferrer";
      const pathText = decodeURI(item.path);
      link.title = pathText; link.setAttribute("aria-label", pageLabel(item.path) + " " + pathText);
      label.append(link, node("small", "", pathText));
      const count = node("div", "count", fmt.format(item.count));
      count.appendChild(node("small", "", snapshot.views ? percent.format(item.count / snapshot.views) : "—"));
      row.append(node("span", "rank-index", fmt.format(i + 1)), label, count); pagesList.appendChild(row);
    });
    if (!snapshot.pages.length) empty(pagesList, "所選期間沒有公開網頁的閱讀資料。");
    $("more-pages").hidden = snapshot.pages.length <= 5;
    $("more-pages").textContent = pagesExpanded ? "收合網頁" : "顯示更多網頁（" + Math.min(50, snapshot.pages.length) + "）";
    $("pages-summary").textContent = "依瀏覽量排序；排除私人頁面";
  }
  function svgNode(tag, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
    if (text !== undefined) el.textContent = text;
    $("trend-plot").appendChild(el); return el;
  }
  function displayPoint(index) {
    if (!chartRows.length || !chartGeometry) return;
    chartIndex = Math.max(0, Math.min(chartRows.length - 1, Number(index)));
    const row = chartRows[chartIndex], key = $("trend-metric").value;
    const {left, top, w, h, max} = chartGeometry;
    const x = left + (chartRows.length === 1 ? w / 2 : chartIndex * w / (chartRows.length - 1));
    const y = top + h * (1 - row[key] / max);
    $("trend-plot").querySelectorAll(".chart-marker,.chart-dot").forEach(el => el.remove());
    svgNode("line", {x1:x, x2:x, y1:top, y2:top+h, class:"chart-marker"});
    svgNode("circle", {cx:x, cy:y, r:4.5, class:"chart-dot"});
    const label = fullDateFmt.format(utcDate(row.date));
    $("chart-readout").replaceChildren(node("span", "muted", label), node("strong", "", fmt.format(row[key])), node("span", "muted", " " + metrics[key]));
    $("chart-day").value = String(chartIndex);
    $("chart-day").setAttribute("aria-valuetext", label + "，" + metrics[key] + " " + fmt.format(row[key]));
    $("chart-day-label").textContent = chartRows.length === 1 ? "當日數據" : "拖曳或用方向鍵逐日查看";
  }
  function drawTrend() {
    const svg = $("trend-plot"); svg.replaceChildren();
    // Match the actual viewport so SVG labels retain a readable 12px size on phones.
    const bounds = svg.getBoundingClientRect();
    const width = Math.max(260, Math.round(bounds.width));
    const height = Math.max(160, Math.round(bounds.height || 216));
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    const left = Math.min(76, Math.max(38, fmt.format(Math.max(0, ...chartRows.map(r => r[$("trend-metric").value]))).length * 8 + 12));
    const top = 16, w = width - left - 16, h = height - top - 32;
    const key = $("trend-metric").value;
    const peak = Math.max(0, ...chartRows.map(r => r[key]));
    const rough = (peak || 1) / 4, magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
    const step = Math.max(1, [1, 2, 5, 10].map(n => n * magnitude).find(n => n >= rough));
    const max = (Math.floor(peak / step) + 1) * step;
    chartGeometry = {left, top, w, h, max};
    for (let value = 0; value <= max; value += step) {
      const y = top + h * (1 - value / max);
      svgNode("line", {x1:left, x2:left+w, y1:y, y2:y, class:"chart-grid"});
      svgNode("text", {x:left-10, y:y+4, "text-anchor":"end"}, fmt.format(value));
    }
    if (!chartRows.length) {
      svg.setAttribute("aria-label", "尚未連接 GA4，沒有流量數據"); return;
    }
    const d = chartRows.map(function (r, i) {
      const x = left + (chartRows.length === 1 ? w / 2 : i * w / (chartRows.length - 1));
      return (i ? "L" : "M") + x.toFixed(2) + " " + (top + h * (1-r[key]/max)).toFixed(2);
    }).join(" ");
    svgNode("path", {d:d, class:"chart-line"});
    if (chartRows.length <= 7) chartRows.forEach(function (row, i) {
      const x = left + (chartRows.length === 1 ? w / 2 : i * w / (chartRows.length - 1));
      const y = top + h * (1 - row[key] / max);
      svgNode("text", {x:x, y:y-9, class:"point-value", "text-anchor":i === 0 ? "start" : i === chartRows.length-1 ? "end" : "middle"}, fmt.format(row[key]));
    });
    const labels = Math.min(chartRows.length, width < 480 ? 3 : 5);
    for (let n = 0; n < labels; n++) {
      const i = labels === 1 ? 0 : Math.round(n * (chartRows.length - 1) / (labels - 1));
      const x = left + (chartRows.length === 1 ? w / 2 : i * w / (chartRows.length - 1));
      svgNode("text", {x:x, y:height-5, "text-anchor":n === 0 ? "start" : n === labels-1 ? "end" : "middle"}, dateFmt.format(utcDate(chartRows[i].date)));
    }
    const maxRow = chartRows.reduce((a,b) => b[key] > a[key] ? b : a);
    svg.setAttribute("aria-label", metrics[key] + "每日趨勢，最高 " + fmt.format(maxRow[key]) + "，" + fullDateFmt.format(utcDate(maxRow.date)) + "。可使用下方日期滑桿或每日明細查看完整數據。");
    $("chart-day").disabled = false; $("chart-day").max = String(chartRows.length-1);
    displayPoint(chartIndex);
  }
  function renderDaily() {
    $("daily-rows").replaceChildren();
    chartRows.forEach(function (row) {
      const tr = node("tr");
      [fullDateFmt.format(utcDate(row.date)), fmt.format(row.sessions), fmt.format(row.screenPageViews), fmt.format(row.activeUsers)].forEach(value => tr.appendChild(node("td", "", value)));
      $("daily-rows").appendChild(tr);
    });
  }
  function normalizeTrend(report, range) {
    const byDate = new Map();
    (report.rows || []).forEach(function (row) {
      const raw = row.dimensionValues[0].value;
      const date = raw.slice(0,4) + "-" + raw.slice(4,6) + "-" + raw.slice(6,8);
      byDate.set(date, {date:date, sessions:numeric(row.metricValues[0].value), screenPageViews:numeric(row.metricValues[1].value), activeUsers:numeric(row.metricValues[2].value)});
    });
    const rows = [];
    // GA4 omits dates without events: fill the actual calendar, not categorical gaps.
    for (let time = utcDate(range.start).getTime(); time <= utcDate(range.end).getTime(); time += DAY) {
      const date = isoDate(new Date(time));
      rows.push(byDate.get(date) || {date:date, sessions:0, screenPageViews:0, activeUsers:0});
    }
    return rows;
  }
  async function runReport(propertyId, body) {
    if (serverMode) {
      return new Promise(function (resolve, reject) {
        if (!window.google || !window.google.script || !window.google.script.run) {
          reject(Error("請從私人入口開啟 Google 保護的儀表板。")); return;
        }
        const timeout = setTimeout(() => reject(Error("Google 報表回應逾時，請稍後按更新重試。")), 45000);
        window.google.script.run.withSuccessHandler(function (result) {
          clearTimeout(timeout); resolve(result);
        }).withFailureHandler(function (error) {
          clearTimeout(timeout);
          reject(Error(error.message || "Google 報表讀取失敗，請稍後按更新重試。"));
        }).runTrafficReport(body);
      });
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    let response;
    try {
      response = await fetch(API + propertyId + ":runReport", {
        method:"POST", headers:{"Authorization":"Bearer " + accessToken, "Content-Type":"application/json"}, body:JSON.stringify(body), cache: "no-store", signal:controller.signal
      });
    } catch (err) {
      throw Error(err.name === "AbortError" ? "GA4 回應逾時，請稍後按更新重試。" : "無法連接 GA4，請確認網路後按更新重試。");
    } finally { clearTimeout(timeout); }
    if (!response.ok) {
      if (response.status === 401) {
        accessToken = ""; authState("授權逾期", false);
        throw Error("Google 授權已過期，請按「連接 Google」重新登入。");
      }
      const result = await response.json().catch(() => ({}));
      throw Error("GA4 讀取失敗：" + (result.error && result.error.message || "HTTP " + response.status) + "。請確認資源 ID、帳戶權限後再按更新。");
    }
    return response.json();
  }
  const metric = name => ({name:name});
  const dimension = name => ({name:name});
  async function refresh() {
    if (refreshBusy) { refreshAgain = true; return; }
    if (!accessToken && !serverMode) return;
    if (!serverMode && Date.now() >= tokenExpires) {
      accessToken = ""; authState("授權逾期", false); alertMessage("授權已過期，請按「連接 Google」重新登入。"); return;
    }
    const property = $("property-id").value.trim();
    if (!serverMode && !/^[0-9]{5,20}$/.test(property)) { alertMessage("請輸入 GA4 的數字資源 ID，非 G- 開頭的測量 ID。"); $("setup").open = true; $("property-id").focus(); return; }
    const range = selectedRange(), requestedRevision = revision;
    refreshBusy = true; $("refresh").disabled = true; $("report").setAttribute("aria-busy", "true");
    $("last-updated").textContent = "正在讀取 GA4…"; alertMessage("");
    const dateFilters = {dateRanges:[{startDate:range.start, endDate:range.end}]};
    try {
      const [overview, trend, sources, facebook, pages] = await Promise.all([
        runReport(property, {...dateFilters, metrics:["activeUsers","sessions","screenPageViews","engagementRate"].map(metric)}),
        runReport(property, {...dateFilters, dimensions:[dimension("date")], metrics:["sessions","screenPageViews","activeUsers"].map(metric), orderBys:[{dimension:{dimensionName:"date"}}], limit:366}),
        runReport(property, {...dateFilters, dimensions:[dimension("sessionSourceMedium")], metrics:[metric("sessions")], orderBys:[{metric:{metricName:"sessions"}, desc:true}], limit:20}),
        runReport(property, {...dateFilters, metrics:[metric("sessions")], dimensionFilter:{filter:{fieldName:"sessionSource", stringFilter:{matchType:"PARTIAL_REGEXP", value:"facebook|(^|[.])fb([./]|$)", caseSensitive:false}}}}),
        runReport(property, {...dateFilters, dimensions:[dimension("pagePath")], metrics:[metric("screenPageViews")], orderBys:[{metric:{metricName:"screenPageViews"}, desc:true}], limit:100})
      ]);
      // A slower previous request must never overwrite a newly selected period.
      if (requestedRevision !== revision) return;
      const v = overview.rows && overview.rows[0] ? overview.rows[0].metricValues : [];
      const get = i => v[i] ? numeric(v[i].value) : 0;
      const fb = facebook.rows && facebook.rows[0] ? numeric(facebook.rows[0].metricValues[0].value) : 0;
      snapshot = {range:range, sessions:get(1), views:get(2),
        sources:(sources.rows || []).map(r => ({label:r.dimensionValues[0].value, count:numeric(r.metricValues[0].value)})),
        pages:(pages.rows || []).map(r => ({path:safePath(r.dimensionValues[0].value), count:numeric(r.metricValues[0].value)})).filter(r => r.path)};
      $("kpi-users").textContent = fmt.format(get(0)); $("kpi-sessions").textContent = fmt.format(get(1));
      $("kpi-views").textContent = fmt.format(get(2)); $("kpi-engagement").textContent = percent.format(get(3)); $("kpi-facebook").textContent = fmt.format(fb);
      $("facebook-share").textContent = get(1) ? "占所有到訪 " + percent.format(fb/get(1)) : "所選期間沒有到訪";
      chartRows = normalizeTrend(trend, range); chartIndex = chartRows.length-1;
      drawTrend(); renderDaily(); renderRankings();
      const top = snapshot.sources[0];
      $("finding").textContent = top ? "主要來源為 " + top.label + "，帶來 " + fmt.format(top.count) + " 次到訪。" : "所選期間沒有到訪紀錄，可切換日期查看其他期間。";
      $("report-period").textContent = rangeLabel(range);
      lastGood = new Intl.DateTimeFormat("zh-TW", {timeZone:"Asia/Taipei", dateStyle:"short", timeStyle:"short"}).format(new Date());
      $("last-updated").textContent = "更新於 " + lastGood + "（臺灣時間）";
    } catch (err) {
      if (requestedRevision === revision) {
        alertMessage((err.message || "讀取失敗，請確認資源 ID 與帳戶權限後重試。") + (snapshot ? " 目前保留上次成功載入的數據。" : ""));
        $("last-updated").textContent = lastGood ? "更新失敗；上次成功 " + lastGood : "讀取失敗，請重新更新";
      }
    } finally {
      refreshBusy = false; $("refresh").disabled = !serverMode && !accessToken; $("report").setAttribute("aria-busy", "false");
      if (refreshAgain) { refreshAgain = false; refresh(); }
    }
  }
  function connect() {
    alertMessage("");
    const clientId = $("client-id").value.trim(), property = $("property-id").value.trim();
    function invalid(message, field) { alertMessage(message); $("setup").open = true; $(field).focus(); }
    if (!/^[0-9]{5,20}$/.test(property)) { invalid("GA4 資源 ID 必須是純數字，請從 GA4 管理 → 資源詳細資料取得。", "property-id"); return; }
    if (!/^[0-9]+-[a-z0-9_-]+\.apps\.googleusercontent\.com$/i.test(clientId)) { invalid("請填入有效的 Google OAuth 2.0 網頁用戶端 ID。", "client-id"); return; }
    if (!window.google || !window.google.accounts || !window.google.accounts.oauth2) { alertMessage("Google 登入服務尚未載入，請確認網路後重新整理頁面。"); return; }
    save(CLIENT_KEY,clientId); save(PROPERTY_KEY,property);
    try {
      tokenClient = window.google.accounts.oauth2.initTokenClient({client_id:clientId, scope:SCOPE,
        callback:function (response) {
          if (response.error || !response.access_token) { alertMessage("Google 登入未完成：" + (response.error || "請重試")); return; }
          accessToken = response.access_token; tokenExpires = Date.now() + (numeric(response.expires_in) || 3500) * 1000 - 30000;
          revision++; authState("已連接 GA4", true); $("setup").classList.toggle("configured", true); $("setup").open = false; refresh();
        },
        error_callback:function () { alertMessage("Google 登入視窗遭到關閉或被阻擋，請按「連接 Google」重試。"); }
      });
      tokenClient.requestAccessToken({prompt:""});
    } catch (err) { alertMessage("Google OAuth 初始化失敗：" + (err.message || "請檢查用戶端設定")); }
  }
  $("client-id").value = readSaved(CLIENT_KEY); $("property-id").value = readSaved(PROPERTY_KEY);
  if ($("client-id").value && $("property-id").value) $("setup").open = false;
  function restoreFilters(params) {
    if ([1,7,28,90].includes(Number(params.get("days")))) days = Number(params.get("days"));
    if (params.has("start") && params.has("end") && !rangeError(params.get("start"), params.get("end"))) {
      custom = {start:params.get("start"), end:params.get("end")}; openCustom(true);
    }
    if (Object.hasOwn(metrics, params.get("metric"))) $("trend-metric").value = params.get("metric");
    $("start-date").value = selectedRange().start; $("end-date").value = selectedRange().end;
    updatePeriodButtons();
  }
  restoreFilters(new URLSearchParams(location.search));
  $("start-date").max = today(); $("end-date").max = today();
  updatePeriodButtons(); drawTrend();
  $("connect").addEventListener("click", connect);
  $("auth-action").addEventListener("click", function () {
    if (accessToken) { $("setup").open = !$("setup").open; return; }
    connect();
  });
  $("refresh").addEventListener("click", refresh);
  document.querySelectorAll("[data-days]").forEach(function (button) {
    button.addEventListener("click", function () {
      days = Number(button.dataset.days); custom = null; revision++;
      openCustom(false); updatePeriodButtons(); syncUrl(); refresh();
    });
  });
  $("custom-period").addEventListener("click", function () {
    openCustom($("custom-range").hidden);
    if (!$("custom-range").hidden) $("start-date").focus();
  });
  $("apply-range").addEventListener("click", function () {
    const start = $("start-date").value, end = $("end-date").value;
    const error = rangeError(start, end);
    $("range-error").textContent = error; $("range-error").hidden = !error;
    $("start-date").setAttribute("aria-invalid", String(Boolean(error)));
    if (error) { $("start-date").focus(); return; }
    custom = {start:start, end:end}; revision++; updatePeriodButtons(); syncUrl(); refresh();
  });
  $("trend-metric").addEventListener("change", function () { syncUrl(); drawTrend(); });
  $("chart-day").addEventListener("input", function () { displayPoint(this.value); });
  $("trend-plot").addEventListener("pointermove", function (event) {
    if (!chartRows.length || !chartGeometry) return;
    const rect = this.getBoundingClientRect();
    displayPoint(Math.round((event.clientX - rect.left - chartGeometry.left) / chartGeometry.w * (chartRows.length-1)));
  });
  $("more-sources").addEventListener("click", function () { sourceExpanded = !sourceExpanded; renderRankings(); });
  $("more-pages").addEventListener("click", function () { pagesExpanded = !pagesExpanded; renderRankings(); });
  let resizeTimer;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawTrend, 100); });
  setInterval(function () { if (!document.hidden) refresh(); }, REFRESH_INTERVAL);
  if (serverMode) {
    $("setup").hidden = true; $("auth-action").hidden = true;
    if (!window.google || !window.google.script || !window.google.script.run) {
      authState("請使用私人入口", false);
      alertMessage("請從原本的私人入口開啟 Google 保護的儀表板。");
      return;
    }
    authState("Google 私人連線", true);
    if (window.google && window.google.script && window.google.script.url) {
      window.google.script.url.getLocation(function (location) {
        restoreFilters(new URLSearchParams(location.parameter || {}));
        refresh();
      });
    } else refresh();
  }
})();
