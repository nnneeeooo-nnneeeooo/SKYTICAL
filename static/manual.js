(async () => {
  "use strict";

  const app = document.querySelector("#app");
  const repository = app.dataset.repository;
  const branch = app.dataset.branch;
  const basePath = app.dataset.base;
  const els = Object.fromEntries([
    "mode-ai", "mode-manual", "manual-editor",
    "manual-title-primary", "manual-content-primary",
    "manual-secondary-language", "manual-title-secondary",
    "manual-content-secondary", "manual-primary-title-label",
    "manual-primary-content-label", "manual-english-mode-panel",
    "manual-english-mode", "writer-models-panel",
    "writer-model-1", "writer-model-2", "writer-model-3",
    "writer-model-4", "writer-model-5",
    "github-token", "clear-token", "source-urls", "source-text",
    "article-summary", "publication-mode", "manual-time-panel",
    "publication-date", "publication-hour", "publication-minute",
    "publication-period", "manual-order-panel", "sort-follow-publication",
    "sort-time-fields", "sort-date", "sort-hour", "sort-minute",
    "sort-period",
    "image-input", "image-list", "image-description", "upload-zone", "article-type", "language",
    "model", "reasoning-tier", "chat-history", "instruction", "clear-chat",
    "generate", "form-error", "security-state", "job-state", "metric-model",
    "metric-reasoning", "metric-fallback", "metric-duration",
    "metric-tokens", "metric-rate", "attempts", "request-log",
    "json-output", "copy-json", "download-json", "output-panel",
    "activity-indicator", "pipeline-steps",
    "review-panel", "review-status", "review-type", "review-time",
    "review-time-source", "review-draft-status", "preview-zh-title",
    "preview-zh-summary", "preview-zh-body", "preview-en-title",
    "preview-en-summary", "preview-en-body", "confirm-model",
    "custom-model-panel", "custom-model", "regenerate", "publish",
    "publish-state",
  ].map(id => [id, document.getElementById(id)]));

  const pathParts = location.pathname.split("/").filter(Boolean);
  const marker = pathParts.lastIndexOf("m");
  const manualToken = marker >= 0 ? pathParts[marker + 1] || "" : "";
  const validToken = /^[A-Za-z0-9_-]{32,128}$/.test(manualToken);
  const PAT_STORAGE_KEY = "avwire-manual-github-pat-v1";
  const PAT_VAULT_CONTEXT = `avwire-pat-v1:${repository}`;
  const images = [];
  const conversation = [];
  let patInputRevision = 0;
  let lastResult = null;
  let workbenchMode = "ai";
  let operationStartedAt = null;
  let aiArticleType = "auto";
  let aiLanguage = "bilingual";

  const ARTICLE_TYPE_LABELS = {
    auto: "自動偵測",
    flash: "快訊",
    press_release: "新聞稿",
    incident: "事故／事件",
    airline: "航司",
    airport: "機場",
    fleet_order: "機隊／訂單",
    regulation: "監管",
    financial: "財報",
  };
  const TIME_SOURCE_LABELS = {
    manual: "手動指定（臺北時間）",
    source_metadata: "來源網頁結構化時間",
    model_source_text: "模型從來源明文辨識",
    generation_fallback: "無法辨識，使用生成時間",
  };

  const text = (element, value) => { element.textContent = value; };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function setState(label, kind = "idle") {
    text(els["job-state"], label);
    els["job-state"].className = `job-state ${kind}`;
    els["activity-indicator"].className = `activity-indicator ${kind}`;
  }

  function setWorkflow(labels) {
    els["pipeline-steps"].replaceChildren();
    labels.forEach(label => {
      const item = document.createElement("li");
      item.className = "waiting";
      item.append(document.createElement("span"), label);
      els["pipeline-steps"].append(item);
    });
  }

  function setWorkflowStep(index, status) {
    const rows = [...els["pipeline-steps"].children];
    if (!rows[index]) return;
    rows[index].className = status;
  }

  function failActiveWorkflow() {
    const active = els["pipeline-steps"].querySelector(".active");
    if (active) active.className = "failed";
  }

  function addLog(message) {
    if (els["request-log"].dataset.empty !== "false") {
      els["request-log"].replaceChildren();
      els["request-log"].dataset.empty = "false";
    }
    const item = document.createElement("li");
    item.textContent = `${clock12(new Date())}　${message}`;
    els["request-log"].append(item);
    els["request-log"].scrollTop = els["request-log"].scrollHeight;
  }

  function bytesToBase64(bytes) {
    let binary = "";
    for (let start = 0; start < bytes.length; start += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
    }
    return btoa(binary);
  }

  function base64ToBytes(value) {
    const binary = atob(value.replace(/\s/g, ""));
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  }

  async function cryptoKey() {
    const digest = await crypto.subtle.digest(
      "SHA-256", new TextEncoder().encode(manualToken));
    return crypto.subtle.importKey(
      "raw", digest, {name: "AES-GCM"}, false, ["encrypt", "decrypt"]);
  }

  async function encrypt(value, jobId) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt(
      {name: "AES-GCM", iv, additionalData: new TextEncoder().encode(jobId)},
      await cryptoKey(),
      new TextEncoder().encode(JSON.stringify(value)),
    );
    return {
      version: 1,
      alg: "A256GCM",
      iv: bytesToBase64(iv),
      ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
    };
  }

  async function decrypt(envelope, jobId) {
    if (envelope.version !== 1 || envelope.alg !== "A256GCM") {
      throw new Error("工作結果使用不支援的加密格式");
    }
    const clear = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: base64ToBytes(envelope.iv),
        additionalData: new TextEncoder().encode(jobId),
      },
      await cryptoKey(),
      base64ToBytes(envelope.ciphertext),
    );
    return JSON.parse(new TextDecoder().decode(clear));
  }

  const validPat = value => /^github_pat_[A-Za-z0-9_]+$/.test(value);

  async function patCryptoKey() {
    const material = new TextEncoder().encode(
      `${manualToken}\u0000${PAT_VAULT_CONTEXT}`);
    const digest = await crypto.subtle.digest("SHA-256", material);
    return crypto.subtle.importKey(
      "raw", digest, {name: "AES-GCM"}, false, ["encrypt", "decrypt"]);
  }

  async function encryptPat(token) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: new TextEncoder().encode(PAT_VAULT_CONTEXT),
      },
      await patCryptoKey(),
      new TextEncoder().encode(token),
    );
    return {
      version: 1,
      alg: "A256GCM",
      iv: bytesToBase64(iv),
      ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
    };
  }

  async function decryptPat(envelope) {
    if (envelope.version !== 1 || envelope.alg !== "A256GCM") {
      throw new Error("不支援的 PAT 加密格式");
    }
    const clear = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: base64ToBytes(envelope.iv),
        additionalData: new TextEncoder().encode(PAT_VAULT_CONTEXT),
      },
      await patCryptoKey(),
      base64ToBytes(envelope.ciphertext),
    );
    const token = new TextDecoder().decode(clear);
    if (!validPat(token)) throw new Error("解密後的 PAT 格式無效");
    return token;
  }

  async function rememberPat(
    token = els["github-token"].value.trim(),
    expectedRevision = null,
  ) {
    try {
      const envelope = await encryptPat(token);
      if (expectedRevision !== null && (
        expectedRevision !== patInputRevision
        || els["github-token"].value.trim() !== token
      )) return false;
      localStorage.setItem(PAT_STORAGE_KEY, JSON.stringify(envelope));
      return true;
    } catch (error) {
      addLog("瀏覽器拒絕保存 PAT；本次工作仍會繼續");
      return false;
    }
  }

  async function savePatOnInput() {
    const token = els["github-token"].value.trim();
    const revision = ++patInputRevision;
    if (!validToken || !validPat(token)) return;
    if (await rememberPat(token, revision)) {
      text(els["security-state"], "網址權杖有效 · PAT 已加密記憶");
    }
  }

  async function restorePat() {
    try {
      const stored = localStorage.getItem(PAT_STORAGE_KEY);
      if (!stored) return false;
      els["github-token"].value = await decryptPat(JSON.parse(stored));
      return true;
    } catch (error) {
      try {
        localStorage.removeItem(PAT_STORAGE_KEY);
      } catch (storageError) {
        // A browser that blocks storage needs no further cleanup.
      }
      return false;
    }
  }

  function githubPath(path) {
    return path.split("/").map(encodeURIComponent).join("/");
  }

  async function github(path, options = {}) {
    const token = els["github-token"].value.trim();
    const separator = path.indexOf("?");
    const rawPath = separator >= 0 ? path.slice(0, separator) : path;
    const query = separator >= 0 ? path.slice(separator) : "";
    const response = await fetch(
      `https://api.github.com/repos/${repository}/contents/${githubPath(rawPath)}${query}`,
      {
        ...options,
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${token}`,
          "X-GitHub-Api-Version": "2022-11-28",
          ...(options.headers || {}),
        },
        cache: "no-store",
      },
    );
    const remaining = response.headers.get("x-ratelimit-remaining");
    const limit = response.headers.get("x-ratelimit-limit");
    if (remaining && limit) {
      text(els["metric-rate"], `GitHub ${remaining}/${limit}；等待模型回應`);
    }
    return response;
  }

  function encodeUtf8(value) {
    return bytesToBase64(new TextEncoder().encode(value));
  }

  function decodeUtf8(value) {
    return new TextDecoder().decode(base64ToBytes(value));
  }

  async function readRepoFile(path) {
    const response = await github(
      `${path}?ref=${encodeURIComponent(branch)}`);
    if (response.status === 404) return {sha: null, content: null};
    if (!response.ok) {
      throw new Error(`讀取 ${path} 失敗（HTTP ${response.status}）`);
    }
    const file = await response.json();
    return {sha: file.sha, content: decodeUtf8(file.content)};
  }

  async function writeRepoFile(path, content, message, sha = null) {
    const body = {message, content: encodeUtf8(content), branch};
    if (sha) body.sha = sha;
    const response = await github(
      path, {method: "PUT", body: JSON.stringify(body)});
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(
        problem.message || `寫入 ${path} 失敗（HTTP ${response.status}）`);
    }
    return response.json();
  }

  async function writeRepoBinary(path, base64Content, message) {
    const current = await readRepoFile(path);
    const body = {message, content: base64Content, branch};
    if (current.sha) body.sha = current.sha;
    const response = await github(
      path, {method: "PUT", body: JSON.stringify(body)});
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(
        problem.message || `寫入圖片 ${path} 失敗（HTTP ${response.status}）`);
    }
    return response.json();
  }

  async function writeRepoJson(path, value, message) {
    const current = await readRepoFile(path);
    return writeRepoFile(
      path, `${JSON.stringify(value, null, 2)}\n`, message, current.sha);
  }

  async function updateCappedList(path, item, limit) {
    const current = await readRepoFile(path);
    let rows = [];
    if (current.content) {
      try {
        const parsed = JSON.parse(current.content);
        if (Array.isArray(parsed)) rows = parsed;
      } catch (error) {
        throw new Error(`${path} 不是有效 JSON，已停止發布`);
      }
    }
    const articleId = item.articleId;
    rows = [
      item,
      ...rows.filter(row => row?.articleId !== articleId),
    ].slice(0, limit);
    return writeRepoFile(
      path,
      `${JSON.stringify(rows, null, 2)}\n`,
      `publish manual article ${articleId}`,
      current.sha,
    );
  }

  async function triggerDeployment(articleId, articleCommit) {
    const path = ".github/deploy-trigger";
    const current = await readRepoFile(path);
    const content = [
      "# Manual article deployment trigger",
      "",
      "This file intentionally triggers the manual-article-deploy workflow.",
      "",
      `article_commit=${articleCommit}`,
      `manual_article_id=${articleId}`,
      `triggered_at=${new Date().toISOString()}`,
      "",
    ].join("\n");
    return writeRepoFile(
      path, content, `deploy manual article ${articleId}`, current.sha);
  }

  function makeJobId() {
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map(value => value.toString(16).padStart(2, "0")).join("");
  }

  async function addImage(file) {
    if (images.length >= 4) {
      throw new Error("最多只能加入 4 張圖片");
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      throw new Error("只接受 JPG、PNG 或 WebP");
    }
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise(resolve =>
      canvas.toBlob(resolve, "image/jpeg", .82));
    if (!blob || blob.size > 2_500_000) {
      throw new Error("圖片壓縮後仍超過 2.5 MB");
    }
    const data = new Uint8Array(await blob.arrayBuffer());
    images.push({
      name: file.name || `pasted-${images.length + 1}.jpg`,
      mime: "image/jpeg",
      data: bytesToBase64(data),
      preview: URL.createObjectURL(blob),
    });
    renderImages();
  }

  function renderImages() {
    els["image-list"].replaceChildren();
    images.forEach((image, index) => {
      const card = document.createElement("div");
      card.className = "image-card";
      card.style.backgroundImage = `url("${image.preview}")`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除 ${image.name}`);
      remove.textContent = "×";
      remove.addEventListener("click", event => {
        event.stopPropagation();
        URL.revokeObjectURL(images[index].preview);
        images.splice(index, 1);
        renderImages();
      });
      card.append(remove);
      els["image-list"].append(card);
    });
  }

  async function acceptFiles(files) {
    text(els["form-error"], "");
    try {
      for (const file of files) await addImage(file);
    } catch (error) {
      text(els["form-error"], error.message);
    }
    els["image-input"].value = "";
  }

  function renderConversation() {
    els["chat-history"].replaceChildren();
    if (!conversation.length) {
      const empty = document.createElement("p");
      empty.className = "empty-chat";
      empty.textContent = "尚無對話。可直接輸入角度、禁語、需保留的名稱或修稿要求。";
      els["chat-history"].append(empty);
      return;
    }
    conversation.forEach(row => {
      const line = document.createElement("p");
      line.className = `chat-line ${row.role}`;
      line.textContent = `${row.role === "user" ? "你" : "AVWIRE"}：${row.text}`;
      els["chat-history"].append(line);
    });
    els["chat-history"].scrollTop = els["chat-history"].scrollHeight;
  }

  function sourceUrls() {
    return [...new Set(els["source-urls"].value.split(/\r?\n/)
      .map(value => value.trim()).filter(Boolean))];
  }

  function clock12(date, timeZone = "Asia/Taipei") {
    return date.toLocaleTimeString("en-US", {
      timeZone,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }

  function setClockInputs(prefix, date = new Date()) {
    const local = new Date(date.getTime() + 8 * 60 * 60 * 1000)
      .toISOString();
    const hour24 = Number(local.slice(11, 13));
    els[`${prefix}-date`].value = local.slice(0, 10);
    els[`${prefix}-hour`].value = String(hour24 % 12 || 12);
    els[`${prefix}-minute`].value = local.slice(14, 16);
    els[`${prefix}-period`].value = hour24 >= 12 ? "PM" : "AM";
  }

  function setTaipeiInputs(date = new Date()) {
    setClockInputs("publication", date);
    setClockInputs("sort", date);
  }

  function taipeiInputUtc(prefix) {
    const date = els[`${prefix}-date`].value;
    const hour12 = Number(els[`${prefix}-hour`].value);
    const minute = els[`${prefix}-minute`].value;
    const period = els[`${prefix}-period`].value;
    if (!date || !Number.isInteger(hour12)
        || hour12 < 1 || hour12 > 12
        || !/^\d{2}$/.test(minute)
        || !["AM", "PM"].includes(period)) return "";
    let hour24 = hour12 % 12;
    if (period === "PM") hour24 += 12;
    const parsed = new Date(
      `${date}T${String(hour24).padStart(2, "0")}:${minute}:00+08:00`);
    return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
  }

  function manualPublicationUtc() {
    return taipeiInputUtc("publication");
  }

  function copyPublicationToSort() {
    ["date", "hour", "minute", "period"].forEach(part => {
      els[`sort-${part}`].value = els[`publication-${part}`].value;
    });
  }

  function updateSortControls() {
    const follows = els["sort-follow-publication"].checked;
    if (follows) copyPublicationToSort();
    els["sort-time-fields"].hidden = follows;
  }

  function manualSortUtc() {
    if (els["sort-follow-publication"].checked) {
      return manualPublicationUtc();
    }
    return taipeiInputUtc("sort");
  }

  function validCustomModel(value) {
    return /^(gemini|nvidia|openrouter):[A-Za-z0-9._/+:-]{2,180}$/
      .test(value);
  }

  function confirmationModel() {
    const selected = els["confirm-model"].value;
    if (selected === "same") {
      return {model: lastResult?.finalModel || "auto", customModel: ""};
    }
    if (selected === "custom") {
      const customModel = els["custom-model"].value.trim();
      if (!validCustomModel(customModel)) {
        throw new Error(
          "自訂模型格式須為 gemini:模型、nvidia:模型或 openrouter:模型");
      }
      return {model: "custom", customModel};
    }
    return {model: selected, customModel: ""};
  }

  function splitParagraphs(value) {
    return value.split(/\r?\n\s*\r?\n/)
      .map(row => row.replace(/\r?\n/g, " ").trim())
      .filter(Boolean);
  }

  function estimateTokens(value) {
    const textValue = String(value || "");
    const cjk = (textValue.match(/[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]/g)
      || []).length;
    const latinWords = (textValue.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g)
      || []).length;
    const other = Math.max(
      0, textValue.replace(/\s/g, "").length - cjk);
    return Math.max(1, Math.ceil(cjk + latinWords * 1.33 + other / 6));
  }

  function writerModelLabels() {
    const labels = [];
    for (let slot = 1; slot <= 5; slot += 1) {
      const value = els[`writer-model-${slot}`].value.trim();
      if (!value) continue;
      if (!/^[^<>\u0000-\u001f]{2,80}$/.test(value)) {
        throw new Error(
          `撰稿模型 ${slot} 必須為 2 至 80 字且不含控制字元`);
      }
      if (!labels.includes(value)) labels.push(value);
    }
    return labels;
  }

  function manualLanguages() {
    const selected = els.language.value;
    return selected === "bilingual" ? ["zh", "en"] : [selected];
  }

  function updateManualLanguageFields() {
    if (workbenchMode !== "manual") return;
    const language = els.language.value;
    const englishOnly = language === "en";
    text(els["manual-primary-title-label"],
      englishOnly ? "Article title (English)" : "文章標題（繁體中文）");
    els["manual-primary-title-label"].append(
      els["manual-title-primary"]);
    text(els["manual-primary-content-label"],
      englishOnly ? "Article content (English)" : "文章內容（繁體中文）");
    els["manual-primary-content-label"].append(
      els["manual-content-primary"]);
    const bilingual = language === "bilingual";
    els["manual-english-mode-panel"].hidden = !bilingual;
    els["manual-secondary-language"].hidden = !bilingual
      || els["manual-english-mode"].value !== "manual";
  }

  function setMode(mode) {
    workbenchMode = mode;
    const manual = mode === "manual";
    els["mode-ai"].classList.toggle("active", !manual);
    els["mode-manual"].classList.toggle("active", manual);
    els["mode-ai"].setAttribute("aria-pressed", String(!manual));
    els["mode-manual"].setAttribute("aria-pressed", String(manual));
    document.querySelectorAll(".ai-only").forEach(node => {
      node.hidden = manual;
    });
    document.querySelectorAll(".manual-only").forEach(node => {
      node.hidden = !manual;
    });
    els["manual-editor"].hidden = !manual;
    els["manual-time-panel"].hidden =
      els["publication-mode"].value !== "manual";
    els["manual-order-panel"].hidden = false;
    els["review-panel"].hidden = true;
    if (manual) {
      if (!els["publication-date"].value) setTaipeiInputs();
      updateSortControls();
      aiArticleType = els["article-type"].value;
      aiLanguage = els.language.value;
      els["article-type"].value = "press_release";
      els.language.value = "bilingual";
      els["article-type"].querySelector('option[value="auto"]').disabled = true;
      text(els.generate, "一鍵送出並發布到網站");
      setWorkflow([
        "檢查手動稿與來源",
        "備份圖片",
        "寫入文章 JSON 與用量紀錄",
        "更新網站資料",
        "部署並確認網站可讀取",
      ]);
    } else {
      els["article-type"].querySelector('option[value="auto"]').disabled = false;
      els["article-type"].value = aiArticleType;
      els.language.value = aiLanguage;
      text(els.generate, "一鍵送出並發布到網站");
      setWorkflow([
        "檢查來源與加密",
        "提交 GitHub Actions",
        "模型生成與 fallback",
        "驗證並組裝文章",
        "發布並確認網站可讀取",
      ]);
    }
    updateManualLanguageFields();
    lastResult = null;
    els["output-panel"].hidden = manual;
    setState("待命", "idle");
    text(els["metric-model"], "—");
    text(els["metric-reasoning"], "—");
    text(els["metric-fallback"], "—");
    text(els["metric-duration"], "—");
    text(els["metric-tokens"], "—");
    text(els["metric-rate"], manual ? "不適用（未呼叫模型）" : "尚無回應標頭");
    els.attempts.innerHTML = '<p class="muted">尚無資料</p>';
  }

  function manualImageSubject() {
    const subject = els["image-description"].value.trim();
    if (subject.length < 4 || subject.length > 240
        || /^(圖片|照片|資料照片|示意圖|image|photo|file photo)$/i.test(subject)
        || subject === els["manual-title-primary"].value.trim()
        || subject === els["manual-title-secondary"].value.trim()) {
      throw new Error("請填寫首張配圖的具體主體，不能只寫資料照片或直接使用新聞標題。");
    }
    return subject;
  }

  function validateForm() {
    if (!validToken) return "私人網址權杖無效";
    if (!validPat(els["github-token"].value.trim())) {
      return "請輸入 fine-grained GitHub PAT";
    }
    const urls = sourceUrls();
    if (!urls.length || urls.length > 10) return "請提供 1 至 10 個來源網址";
    if (!urls.every(url => /^https?:\/\//i.test(url))) {
      return "來源網址只能使用 http:// 或 https://";
    }
    if (workbenchMode === "manual") {
      if (images.length) {
        try { manualImageSubject(); } catch (error) { return error.message; }
      }
      if (!els["manual-title-primary"].value.trim()) {
        return "請輸入文章標題";
      }
      if (!splitParagraphs(els["manual-content-primary"].value).length) {
        return "請輸入文章內容";
      }
      if (els.language.value === "bilingual"
          && els["manual-english-mode"].value === "manual"
          && (!els["manual-title-secondary"].value.trim()
              || !splitParagraphs(
                els["manual-content-secondary"].value).length)) {
        return "雙語模式必須同時填寫繁中與英文標題及內容";
      }
      try {
        if (!writerModelLabels().length) {
          return "完全手動模式請至少填寫一個撰稿模型署名";
        }
      } catch (error) {
        return error.message;
      }
      if (els["publication-mode"].value === "manual"
          && !manualPublicationUtc()) {
        return "請指定有效的文章日期與時間";
      }
    }
    if (workbenchMode === "ai"
        && els["publication-mode"].value === "manual"
        && !manualPublicationUtc()) {
      return "請指定有效的臺北文章日期與時間";
    }
    if (!els["sort-follow-publication"].checked && !manualSortUtc()) {
      return "請指定有效的網站排序日期與時間";
    }
    try {
      writerModelLabels();
    } catch (error) {
      return error.message;
    }
    const encodedImages = images.reduce(
      (sum, image) => sum + image.data.length, 0);
    if (encodedImages > 12_000_000) return "圖片總量過大，請移除部分圖片";
    return "";
  }

  function manualArticle(jobId, imageUrls, fixedArticleId = "") {
    const language = els.language.value;
    const languages = manualLanguages();
    const primaryTitle = els["manual-title-primary"].value.trim();
    const primaryBody = splitParagraphs(els["manual-content-primary"].value);
    const secondaryTitle = els["manual-title-secondary"].value.trim();
    const secondaryBody = splitParagraphs(
      els["manual-content-secondary"].value);
    const empty = {title: "", summary: "", body: []};
    const block = (title, body) => ({
      title,
      summary: (body[0] || title).slice(0, 180),
      body,
    });
    const zh = language === "en"
      ? empty : block(primaryTitle, primaryBody);
    const en = language === "en"
      ? block(primaryTitle, primaryBody)
      : (language === "bilingual"
        ? block(secondaryTitle, secondaryBody) : empty);
    const now = new Date();
    const publicationTime = manualPublicationUtc();
    const sortTime = manualSortUtc();
    const writerModels = writerModelLabels();
    const compact = now.toISOString()
      .replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
    const articleId = fixedArticleId
      || `a-${compact}-manual-${jobId.slice(0, 6)}`;
    const sources = sourceUrls().map(url => {
      let name = url;
      try {
        name = new URL(url).hostname.replace(/^www\./, "");
      } catch (error) {
        // URL validation already ran; retain the URL as a safe fallback name.
      }
      return {name, url};
    });
    const category = {
      incident: "safety",
      regulation: "reg",
      fleet_order: "biz",
      financial: "biz",
    }[els["article-type"].value] || "ops";
    const attachments = imageUrls.map((url, index) => ({
      url,
      kind: index === 0 ? "article_image" : "attachment",
    }));
    return {
      id: articleId,
      publishedUtc: publicationTime,
      sortUtc: sortTime,
      cat: category,
      primarySource: sources[0]?.name || "Manual source",
      image: imageUrls[0] ? {
        url: imageUrls[0],
        provider: "AVWIRE manual upload",
        subject: manualImageSubject(),
        kind: "file_photo",
      } : null,
      zh,
      en,
      sources,
      writer: `manual:${writerModels.join("、")}`,
      writerModels,
      articleFormat: "full",
      availableLanguages: languages,
      manualArticleType: els["article-type"].value,
      attachments,
    };
  }

  function imageUrlsForArticle(articleId) {
    return images.map((image, index) =>
      `${location.origin}${basePath}/assets/${articleId}-image-${index + 1}.jpg`);
  }

  async function uploadManualImages(articleId) {
    let latestCommit = "";
    for (const [index, image] of images.entries()) {
      const path = `static/${articleId}-image-${index + 1}.jpg`;
      const result = await writeRepoBinary(
        path, image.data, `upload manual article image ${articleId}`);
      latestCommit = result.commit?.sha || latestCommit;
      addLog(`圖片 ${index + 1}/${images.length} 已備份`);
    }
    return latestCommit;
  }

  function usageModelsFromResult(result) {
    const grouped = new Map();
    const add = (label, tokens, estimated = false) => {
      if (!label) return;
      const row = grouped.get(label) || {
        label, inputTokens: 0, outputTokens: 0, estimated,
      };
      row.inputTokens += Number(tokens?.input || 0);
      row.outputTokens += Number(tokens?.output || 0);
      row.estimated ||= estimated;
      grouped.set(label, row);
    };
    for (const attempt of result?.attempts || []) {
      add(attempt.model, attempt.tokens);
    }
    for (const row of result?.requestLog || []) {
      if (row.tokens) add("gemini:gemini-3.6-flash", row.tokens);
    }
    return [...grouped.values()];
  }

  function manualUsageModels(article) {
    const allText = [
      article.zh.title, ...article.zh.body,
      article.en.title, ...article.en.body,
    ].join("\n");
    const labels = article.writerModels?.length
      ? article.writerModels
      : [article.writer.replace(/^manual:/, "")];
    return labels.map(label => ({
      label,
      inputTokens: 0,
      outputTokens: estimateTokens(allText),
      estimated: true,
    }));
  }

  async function recordPublicationUsage(article, mode, result = null) {
    const current = await readRepoFile("data/usage.json");
    let ledger = {};
    try {
      ledger = current.content ? JSON.parse(current.content) : {};
    } catch (error) {
      throw new Error("data/usage.json 不是有效 JSON，已停止發布");
    }
    ledger.models = typeof ledger.models === "object" && ledger.models
      ? ledger.models : {};
    ledger.daily = typeof ledger.daily === "object" && ledger.daily
      ? ledger.daily : {};
    ledger.recentRuns = Array.isArray(ledger.recentRuns)
      ? ledger.recentRuns : [];
    const stamp = new Date().toISOString();
    const resourceUsage = {
      actualUsd: 0,
      models: mode === "manual"
        ? manualUsageModels(article) : usageModelsFromResult(result),
    };
    if (mode === "ai") {
      const groupId = `manual-${result.id}`;
      const existing = ledger.recentRuns.find(
        row => row && row.groupId === groupId);
      if (existing) {
        existing.articleId = article.id;
        existing.result = "published";
        existing.finalStatus = "publish";
        existing.resourceUsage = resourceUsage;
      } else {
        ledger.recentRuns.unshift({
          startedUtc: result.completedUtc || stamp,
          finishedUtc: stamp,
          workflow: "manual",
          taskType: "manual_article",
          groupId,
          sourceCount: sourceUrls().length,
          primarySource: article.primarySource,
          result: "published",
          articleId: article.id,
          finalStatus: "publish",
          finalModel: result.finalModel,
          fallbackUsed: result.fallbackUsed === true,
          durationsMs: {},
          attempts: [],
          resourceUsage,
        });
      }
    } else {
      ledger.recentRuns = ledger.recentRuns.filter(
        row => row?.articleId !== article.id);
      ledger.recentRuns.unshift({
        startedUtc: operationStartedAt
          ? new Date(operationStartedAt).toISOString() : stamp,
        finishedUtc: stamp,
        workflow: "manual_workbench",
        taskType: "manual_article",
        groupId: article.id,
        sourceCount: sourceUrls().length,
        primarySource: article.primarySource,
        result: "published",
        articleId: article.id,
        finalStatus: "publish",
        finalModel: article.writer,
        fallbackUsed: false,
        durationsMs: {
          total: operationStartedAt ? Date.now() - operationStartedAt : 0,
        },
        attempts: [],
        resourceUsage,
      });
    }
    const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000;
    ledger.recentRuns = ledger.recentRuns.filter(row => {
      const parsed = Date.parse(row?.startedUtc || row?.finishedUtc || "");
      return Number.isFinite(parsed) && parsed >= cutoff;
    }).slice(0, 1000);
    ledger.updatedUtc = stamp.replace(/:\d{2}\.\d{3}Z$/, "Z");
    ledger.trackingSinceUtc ||= ledger.updatedUtc;
    return writeRepoFile(
      "data/usage.json",
      `${JSON.stringify(ledger, null, 2)}\n`,
      `record private manual usage ${article.id}`,
      current.sha,
    );
  }

  async function waitForPublishedArticle(article) {
    const available = Array.isArray(article.availableLanguages)
      ? article.availableLanguages : ["zh", "en"];
    const lang = available.includes("zh") ? "zh" : "en";
    const langPath = lang === "en" ? "en/" : "";
    const url = `${basePath}/${langPath}news/${article.id}/`;
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const response = await fetch(`${url}?check=${Date.now()}`, {
        cache: "no-store",
      }).catch(() => null);
      if (response?.ok) return url;
      await sleep(10000);
    }
    throw new Error(
      "GitHub 已接受發布，但 10 分鐘內尚未確認 Pages 上線");
  }

  async function submitJob(payload, jobId) {
    const envelope = await encrypt(payload, jobId);
    const body = {
      message: `queue encrypted manual draft ${jobId}`,
      content: bytesToBase64(
        new TextEncoder().encode(JSON.stringify(envelope))),
      branch,
    };
    const response = await github(
      `data/manual-jobs/inbox/${jobId}.json`,
      {method: "PUT", body: JSON.stringify(body)},
    );
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(
        problem.message || `GitHub 提交失敗（HTTP ${response.status}）`);
    }
  }

  async function pollResult(jobId) {
    const deadline = Date.now() + 20 * 60 * 1000;
    let misses = 0;
    while (Date.now() < deadline) {
      await sleep(misses < 6 ? 5000 : 10000);
      const response = await github(
        `data/manual-jobs/outbox/${jobId}.json?ref=${encodeURIComponent(branch)}`);
      if (response.status === 404) {
        misses += 1;
        if (misses === 1) addLog("GitHub Actions 已排隊，等待模型生成");
        continue;
      }
      if (!response.ok) {
        throw new Error(`讀取工作結果失敗（HTTP ${response.status}）`);
      }
      const file = await response.json();
      const envelope = JSON.parse(
        new TextDecoder().decode(base64ToBytes(file.content)));
      return decrypt(envelope, jobId);
    }
    throw new Error("等待超過 20 分鐘；工作可能仍在 GitHub Actions 執行");
  }

  function rateSummary(result) {
    const values = [];
    for (const attempt of result.attempts || []) {
      for (const request of attempt.requests || []) {
        const headers = request.headers || {};
        const parts = Object.entries(headers)
          .filter(([key]) => key.includes("ratelimit") || key === "retry-after")
          .map(([key, value]) => `${key}: ${value}`);
        if (parts.length) values.push(`${attempt.displayName}: ${parts.join(", ")}`);
      }
    }
    for (const row of result.requestLog || []) {
      const parts = Object.entries(row.rateLimit || {})
        .map(([key, value]) => `${key}: ${value}`);
      if (parts.length) values.push(`圖片 OCR: ${parts.join(", ")}`);
    }
    return values.length ? values.join(" ｜ ") : "供應商未回傳 rate-limit 標頭";
  }

  function renderPreviewBody(element, paragraphs) {
    element.replaceChildren();
    for (const paragraph of paragraphs || []) {
      const node = document.createElement("p");
      node.textContent = paragraph;
      element.append(node);
    }
  }

  function publicationTimeLabel(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value || "—";
    const date = parsed.toLocaleDateString("zh-TW", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    return `${date} ${clock12(parsed)}（UTC+8）`;
  }

  function renderReview(result) {
    const draft = result.draft || {};
    const publication = result.publication || {};
    const zh = draft.zh || {};
    const en = draft.en || {};
    text(els["review-type"],
      ARTICLE_TYPE_LABELS[result.detectedArticleType] ||
      result.detectedArticleType || "—");
    text(els["review-time"],
      publicationTimeLabel(result.publicationTimeUtc));
    text(els["review-time-source"],
      TIME_SOURCE_LABELS[result.publicationTimeSource] ||
      result.publicationTimeSource || "—");
    text(els["review-draft-status"], draft.status || "—");
    text(els["preview-zh-title"], zh.title || "—");
    text(els["preview-zh-summary"], zh.summary || "");
    renderPreviewBody(els["preview-zh-body"], zh.body);
    text(els["preview-en-title"], en.title || "—");
    text(els["preview-en-summary"], en.summary || "");
    renderPreviewBody(els["preview-en-body"], en.body);
    els["review-panel"].hidden = false;
    els["regenerate"].disabled = false;
    els.publish.disabled = !publication.article;
    text(els["review-status"],
      publication.article ? "驗證完成" : "不可發布");
    els["review-status"].className = publication.article
      ? "job-state working" : "job-state error";
    text(els["publish-state"], publication.article
      ? "驗證完成，系統將自動寫入 JSON 並部署。"
      : "此草稿未通過發布組裝，請更換模型或調整資料後重新生成。");
  }

  function displayResult(result) {
    text(els["metric-model"],
      result.finalModelName || result.finalModel || "全部模型失敗");
    text(els["metric-reasoning"],
      result.reasoningEffective || result.reasoningTier || "—");
    text(els["metric-fallback"], result.fallbackUsed ? "已啟用" : "未啟用");
    const totalMs = [
      ...(result.attempts || []).map(row => row.durationMs || 0),
      ...(result.requestLog || []).map(row => row.durationMs || 0),
    ].reduce((sum, value) => sum + value, 0);
    text(els["metric-duration"], `${(totalMs / 1000).toFixed(1)} 秒`);
    const tokens = (result.attempts || []).reduce(
      (sum, row) => ({
        input: sum.input + (row.tokens?.input || 0),
        output: sum.output + (row.tokens?.output || 0),
      }), {input: 0, output: 0});
    for (const row of result.requestLog || []) {
      tokens.input += row.tokens?.input || 0;
      tokens.output += row.tokens?.output || 0;
    }
    text(els["metric-tokens"], `${tokens.input.toLocaleString()} in / ${tokens.output.toLocaleString()} out`);
    text(els["metric-rate"], rateSummary(result));

    els.attempts.replaceChildren();
    for (const row of result.attempts || []) {
      const block = document.createElement("div");
      block.className = `attempt ${row.outcome}`;
      const title = document.createElement("strong");
      title.textContent = `${row.displayName} · ${row.outcome === "success" ? "成功" : "失敗"}`;
      const detail = document.createElement("span");
      detail.textContent = [
        row.reasoning,
        `${(row.durationMs / 1000).toFixed(1)} 秒`,
        row.failureClass,
        row.failureMessage,
      ].filter(Boolean).join(" · ");
      block.append(title, detail);
      els.attempts.append(block);
    }
    for (const row of result.requestLog || []) {
      addLog(`${row.stage}：${row.message}`);
    }
    if (result.status !== "success") {
      throw new Error(result.error || "生成失敗");
    }
    lastResult = result;
    const publicationJson = result.publication?.article
      ? {articles: [result.publication.article]}
      : result.draft;
    els["json-output"].value = JSON.stringify(publicationJson, null, 2);
    els["copy-json"].disabled = false;
    els["download-json"].disabled = false;
    renderReview(result);
    addLog(`生成與驗證完成：${result.finalModelName}`);
    conversation.push({
      role: "assistant",
      text: `${result.finalModelName} 已產出 ${result.draft.status} 內容，準備自動發布。`,
    });
    renderConversation();
  }

  async function generate(selection = null, previousDraft = null) {
    text(els["form-error"], "");
    const problem = validateForm();
    if (problem) {
      text(els["form-error"], problem);
      return;
    }
    els.generate.disabled = true;
    els.regenerate.disabled = true;
    els.publish.disabled = true;
    lastResult = null;
    els["json-output"].value = "";
    els["copy-json"].disabled = true;
    els["download-json"].disabled = true;
    setWorkflow([
      "檢查來源與加密",
      "提交 GitHub Actions",
      "模型生成與 fallback",
      "驗證並組裝文章",
      "發布並確認網站可讀取",
    ]);
    setWorkflowStep(0, "active");
    setState("加密提交中", "working");
    els["request-log"].dataset.empty = "true";
    els["request-log"].replaceChildren();
    const instruction = els.instruction.value.trim();
    if (instruction && !previousDraft) {
      conversation.push({role: "user", text: instruction});
      renderConversation();
    }
    const jobId = makeJobId();
    const requested = selection || {
      model: els.model.value,
      customModel: "",
    };
    const payload = {
      version: 1,
      articleType: els["article-type"].value,
      language: els.language.value,
      model: requested.model,
      customModel: requested.customModel,
      reasoningTier: els["reasoning-tier"].value,
      sourceUrls: sourceUrls(),
      sourceText: els["source-text"].value,
      articleSummary: els["article-summary"].value,
      publicationMode: els["publication-mode"].value,
      publicationTimeUtc: (
        els["publication-mode"].value === "manual"
          ? manualPublicationUtc() : ""
      ),
      sortMode: (
        els["sort-follow-publication"].checked ? "publication" : "manual"
      ),
      sortTimeUtc: (
        els["sort-follow-publication"].checked ? "" : manualSortUtc()
      ),
      writerModels: writerModelLabels(),
      images: images.map(({mime, data}) => ({mime, data})),
      instruction,
      conversation: conversation.slice(-12),
      previousDraft,
      submittedUtc: new Date().toISOString(),
    };
    try {
      await rememberPat(
        els["github-token"].value.trim(), patInputRevision);
      addLog("在瀏覽器內以 AES-256-GCM 加密來源與圖片");
      setWorkflowStep(0, "done");
      setWorkflowStep(1, "active");
      await submitJob(payload, jobId);
      addLog("加密工作已提交；repository 內只保存密文");
      setWorkflowStep(1, "done");
      setWorkflowStep(2, "active");
      setState("模型生成中", "working");
      const result = await pollResult(jobId);
      displayResult(result);
      setWorkflowStep(2, "done");
      setWorkflowStep(3, "active");
      setState("驗證文章", "working");
      if (!result.publication?.article) {
        throw new Error("內容未通過發布驗證，未寫入網站");
      }
      await publishArticle();
      els.instruction.value = "";
    } catch (error) {
      text(els["form-error"], error.message || "工作失敗");
      addLog(`失敗：${error.message || "未知錯誤"}`);
      failActiveWorkflow();
      setState("失敗", "error");
    } finally {
      els.generate.disabled = false;
      if (lastResult) {
        els.regenerate.disabled = false;
        els.publish.disabled = !lastResult.publication?.article;
      }
    }
  }

  async function regenerateDraft() {
    if (!lastResult?.draft) return;
    try {
      const selected = confirmationModel();
      conversation.push({
        role: "user",
        text: `確認階段改用 ${selected.customModel || selected.model} 重新生成。`,
      });
      renderConversation();
      await generate(selected, lastResult.draft);
    } catch (error) {
      text(els["form-error"], error.message || "無法重新生成");
    }
  }

  function manualNeedsTranslation() {
    return (
      els.language.value === "bilingual"
      && els["manual-english-mode"].value === "auto"
    );
  }

  function manualNeedsPreparation() {
    return (
      manualNeedsTranslation()
      || els["publication-mode"].value === "auto"
    );
  }

  function manualArticleBlock(titleId, contentId) {
    const body = splitParagraphs(els[contentId].value);
    return {
      title: els[titleId].value.trim(),
      summary: (body[0] || "").slice(0, 180),
      body,
    };
  }

  async function prepareAndPublishManualArticle() {
    text(els["form-error"], "");
    const problem = validateForm();
    if (problem) {
      text(els["form-error"], problem);
      return;
    }
    operationStartedAt = Date.now();
    const jobId = makeJobId();
    const translationOnly = manualNeedsTranslation();
    const secondary = (
      els.language.value === "bilingual"
      && els["manual-english-mode"].value === "manual"
    ) ? manualArticleBlock(
        "manual-title-secondary", "manual-content-secondary") : null;
    const payload = {
      version: 1,
      operatorAuthored: true,
      translationOnly,
      articleType: els["article-type"].value,
      language: els.language.value,
      model: els.model.value,
      customModel: "",
      reasoningTier: els["reasoning-tier"].value,
      sourceUrls: sourceUrls(),
      sourceText: "",
      articleSummary: "",
      publicationMode: els["publication-mode"].value,
      publicationTimeUtc: (
        els["publication-mode"].value === "manual"
          ? manualPublicationUtc() : ""
      ),
      sortMode: (
        els["sort-follow-publication"].checked ? "publication" : "manual"
      ),
      sortTimeUtc: (
        els["sort-follow-publication"].checked ? "" : manualSortUtc()
      ),
      writerModels: writerModelLabels(),
      manualArticle: manualArticleBlock(
        "manual-title-primary", "manual-content-primary"),
      manualEnglishArticle: secondary,
      images: [],
      instruction: "",
      conversation: [],
      previousDraft: null,
      submittedUtc: new Date().toISOString(),
    };
    els.generate.disabled = true;
    els.regenerate.disabled = true;
    els.publish.disabled = true;
    lastResult = null;
    els["request-log"].dataset.empty = "true";
    els["request-log"].replaceChildren();
    setWorkflow([
      "檢查手動稿與來源",
      "提交加密背景工作",
      translationOnly
        ? "模型翻譯、來源時間辨識與 fallback"
        : "來源時間辨識與 fallback",
      "驗證手動文章",
      "發布並確認網站可讀取",
    ]);
    setWorkflowStep(0, "active");
    setState("加密提交中", "working");
    try {
      await rememberPat(
        els["github-token"].value.trim(), patInputRevision);
      setWorkflowStep(0, "done");
      setWorkflowStep(1, "active");
      await submitJob(payload, jobId);
      addLog("手動稿已加密提交，repository 只保存密文");
      setWorkflowStep(1, "done");
      setWorkflowStep(2, "active");
      setState(
        translationOnly ? "等待翻譯與時間辨識" : "辨識來源時間中",
        "working");
      const result = await pollResult(jobId);
      displayResult(result);
      setWorkflowStep(2, "done");
      setWorkflowStep(3, "active");
      setState("驗證手動文章", "working");
      if (!result.publication?.article) {
        throw new Error("手動稿未通過驗證，未寫入網站");
      }
      await publishArticle();
    } catch (error) {
      text(els["form-error"], error.message || "時間辨識、翻譯或發布失敗");
      addLog(`手動稿處理中斷：${error.message || "未知錯誤"}`);
      failActiveWorkflow();
      setState("流程中斷", "error");
    } finally {
      els.generate.disabled = false;
      if (lastResult) {
        els.regenerate.disabled = false;
        els.publish.disabled = !lastResult.publication?.article;
      }
    }
  }

  async function publishManualArticle() {
    text(els["form-error"], "");
    const problem = validateForm();
    if (problem) {
      text(els["form-error"], problem);
      return;
    }
    operationStartedAt = Date.now();
    const jobId = makeJobId();
    const previewId = `a-${new Date().toISOString()
      .replace(/[-:]/g, "").slice(0, 13).replace("T", "-")}`
      + `-manual-${jobId.slice(0, 6)}`;
    const imageUrls = imageUrlsForArticle(previewId);
    const article = manualArticle(jobId, imageUrls, previewId);
    const articlePath = `data/articles/manual-${jobId}.json`;
    const modelLabel = writerModelLabels().join("、");
    const outputTokens = manualUsageModels(article)[0].outputTokens;
    els.generate.disabled = true;
    els["request-log"].dataset.empty = "true";
    els["request-log"].replaceChildren();
    els.attempts.innerHTML =
      '<p class="muted">完全手動模式沒有模型 API 呼叫。</p>';
    text(els["metric-model"], modelLabel);
    text(els["metric-reasoning"], "手動撰稿／不呼叫 API");
    text(els["metric-fallback"], "不適用");
    text(els["metric-tokens"],
      `0 in / 約 ${outputTokens.toLocaleString()} out`);
    text(els["metric-rate"], "不適用（未呼叫模型）");
    setWorkflow([
      "檢查手動稿與來源",
      "備份圖片",
      "寫入文章 JSON 與用量紀錄",
      "更新網站資料",
      "部署並確認網站可讀取",
    ]);
    setWorkflowStep(0, "active");
    setState("檢查手動稿", "working");
    try {
      await rememberPat(
        els["github-token"].value.trim(), patInputRevision);
      setWorkflowStep(0, "done");
      setWorkflowStep(1, "active");
      setState("備份圖片", "working");
      let latestCommit = await uploadManualImages(article.id);
      setWorkflowStep(1, "done");
      setWorkflowStep(2, "active");
      setState("備份文章與用量", "working");
      const articleResult = await writeRepoJson(
        articlePath,
        {articles: [article]},
        `publish manual article ${article.id}`,
      );
      latestCommit = articleResult.commit?.sha || latestCommit;
      addLog(`文章 JSON 已自動備份：${articlePath}`);
      const usageResult = await recordPublicationUsage(
        article, "manual");
      latestCommit = usageResult.commit?.sha || latestCommit;
      addLog("私人補稿用量已加入 30 天逐篇紀錄");
      setWorkflowStep(2, "done");
      setWorkflowStep(3, "active");
      setState("更新網站資料", "working");
      const available = article.availableLanguages;
      const flash = {
        timeUtc: article.sortUtc || article.publishedUtc,
        hot: els["article-type"].value === "flash",
        zh: article.zh.title || article.en.title,
        en: article.en.title || article.zh.title,
        articleId: article.id,
        availableLanguages: available,
      };
      const flashResult = await updateCappedList(
        "data/flashes.json", flash, 10);
      latestCommit = flashResult.commit?.sha || latestCommit;
      addLog("首頁快訊與文章索引已同步");
      setWorkflowStep(3, "done");
      setWorkflowStep(4, "active");
      setState("Pages 建置中", "working");
      await triggerDeployment(article.id, latestCommit);
      addLog("GitHub Pages 部署已觸發，正在確認正式文章網址");
      const publishedUrl = await waitForPublishedArticle(article);
      setWorkflowStep(4, "done");
      setState("發布完成", "success");
      const elapsed = Date.now() - operationStartedAt;
      text(els["metric-duration"], `${(elapsed / 1000).toFixed(1)} 秒`);
      addLog(`正式文章已上線：${publishedUrl}`);
      text(els.generate, "已發布；可修改內容後送出下一篇");
    } catch (error) {
      failActiveWorkflow();
      text(els["form-error"], error.message || "手動發布失敗");
      addLog(`發布中斷：${error.message || "未知錯誤"}`);
      setState("流程中斷", "error");
    } finally {
      els.generate.disabled = false;
    }
  }

  async function publishArticle() {
    const publication = lastResult?.publication;
    const article = publication?.article;
    if (!article || !publication.articlePath) {
      text(els["publish-state"], "目前沒有可發布的文章資料。");
      return;
    }
    if (!/^data\/articles\/manual-[0-9a-f]{32}\.json$/
      .test(publication.articlePath)) {
      text(els["publish-state"], "文章路徑驗證失敗，已停止發布。");
      return;
    }
    els.publish.disabled = true;
    els.regenerate.disabled = true;
    els.generate.disabled = true;
    setWorkflowStep(3, "done");
    setWorkflowStep(4, "active");
    setState("發布至 GitHub", "working");
    text(els["review-status"], "發布中");
    els["review-status"].className = "job-state working";
    text(els["publish-state"], "正在上傳文章 JSON 與更新網站資料…");
    try {
      let latestCommit = "";
      if (lastResult.operatorAuthored && images.length) {
        const imageSubject = manualImageSubject();
        const imageUrls = imageUrlsForArticle(article.id);
        latestCommit = await uploadManualImages(article.id);
        article.image = {
          url: imageUrls[0],
          provider: "AVWIRE manual upload",
          subject: imageSubject,
          kind: "file_photo",
        };
        article.attachments = imageUrls.map((url, index) => ({
          url,
          kind: index === 0 ? "article_image" : "attachment",
        }));
      }
      const articleResult = await writeRepoJson(
        publication.articlePath,
        {articles: [article]},
        `publish manual article ${article.id}`,
      );
      addLog(`文章 JSON 已寫入 ${publication.articlePath}`);
      latestCommit = articleResult.commit?.sha || latestCommit;
      if (publication.flash) {
        const result = await updateCappedList(
          "data/flashes.json", publication.flash, 10);
        latestCommit = result.commit?.sha || latestCommit;
        addLog("首頁快訊資料已同步");
      }
      if (publication.incident) {
        const result = await updateCappedList(
          "data/incidents.json", publication.incident, 60);
        latestCommit = result.commit?.sha || latestCommit;
        addLog("事故／事件資料已同步");
      }
      const usageResult = await recordPublicationUsage(
        article, "ai", lastResult);
      latestCommit = usageResult.commit?.sha || latestCommit;
      addLog("私人補稿 token 與理論花費資料已逐篇記錄");
      await triggerDeployment(article.id, latestCommit);
      addLog("Pages 部署已觸發，正在確認正式文章網址");
      const publishedUrl = await waitForPublishedArticle(article);
      addLog(`正式文章已上線：${publishedUrl}`);
      text(els["publish-state"],
        `發布完成：${article.id}`);
      text(els["review-status"], "發布完成");
      els["review-status"].className = "job-state success";
      setWorkflowStep(4, "done");
      setState("發布完成", "success");
    } catch (error) {
      text(els["publish-state"], error.message || "發布失敗");
      text(els["review-status"], "發布失敗");
      els["review-status"].className = "job-state error";
      addLog(`發布失敗：${error.message || "未知錯誤"}`);
      failActiveWorkflow();
      setState("發布失敗", "error");
      els.publish.disabled = false;
      els.regenerate.disabled = false;
    } finally {
      els.generate.disabled = false;
    }
  }

  els["github-token"].addEventListener("input", savePatOnInput);
  els["clear-token"].addEventListener("click", () => {
    patInputRevision += 1;
    els["github-token"].value = "";
    try {
      localStorage.removeItem(PAT_STORAGE_KEY);
    } catch (error) {
      // The input is still cleared when browser storage is unavailable.
    }
    text(els["security-state"], "網址權杖有效 · PAT 已清除");
  });
  els["image-input"].addEventListener(
    "change", event => acceptFiles(event.target.files));
  els["upload-zone"].addEventListener("dragover", event => {
    event.preventDefault();
    els["upload-zone"].classList.add("drag");
  });
  els["upload-zone"].addEventListener("dragleave", () =>
    els["upload-zone"].classList.remove("drag"));
  els["upload-zone"].addEventListener("drop", event => {
    event.preventDefault();
    els["upload-zone"].classList.remove("drag");
    acceptFiles(event.dataTransfer.files);
  });
  document.addEventListener("paste", event => {
    const files = [...event.clipboardData.items]
      .filter(item => item.kind === "file" && item.type.startsWith("image/"))
      .map(item => item.getAsFile()).filter(Boolean);
    if (files.length) {
      event.preventDefault();
      acceptFiles(files);
    }
  });
  els["clear-chat"].addEventListener("click", () => {
    conversation.splice(0);
    renderConversation();
  });
  els["mode-ai"].addEventListener("click", () => setMode("ai"));
  els["mode-manual"].addEventListener("click", () => setMode("manual"));
  els.language.addEventListener("change", updateManualLanguageFields);
  els["manual-english-mode"].addEventListener(
    "change", updateManualLanguageFields);
  els["publication-mode"].addEventListener("change", () => {
    const manual = els["publication-mode"].value === "manual";
    els["manual-time-panel"].hidden = !manual;
    if (manual && !els["publication-date"].value) {
      setTaipeiInputs();
    }
  });
  els["sort-follow-publication"].addEventListener(
    "change", updateSortControls);
  [
    "publication-date", "publication-hour",
    "publication-minute", "publication-period",
  ].forEach(id => {
    els[id].addEventListener("change", () => {
      if (els["sort-follow-publication"].checked) {
        copyPublicationToSort();
      }
    });
  });
  els["confirm-model"].addEventListener("change", () => {
    els["custom-model-panel"].hidden =
      els["confirm-model"].value !== "custom";
  });
  els.generate.addEventListener("click", () => {
    if (workbenchMode === "manual") {
      if (manualNeedsPreparation()) {
        prepareAndPublishManualArticle();
      } else {
        publishManualArticle();
      }
    } else {
      generate();
    }
  });
  els.regenerate.addEventListener("click", regenerateDraft);
  els.publish.addEventListener("click", publishArticle);
  els["copy-json"].addEventListener("click", async () => {
    await navigator.clipboard.writeText(els["json-output"].value);
    text(els["copy-json"], "已複製");
    setTimeout(() => text(els["copy-json"], "複製"), 1300);
  });
  els["download-json"].addEventListener("click", () => {
    if (!els["json-output"].value) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob(
      [els["json-output"].value], {type: "application/json"}));
    link.download = lastResult?.publication?.article?.id
      ? `${lastResult.publication.article.id}.json`
      : `avwire-manual-${Date.now()}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });

  els["request-log"].dataset.empty = "true";
  setTaipeiInputs();
  setMode("ai");
  const restoredPat = validToken && await restorePat();
  if (validToken) {
    text(els["security-state"], restoredPat
      ? "網址權杖有效 · PAT 已自動解鎖"
      : "網址權杖有效 · AES-256-GCM");
  } else {
    text(els["security-state"], "私人網址無效");
    text(els["form-error"], "此頁缺少有效的私人網址權杖");
    els.generate.disabled = true;
  }
})();
