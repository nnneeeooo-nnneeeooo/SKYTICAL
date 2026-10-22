(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const CLIENT_KEY = "skytical-ga4-oauth-client-v1";
  const PROPERTY_KEY = "skytical-ga4-property-v1";
  const SCOPE = "https://www.googleapis.com/auth/analytics.readonly";
  const API = "https://analyticsdata.googleapis.com/v1beta/properties/";
  const REFRESH_INTERVAL = 10 * 60 * 1000;
  const fmt = new Intl.NumberFormat("zh-TW");
  let tokenClient = null;
  let accessToken = "";
  let tokenExpires = 0;
  let refreshBusy = false;
  let days = 7;

  function readSaved(key) {
    try { return localStorage.getItem(key) || ""; } catch (_) { return ""; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, value); } catch (_) { /* optional */ }
  }
  $("client-id").value = readSaved(CLIENT_KEY);
  $("property-id").value = readSaved(PROPERTY_KEY);

  function alertMessage(message) {
    $("error").textContent = message;
    $("error").hidden = !message;
  }
  function authState(message, connected) {
    $("auth-state").textContent = message;
    $("auth-state").classList.toggle("connected", Boolean(connected));
  }
  function numeric(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  }
  function renderEmpty(container, message) {
    container.replaceChildren();
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = message;
    container.appendChild(p);
  }
  function rankRow(container, label, number, href) {
    const row = document.createElement("div");
    row.className = "rank-row";
    const content = document.createElement("div");
    content.className = "label";
    if (href) {
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = label;
      content.appendChild(a);
    } else {
      content.textContent = label;
    }
    const count = document.createElement("strong");
    count.className = "count";
    count.textContent = fmt.format(numeric(number));
    row.append(content, count);
    container.appendChild(row);
  }

  function drawTrend(report) {
    const svg = $("trend-plot");
    const labels = $("trend-labels");
    svg.replaceChildren();
    labels.replaceChildren();
    const rows = (report.rows || []).map(function (row) {
      return {date: row.dimensionValues[0].value, sessions: numeric(row.metricValues[0].value)};
    }).sort(function (a,b) { return a.date.localeCompare(b.date); });
    if (!rows.length) {
      const msg = document.createElement("p");
      msg.className = "muted";
      msg.textContent = "目前沒有足夠的每日數據";
      labels.appendChild(msg);
      return;
    }
    const width = 760, height = 246, left = 28, right = 18, top = 17, bottom = 21;
    const usableW = width - left - right, usableH = height - top - bottom;
    const max = Math.max(1, ...rows.map(r => r.sessions));
    const point = (r, i) => [
      left + (rows.length === 1 ? usableW / 2 : i * usableW / (rows.length - 1)),
      top + usableH * (1 - r.sessions / max)
    ];
    function element(name, attrs) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
      svg.appendChild(el);
      return el;
    }
    [0, .5, 1].forEach(function (step) {
      const y = top + usableH * step;
      element("line", {x1:left, y1:y, x2:width-right, y2:y, stroke:"#34393a", "stroke-width":1});
    });
    const d = rows.map((r,i) => {
      const p = point(r,i);
      return (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2);
    }).join(" ");
    element("path", {d:d, fill:"none", stroke:"#fb824f", "stroke-width":3.4, "stroke-linejoin":"round", "stroke-linecap":"round"});
    rows.forEach((r,i) => {
      if (rows.length > 8 && i !== rows.length-1 && i !== 0 && i % 4 !== 0) return;
      const p = point(r,i);
      const circle = element("circle", {cx:p[0],cy:p[1],r:4.1,fill:"#ffba6e",stroke:"#181a1a","stroke-width":2});
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = r.date.slice(0,4) + "/" + r.date.slice(4,6) + "/" + r.date.slice(6) + "：" + fmt.format(r.sessions) + " 次";
      circle.appendChild(title);
    });
    [rows[0], rows[Math.floor((rows.length-1)/2)], rows[rows.length-1]].forEach(function (r) {
      const span = document.createElement("span");
      span.textContent = r.date.slice(4,6) + "/" + r.date.slice(6,8);
      labels.appendChild(span);
    });
  }

  async function runReport(propertyId, body) {
    const response = await fetch(API + propertyId + ":runReport", {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + accessToken,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body),
      cache: "no-store"
    });
    if (!response.ok) {
      if (response.status === 401) {
        accessToken = "";
        authState("授權逾期，請重新登入", false);
        throw Error("Google 授權已過期，請再按「使用 Google 帳號連接」。");
      }
      const result = await response.json().catch(() => ({}));
      const hint = result.error && result.error.message ? result.error.message : "HTTP " + response.status;
      throw Error("GA4 讀取失敗：" + hint);
    }
    return response.json();
  }
  const metric = (name) => ({name:name});
  const dimension = (name) => ({name:name});

  async function refresh() {
    if (refreshBusy || !accessToken) return;
    if (Date.now() >= tokenExpires) {
      accessToken = "";
      authState("登入已逾期", false);
      alertMessage("授權已過期，請重新登入 Google 帳號。");
      return;
    }
    const property = $("property-id").value.trim();
    if (!/^[0-9]{5,20}$/.test(property)) {
      alertMessage("請輸入 GA4 資源的數字 Property ID，不是 G- 開頭的測量 ID。");
      return;
    }
    refreshBusy = true;
    $("refresh").disabled = true;
    $("last-updated").textContent = "正在讀取 GA4…";
    alertMessage("");
    const dateRanges = [{startDate: days + "daysAgo", endDate:"today"}];
    const dateFilters = {dateRanges:dateRanges};
    try {
      const [overview, trend, sources, facebook, pages] = await Promise.all([
        runReport(property, {...dateFilters, metrics:["activeUsers","sessions","screenPageViews","engagementRate"].map(metric)}),
        runReport(property, {...dateFilters, dimensions:[dimension("date")], metrics:[metric("sessions")],
          orderBys:[{dimension:{dimensionName:"date"}}], limit:40}),
        runReport(property, {...dateFilters, dimensions:[dimension("sessionSourceMedium")], metrics:[metric("sessions")],
          orderBys:[{metric:{metricName:"sessions"},desc:true}], limit:20}),
        runReport(property, {...dateFilters, metrics:[metric("sessions")],
          dimensionFilter:{filter:{fieldName:"sessionSource",
            stringFilter:{matchType:"PARTIAL_REGEXP",value:"facebook|(^|[.])fb([./]|$)",caseSensitive:false}}}}),
        runReport(property, {...dateFilters, dimensions:[dimension("pagePath")], metrics:[metric("screenPageViews")],
          orderBys:[{metric:{metricName:"screenPageViews"},desc:true}], limit:100})
      ]);
      const v = overview.rows && overview.rows[0] ? overview.rows[0].metricValues : [];
      const get = (i) => v[i] ? numeric(v[i].value) : 0;
      $("kpi-users").textContent = fmt.format(get(0));
      $("kpi-sessions").textContent = fmt.format(get(1));
      $("kpi-views").textContent = fmt.format(get(2));
      $("kpi-engagement").textContent = (get(3) * 100).toFixed(1) + "%";
      const fbRows = facebook.rows || [];
      $("kpi-facebook").textContent = fmt.format(fbRows[0] ? fbRows[0].metricValues[0].value : 0);
      drawTrend(trend);

      const sourceList = $("sources-list");
      sourceList.replaceChildren();
      (sources.rows || []).slice(0,12).forEach(row =>
        rankRow(sourceList, row.dimensionValues[0].value, row.metricValues[0].value));
      if (!sourceList.children.length) renderEmpty(sourceList, "尚無來源資料");

      const pagesList = $("pages-list");
      pagesList.replaceChildren();
      (pages.rows || []).filter(function (row) {
        const path = row.dimensionValues[0].value || "";
        return path.startsWith("/") && !/^\/(m|u)\//.test(path);
      }).slice(0,12).forEach(function (row) {
        const path = row.dimensionValues[0].value;
        rankRow(pagesList, path === "/" ? "首頁 /" : path, row.metricValues[0].value,
          "https://skytical.tech" + path);
      });
      if (!pagesList.children.length) renderEmpty(pagesList, "尚無文章閱讀資料");
      $("report").hidden = false;
      $("last-updated").textContent = "最後更新：" + new Intl.DateTimeFormat("zh-TW", {
        timeZone:"Asia/Taipei",dateStyle:"short",timeStyle:"short"
      }).format(new Date()) + "（臺灣時間）";
    } catch (err) {
      alertMessage(err.message || "讀取失敗，請確認資源 ID 與 Google 帳戶權限。");
      $("last-updated").textContent = "更新失敗";
    } finally {
      refreshBusy = false;
      $("refresh").disabled = !accessToken;
    }
  }

  $("connect").addEventListener("click", function () {
    alertMessage("");
    const clientId = $("client-id").value.trim();
    const property = $("property-id").value.trim();
    if (!/^[0-9]{5,20}$/.test(property)) {
      alertMessage("GA4 資源 ID 必須是純數字，請從 GA4 管理 → 資源詳細資料取得。");
      return;
    }
    if (!/^[0-9]+-[a-z0-9_-]+\.apps\.googleusercontent\.com$/i.test(clientId)) {
      alertMessage("請填入有效的 Google OAuth 2.0「網頁應用程式」用戶端 ID。");
      return;
    }
    if (!window.google || !window.google.accounts || !window.google.accounts.oauth2) {
      alertMessage("Google 登入服務尚未載入，請確認網路後重新整理頁面。");
      return;
    }
    save(CLIENT_KEY,clientId);
    save(PROPERTY_KEY,property);
    try {
      tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id:clientId,
        scope:SCOPE,
        callback:function (response) {
          if (response.error || !response.access_token) {
            alertMessage("Google 登入未完成：" + (response.error || "請重試"));
            return;
          }
          accessToken = response.access_token;
          tokenExpires = Date.now() + (numeric(response.expires_in) || 3500) * 1000 - 30000;
          authState("已透過 Google 授權",true);
          $("refresh").disabled = false;
          refresh();
        },
        error_callback:function () {
          alertMessage("Google 登入視窗遭到關閉或被瀏覽器阻擋，請重新操作。");
        }
      });
      tokenClient.requestAccessToken({prompt:"consent"});
    } catch (err) {
      alertMessage("Google OAuth 初始化失敗：" + (err.message || "請檢查用戶端設定"));
    }
  });

  $("refresh").addEventListener("click", refresh);
  document.querySelectorAll("[data-days]").forEach(function (button) {
    button.addEventListener("click", function () {
      days = Number(button.dataset.days);
      document.querySelectorAll("[data-days]").forEach(function (other) {
        const active = other === button;
        other.classList.toggle("active", active);
        other.setAttribute("aria-pressed", String(active));
      });
      refresh();
    });
  });
  setInterval(function () {
    if (!document.hidden) refresh();
  }, REFRESH_INTERVAL);
})();
