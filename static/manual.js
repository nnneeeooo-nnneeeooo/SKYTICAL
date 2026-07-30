(async () => {
  "use strict";

  const app = document.querySelector("#app");
  const repository = app.dataset.repository;
  const branch = app.dataset.branch;
  const els = Object.fromEntries([
    "github-token", "clear-token", "source-urls", "source-text",
    "image-input", "image-list", "upload-zone", "article-type", "language",
    "model", "reasoning-tier", "chat-history", "instruction", "clear-chat",
    "generate", "form-error", "security-state", "job-state", "metric-model",
    "metric-reasoning", "metric-fallback", "metric-duration",
    "metric-tokens", "metric-rate", "attempts", "request-log",
    "json-output", "copy-json", "download-json",
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
  let lastDraft = null;

  const text = (element, value) => { element.textContent = value; };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function setState(label, kind = "idle") {
    text(els["job-state"], label);
    els["job-state"].className = `job-state ${kind}`;
  }

  function addLog(message) {
    if (els["request-log"].dataset.empty !== "false") {
      els["request-log"].replaceChildren();
      els["request-log"].dataset.empty = "false";
    }
    const item = document.createElement("li");
    item.textContent = `${new Date().toLocaleTimeString("zh-TW")}　${message}`;
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
    const encodedImages = images.reduce(
      (sum, image) => sum + image.data.length, 0);
    if (encodedImages > 12_000_000) return "圖片總量過大，請移除部分圖片";
    return "";
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
    lastDraft = result.draft;
    els["json-output"].value = JSON.stringify(result.draft, null, 2);
    els["copy-json"].disabled = false;
    els["download-json"].disabled = false;
    addLog(`生成完成：${result.finalModelName}`);
    conversation.push({
      role: "assistant",
      text: `${result.finalModelName} 已產出 ${result.draft.status} JSON。`,
    });
    renderConversation();
  }

  async function generate() {
    text(els["form-error"], "");
    const problem = validateForm();
    if (problem) {
      text(els["form-error"], problem);
      return;
    }
    els.generate.disabled = true;
    lastDraft = null;
    els["json-output"].value = "";
    els["copy-json"].disabled = true;
    els["download-json"].disabled = true;
    setState("加密提交中", "working");
    els["request-log"].dataset.empty = "true";
    els["request-log"].replaceChildren();
    const instruction = els.instruction.value.trim();
    if (instruction) {
      conversation.push({role: "user", text: instruction});
      renderConversation();
    }
    const jobId = makeJobId();
    const payload = {
      version: 1,
      articleType: els["article-type"].value,
      language: els.language.value,
      model: els.model.value,
      reasoningTier: els["reasoning-tier"].value,
      sourceUrls: sourceUrls(),
      sourceText: els["source-text"].value,
      images: images.map(({mime, data}) => ({mime, data})),
      instruction,
      conversation: conversation.slice(-12),
      submittedUtc: new Date().toISOString(),
    };
    try {
      await rememberPat(
        els["github-token"].value.trim(), patInputRevision);
      addLog("在瀏覽器內以 AES-256-GCM 加密來源與圖片");
      await submitJob(payload, jobId);
      addLog("加密工作已提交；repository 內只保存密文");
      setState("模型生成中", "working");
      const result = await pollResult(jobId);
      displayResult(result);
      setState("完成", "success");
      els.instruction.value = "";
    } catch (error) {
      text(els["form-error"], error.message || "工作失敗");
      addLog(`失敗：${error.message || "未知錯誤"}`);
      setState("失敗", "error");
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
  els.generate.addEventListener("click", generate);
  els["copy-json"].addEventListener("click", async () => {
    await navigator.clipboard.writeText(els["json-output"].value);
    text(els["copy-json"], "已複製");
    setTimeout(() => text(els["copy-json"], "複製"), 1300);
  });
  els["download-json"].addEventListener("click", () => {
    if (!lastDraft) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob(
      [JSON.stringify(lastDraft, null, 2)], {type: "application/json"}));
    link.download = `avwire-manual-${Date.now()}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });

  els["request-log"].dataset.empty = "true";
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
