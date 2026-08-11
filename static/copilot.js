(async () => {
  "use strict";

  const app = document.getElementById("app");
  const panel = document.getElementById("copilot-panel");
  if (!app || !panel || app.dataset.copilotEnabled !== "true") return;

  const repository = app.dataset.repository;
  const owner = repository.split("/")[0];
  const branch = app.dataset.branch;
  const basePath = app.dataset.base || "";
  const tokenInput = document.getElementById("github-token");
  const controls = document.getElementById("copilot-controls");
  const question = document.getElementById("copilot-question");
  const unlock = document.getElementById("copilot-unlock");
  const ask = document.getElementById("copilot-ask");
  const statusButton = document.getElementById("copilot-status");
  const indexButton = document.getElementById("copilot-index");
  const authState = document.getElementById("copilot-auth-state");
  const message = document.getElementById("copilot-message");
  const resultPanel = document.getElementById("copilot-result");
  const answer = document.getElementById("copilot-answer");
  const sourceList = document.getElementById("copilot-source-list");
  const mode = document.getElementById("copilot-mode");
  const resultTime = document.getElementById("copilot-time");
  const usage = document.getElementById("copilot-usage");
  const suggestionPanel = document.getElementById("copilot-suggestion");
  const suggestionBody = document.getElementById("copilot-suggestion-body");
  const applyButton = document.getElementById("copilot-apply");
  const undoButton = document.getElementById("copilot-undo");
  const contextState = document.getElementById("copilot-context-state");
  const charCount = document.getElementById("copilot-char-count");

  const pathParts = location.pathname.split("/").filter(Boolean);
  const marker = pathParts.lastIndexOf("m");
  const manualToken = marker >= 0 ? pathParts[marker + 1] || "" : "";
  const validManualToken = /^[A-Za-z0-9_-]{32,128}$/.test(manualToken);
  const validPat = value => /^github_pat_[A-Za-z0-9_]+$/.test(value);
  const history = [];
  let verifiedActor = "";
  let lastSuggestion = null;
  let undoSnapshot = null;
  let busy = false;

  const bytesToBase64 = bytes => {
    let binary = "";
    for (let start = 0; start < bytes.length; start += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
    }
    return btoa(binary);
  };
  const base64ToBytes = value => {
    const binary = atob(String(value || "").replace(/\s/g, ""));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  };
  const encodeUtf8 = value => bytesToBase64(new TextEncoder().encode(value));
  const decodeUtf8 = value => new TextDecoder().decode(base64ToBytes(value));
  const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

  function setMessage(text, kind = "empty") {
    message.textContent = text;
    message.className = `copilot-message ${kind}`;
  }

  function setBusy(value) {
    busy = value;
    controls.disabled = value || !verifiedActor;
    unlock.disabled = value;
    if (value) setMessage("Copilot 正在處理加密請求；不會修改或發布草稿。", "loading");
  }

  function randomJobId() {
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map(value => value.toString(16).padStart(2, "0")).join("");
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
    if (!envelope || envelope.version !== 1 || envelope.alg !== "A256GCM") {
      throw new Error("Copilot 回應使用不支援的加密格式");
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

  async function githubApi(path, options = {}) {
    const token = tokenInput.value.trim();
    const response = await fetch(`https://api.github.com${path}`, {
      ...options,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(options.headers || {}),
      },
      cache: "no-store",
    });
    return response;
  }

  function githubPath(path) {
    return path.split("/").map(encodeURIComponent).join("/");
  }

  async function readRepoFile(path) {
    const response = await githubApi(
      `/repos/${repository}/contents/${githubPath(path)}?ref=${encodeURIComponent(branch)}&check=${Date.now()}`,
    );
    if (response.status === 404) return {sha: null, content: null};
    if (!response.ok) throw new Error(`讀取 Copilot job 失敗（HTTP ${response.status}）`);
    const file = await response.json();
    return {sha: file.sha, content: decodeUtf8(file.content)};
  }

  async function writeRepoFile(path, content, messageText) {
    const existing = await readRepoFile(path);
    if (existing.sha) throw new Error("Copilot job ID 已存在，請重新送出");
    const response = await githubApi(
      `/repos/${repository}/contents/${githubPath(path)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          message: messageText,
          content: encodeUtf8(content),
          branch,
        }),
      },
    );
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.message || `提交 Copilot job 失敗（HTTP ${response.status}）`);
    }
  }

  async function verifyAdmin() {
    if (!validManualToken) throw new Error("私人補稿台網址權杖無效");
    if (!validPat(tokenInput.value.trim())) throw new Error("請先輸入有效的 fine-grained GitHub PAT");
    setMessage("正在向 GitHub 驗證 repository 管理員權限…", "loading");
    const [userResponse, repoResponse] = await Promise.all([
      githubApi("/user"),
      githubApi(`/repos/${repository}`),
    ]);
    if (!userResponse.ok || !repoResponse.ok) {
      throw new Error("GitHub 驗證失敗；請確認 PAT 只授權此 repository 且仍有效");
    }
    const user = await userResponse.json();
    const repo = await repoResponse.json();
    if (String(user.login || "").toLowerCase() !== owner.toLowerCase()
        || repo.permissions?.admin !== true) {
      throw new Error("此 PAT 不屬於 SKYTICAL repository owner／管理員");
    }
    verifiedActor = user.login;
    controls.disabled = false;
    authState.textContent = `已驗證 ${verifiedActor}`;
    authState.className = "copilot-badge ready";
    setMessage("管理員權限已驗證。Copilot 的 AI 內容只會顯示為建議預覽。", "success");
    updateContextState();
  }

  function selectedText() {
    const candidates = [
      document.getElementById("manual-content-primary"),
      document.getElementById("source-text"),
      document.getElementById("article-summary"),
    ];
    for (const field of candidates) {
      if (!field || document.activeElement !== field) continue;
      const start = Number(field.selectionStart || 0);
      const end = Number(field.selectionEnd || 0);
      if (end > start) return field.value.slice(start, end, 4000);
    }
    return "";
  }

  function textContent(id) {
    return (document.getElementById(id)?.textContent || "").trim();
  }

  function currentDraft() {
    let draftId = "";
    try {
      const output = JSON.parse(document.getElementById("json-output")?.value || "{}");
      draftId = String(output.article?.id || output.id || "").slice(0, 160);
    } catch (_error) {
      // A draft can be analyzed before publication JSON exists.
    }
    const manualTitle = document.getElementById("manual-title-primary")?.value.trim() || "";
    const manualBody = document.getElementById("manual-content-primary")?.value.trim() || "";
    const previewBody = [...document.querySelectorAll("#preview-zh-body p")]
      .map(row => row.textContent.trim()).filter(Boolean).join("\n\n");
    const context = {
      draftId,
      title: (manualTitle || textContent("preview-zh-title")).slice(0, 300),
      subtitle: "",
      excerpt: (document.getElementById("article-summary")?.value.trim()
        || textContent("preview-zh-summary")).slice(0, 1500),
      body: (manualBody || previewBody || document.getElementById("source-text")?.value.trim() || "")
        .slice(0, 12000),
      category: document.getElementById("article-type")?.value || "",
      tags: [],
      selectedText: selectedText(),
    };
    return context;
  }

  function updateContextState() {
    const draft = currentDraft();
    const fields = [draft.title, draft.excerpt, draft.body, draft.selectedText].filter(Boolean).length;
    contextState.textContent = fields
      ? `已準備草稿 context（${fields} 個欄位${draft.selectedText ? "，優先使用選取段落" : ""}）`
      : "目前沒有草稿 context；將只搜尋站內已發布文章";
  }

  async function pollResult(jobId) {
    const path = `data/copilot-jobs/outbox/${jobId}.json`;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const result = await readRepoFile(path);
      if (result.content) return decrypt(JSON.parse(result.content), jobId);
      if (attempt > 0 && attempt % 6 === 0) {
        setMessage(`Copilot worker 仍在處理（約 ${attempt * 10} 秒）…`, "loading");
      }
      await sleep(10000);
    }
    throw new Error("Copilot worker 等候逾時；請在 Actions 檢查 private-copilot-job");
  }

  async function submit(route, promptText = "") {
    if (busy) return null;
    if (!verifiedActor) await verifyAdmin();
    const jobId = randomJobId();
    const payload = {
      route,
      requestId: jobId,
      question: promptText,
      history: history.slice(-6),
      draft: currentDraft(),
    };
    const envelope = await encrypt(payload, jobId);
    setBusy(true);
    try {
      await writeRepoFile(
        `data/copilot-jobs/inbox/${jobId}.json`,
        `${JSON.stringify(envelope, null, 2)}\n`,
        `queue encrypted Copilot job ${jobId}`,
      );
      setMessage("加密 job 已送出；等待管理員限定的 Actions worker。", "loading");
      return await pollResult(jobId);
    } finally {
      setBusy(false);
    }
  }

  function safeSourceHref(value) {
    if (typeof value !== "string") return null;
    if (value.startsWith("/") && !value.startsWith("//")) return `${basePath}${value}`;
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  }

  function renderSources(sources) {
    sourceList.replaceChildren();
    const valid = Array.isArray(sources) ? sources : [];
    valid.forEach(source => {
      const href = safeSourceHref(source.url);
      if (!href) return;
      const card = document.createElement("a");
      card.className = "copilot-source-card";
      card.href = href;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      const title = document.createElement("strong");
      title.textContent = String(source.title || "未命名來源").slice(0, 300);
      const meta = document.createElement("span");
      meta.textContent = [source.publishedAt, source.category].filter(Boolean).join(" · ") || "SKYTICAL 站內文章";
      card.append(title, meta);
      sourceList.append(card);
    });
    if (!sourceList.children.length) {
      const empty = document.createElement("p");
      empty.className = "copilot-empty-source";
      empty.textContent = "沒有可可靠引用的來源。";
      sourceList.append(empty);
    }
  }

  function suggestionRows(value) {
    const rows = [];
    const add = (label, content) => {
      if (!content || (Array.isArray(content) && !content.length)) return;
      rows.push([label, Array.isArray(content) ? content.join("、") : String(content)]);
    };
    add("建議類型", value.kind);
    add("標題", value.title);
    add("副標", value.subtitle);
    add("摘要", value.excerpt);
    add("正文", Array.isArray(value.body) ? value.body.join("\n\n") : "");
    add("分類", value.category);
    add("Tags", value.tags);
    const entities = value.entities || {};
    add("航空公司", entities.airlines);
    add("機型", entities.aircraft);
    add("機場", entities.airports);
    add("航線", entities.routes);
    add("需補充／查證", value.verificationItems);
    return rows;
  }

  function renderSuggestion(value) {
    suggestionBody.replaceChildren();
    const rows = value && typeof value === "object" ? suggestionRows(value) : [];
    lastSuggestion = rows.length ? value : null;
    suggestionPanel.hidden = !lastSuggestion;
    if (!lastSuggestion) return;
    rows.forEach(([label, content]) => {
      const row = document.createElement("div");
      row.className = "copilot-suggestion-row";
      const heading = document.createElement("strong");
      heading.textContent = label;
      const detail = document.createElement("span");
      detail.textContent = content;
      row.append(heading, detail);
      suggestionBody.append(row);
    });
  }

  function renderAnswer(response) {
    resultPanel.hidden = false;
    answer.textContent = String(response.answer || "目前沒有可顯示的回答。");
    mode.textContent = response.sourceMode || "資料不足";
    resultTime.textContent = response.asOf ? `資料時間 ${response.asOf}` : "";
    const metrics = response.usage || {};
    usage.textContent = response.model
      ? `${response.model} · ${(metrics.inputTokens || 0).toLocaleString()} in / ${(metrics.outputTokens || 0).toLocaleString()} out · ${metrics.latencyMs || 0} ms`
      : "未呼叫主模型";
    renderSources(response.sources);
    renderSuggestion(response.suggestion);
    const kind = response.statusCode === 429 ? "rate-limit"
      : response.status === "success" ? "success"
        : response.status === "insufficient" || response.status === "blocked" ? "empty" : "error";
    setMessage(response.note || (response.status === "success"
      ? "Copilot 已完成；建議尚未套用。"
      : response.answer || "Copilot 無法完成請求。"), kind);
  }

  async function runAsk() {
    const promptText = question.value.trim();
    if (!promptText) {
      setMessage("請輸入航空問題或選擇一個草稿動作。", "error");
      question.focus();
      return;
    }
    try {
      const response = await submit("/api/admin/copilot/ask", promptText);
      if (!response) return;
      renderAnswer(response);
      history.push({role: "user", text: promptText});
      history.push({role: "assistant", text: String(response.answer || "").slice(0, 700)});
      while (history.length > 6) history.shift();
    } catch (error) {
      setMessage(error.message || "Copilot 請求失敗", "error");
    }
  }

  async function runAdminRoute(route) {
    try {
      const response = await submit(route, "");
      if (!response) return;
      if (response.status !== "success") {
        setMessage(response.answer || "Copilot 管理操作失敗。", "error");
        return;
      }
      if (route.endsWith("/status")) {
        const index = response.index || {};
        setMessage(
          `Copilot 已啟用；站內索引 ${index.total || 0} 篇，更新時間 ${index.updatedUtc || "尚未建立"}；外部搜尋未設定。`,
          "success",
        );
      } else {
        setMessage(`站內索引已增量更新：共 ${response.index?.total || 0} 篇。`, "success");
      }
    } catch (error) {
      setMessage(error.message || "Copilot 管理操作失敗", "error");
    }
  }

  function editorSnapshot() {
    return {
      title: document.getElementById("manual-title-primary")?.value || "",
      body: document.getElementById("manual-content-primary")?.value || "",
      category: document.getElementById("article-type")?.value || "auto",
    };
  }

  function restoreSnapshot(snapshot) {
    document.getElementById("mode-manual")?.click();
    const title = document.getElementById("manual-title-primary");
    const body = document.getElementById("manual-content-primary");
    const category = document.getElementById("article-type");
    if (title) title.value = snapshot.title;
    if (body) body.value = snapshot.body;
    if (category) category.value = snapshot.category;
    updateContextState();
  }

  function applySuggestion() {
    if (!lastSuggestion) return;
    if (!window.confirm("確認將這份 AI 建議套用到手動草稿？原稿會保留到「復原上次套用」。此動作不會發布文章。")) return;
    undoSnapshot = editorSnapshot();
    document.getElementById("mode-manual")?.click();
    const title = document.getElementById("manual-title-primary");
    const body = document.getElementById("manual-content-primary");
    const category = document.getElementById("article-type");
    if (title && lastSuggestion.title) title.value = lastSuggestion.title;
    if (body && Array.isArray(lastSuggestion.body) && lastSuggestion.body.length) {
      body.value = lastSuggestion.body.join("\n\n");
    } else if (body && lastSuggestion.excerpt) {
      body.value = lastSuggestion.excerpt;
    }
    const allowedCategories = new Set(
      category ? [...category.options].map(option => option.value) : [],
    );
    if (category && allowedCategories.has(lastSuggestion.category)) category.value = lastSuggestion.category;
    undoButton.disabled = false;
    setMessage("建議已由管理員手動套用；文章仍未發布。", "success");
    updateContextState();
  }

  unlock.addEventListener("click", async () => {
    try {
      await verifyAdmin();
    } catch (error) {
      verifiedActor = "";
      controls.disabled = true;
      authState.textContent = "管理員驗證失敗";
      authState.className = "copilot-badge locked";
      setMessage(error.message || "管理員驗證失敗", "error");
    }
  });
  ask.addEventListener("click", runAsk);
  statusButton.addEventListener("click", () => runAdminRoute("/api/admin/copilot/status"));
  indexButton.addEventListener("click", () => runAdminRoute("/api/admin/copilot/index"));
  applyButton.addEventListener("click", applySuggestion);
  undoButton.addEventListener("click", () => {
    if (!undoSnapshot) return;
    restoreSnapshot(undoSnapshot);
    undoSnapshot = null;
    undoButton.disabled = true;
    setMessage("已復原套用前的手動草稿。", "success");
  });
  question.addEventListener("input", () => {
    charCount.textContent = `${question.value.length} / 500`;
    updateContextState();
  });
  question.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runAsk();
  });
  panel.querySelectorAll("[data-copilot-prompt]").forEach(button => {
    button.addEventListener("click", () => {
      question.value = button.dataset.copilotPrompt;
      question.dispatchEvent(new Event("input"));
      question.focus();
    });
  });

  if (!validManualToken) {
    unlock.disabled = true;
    setMessage("私人補稿台網址權杖無效，Copilot 已鎖定。", "error");
  }
  updateContextState();
})();
