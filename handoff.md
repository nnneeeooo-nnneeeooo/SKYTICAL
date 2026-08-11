# SKYTICAL Copilot Beta 交接

日期：2026-08-11
分支：`agent/copilot-knowledge-web`
基準：`main`

## 1. 專案分析結果

- 技術棧：Python 3.12、Jinja2、Vanilla JavaScript/CSS、JSON 檔案資料庫、GitHub Actions、GitHub Pages。
- 正式網站是純靜態 GitHub Pages，沒有常駐 application server、session middleware、資料庫連線或可部署 `/api/*` 的 server runtime。
- 私人補稿台：建置時由 `pipeline/build.py` 產生於 `/m/<AVWIRE_MANUAL_TOKEN>/`，主要檔案為 `templates/manual.html`、`static/manual.js`、`static/manual.css`、`pipeline/manual_draft.py`、`.github/workflows/manual-draft.yml`。
- API 用量頁：建置時產生於 `/u/<AVWIRE_USAGE_TOKEN>/`，主要檔案為 `templates/usage.html`、`pipeline/usage.py` 與 `pipeline/build.py`。
- 現有管理員身分：補稿台由瀏覽器中的 fine-grained GitHub PAT 存取 GitHub Contents API；沒有傳統登入 session。Copilot UI 另向 GitHub 驗證 PAT 的 login、repository owner 與 `permissions.admin`，Actions worker 再以 `GITHUB_ACTOR == GITHUB_REPOSITORY_OWNER` 做獨立 server-side 檢查。
- 未登入時，GitHub API 會回 401；非 repository owner／管理員在 UI 被鎖定，worker 也回 403；feature flag 關閉時 worker 回 404。
- 文章資料模型：已發布文章位於 `data/articles/*.json`，包含中英文標題、摘要、正文、來源、發布時間、分類、facts 與 entities。Copilot 只索引已發布且未封存文章；當前草稿只存在單次加密 job context，不會寫入 RAG index。
- 可重用基礎設施：AES-GCM 加密 job envelope、GitHub Contents API、Actions secrets、既有 provider fallback、`data/usage.json`、模型牌價表與靜態建站流程。

## 2. 已完成功能

- 在既有私人補稿台加入 `SKYTICAL Copilot Beta` 面板，沒有另建後台。
- 支援航空問答、站內文章搜尋、草稿摘要、三行摘要、分類與 tags 建議、航空實體擷取、補充／查證建議。
- 優先讀取目前 textarea 的選取段落；否則傳遞截斷後的 `draftId`、title、subtitle、excerpt、body、category、tags。
- 回答顯示資料來源模式、資料時間、模型／token／延遲、來源卡片、loading、error、empty、rate-limit 與 feature-disabled 狀態。
- AI 內容只顯示為 suggestion preview；必須按「套用建議到手動草稿」並通過確認對話才會修改本機表單。
- 套用前在記憶體保留原稿 snapshot，可按「復原上次套用」還原；不會自動 publish、schedule、delete 或寫入文章資料。
- 前端來源卡片全部用 DOM `textContent` 建立，不使用 `innerHTML`；URL 只接受站內絕對路徑或 HTTPS。
- Copilot 面板只有 build-time feature flag 開啟時才會寫入既有私人補稿頁；控制項在 GitHub owner/admin 驗證前保持 disabled。
- worker 端再次檢查 feature flag 與 repository owner，不相信 client 傳入的 role、admin flag 或 userId。
- 加入增量站內索引、guardrail、限流、預算保護、provider fallback、輸出驗證與 usage telemetry。
- 所有 prompt、history 與草稿內容只存在 AES-GCM 密文 job；repository 不會保存明文對話或草稿。

## 3. 修改與新增檔案

新增：

- `.env.example`
- `.github/workflows/copilot.yml`
- `pipeline/copilot.py`
- `static/copilot.css`
- `static/copilot.js`
- `tests/test_copilot.py`
- `data/copilot/.gitkeep`
- `data/copilot-jobs/inbox/.gitkeep`
- `data/copilot-jobs/outbox/.gitkeep`
- `handoff.md`

修改：

- `pipeline/build.py`
- `pipeline/usage.py`
- `templates/manual.html`
- `templates/usage.html`
- `.github/workflows/hourly.yml`
- `.github/workflows/briefing.yml`
- `.github/workflows/manual-article-deploy.yml`
- `.gitignore`

未修改既有登入邏輯、補稿發布流程、CMS／草稿資料契約、公開 Header、Footer、首頁、文章頁、sitemap 或 robots。

## 4. 私有 API 路徑與傳輸方式

邏輯路徑：

- `/api/admin/copilot/ask`
- `/api/admin/copilot/index`
- `/api/admin/copilot/status`

此 repository 沒有 HTTP server，因此上述路徑是加密 job payload 的 route contract，不是公開網路上的 HTTP endpoint。傳輸流程：

1. 私人補稿台驗證 GitHub owner/admin PAT。
2. 瀏覽器以 `AVWIRE_MANUAL_TOKEN` 衍生的 AES-256-GCM key 加密請求。
3. GitHub Contents API 將密文寫到 `data/copilot-jobs/inbox/<jobId>.json`。
4. `private-copilot-job` Actions worker 檢查 `GITHUB_ACTOR`、repository owner 與 server-side feature flag。
5. worker 處理後把密文結果寫到 `data/copilot-jobs/outbox/<jobId>.json`。
6. 補稿台輪詢、解密並顯示 suggestion preview。

這不是以秘密網址冒充 API 權限：GitHub PAT 與 worker owner 檢查才是實際權限邊界；秘密網址權杖只負責既有頁面位置與 job 加密。若產品必須具備真正的 session-backed HTTP API、一般 admin role 或 IP-based middleware，需新增 owner 核准的私有 application server，GitHub Pages 無法提供。

## 5. RAG 與文章索引

- 策略：`incremental-lexical-v1`，完全本機、deterministic，零 embedding／向量服務費用。
- 索引來源：只讀取 `data/articles/*.json` 中已發布、未封存且具有安全 HTTPS 來源的文章。
- 索引內容：繁中／英文標題、摘要、正文、fact claim／quote 與 entities；單篇文字最多 8,000 字元。
- 每筆 metadata：title、url、slug、publishedAt、category、airline、aircraft、airport、route、language。
- 每筆有 SHA-256 `contentHash`；未變更文章直接重用，新增、修改、刪除文章才更新對應紀錄。
- 每次 prompt 最多 5 篇站內結果、總 RAG context 12,000 字元；context 明確標記為 untrusted evidence data。
- 草稿永不寫入 index，只在當次 encrypted request 內使用。
- 沒有執行外部 embedding 或高成本全站重新索引；正式環境目前以本機規則維護 189 篇已發布文章的輕量索引。

## 6. 外部 fallback

- Copilot 先使用 SKYTICAL 已發布內容；站內資料不足時，允許模型以自身航空知識回答穩定的背景問題，並清楚標示為模型知識，不再一律拒答。
- 比較、規格、性能、先進程度、最新／即時等容易過時或需要外部證據的問題，會優先改用 Gemini 的內建 Google Search grounding。
- `GEMINI_API_KEY` 存在時，status 回覆 `externalSearchConfigured=true` 與 `webGroundingProvider=gemini-google-search`；沒有另增 `EXTERNAL_SEARCH_API_KEY`。
- Grounded 回答最多顯示 5 筆 Google 回傳的 HTTPS citation，並在隔離 iframe 中原樣顯示 Google Search Suggestions。Grounded 結果不再交給第二個模型重寫，避免 citation 與回答失去對應。
- 最新／即時問題若無法取得完整 grounding，仍安全拒答；一般穩定背景題則可退回模型航空知識，並標示「非即時」。
- 既有 `ExternalSearch` interface 保留供測試或未來自訂供應商使用，但正式 Gemini 路徑不會把外部網頁永久寫入 RAG index。

## 7. Guardrail pipeline

執行順序：

1. 嚴格 input validation 與 Unicode／控制字元清理。
2. Base64、percent encoding、ROT13 等可疑 payload 偵測。
3. 中英文 jailbreak／prompt injection 規則式偵測。
4. deterministic 航空範圍分類；off-topic、unclear、injection 直接固定回覆。
5. rate limit、duplicate cooldown、daily limit 與 budget 檢查。
6. 通過後先執行站內 RAG，SKYTICAL 來源始終優先。
7. 比較／規格／性能／時效性問題優先使用 Gemini Google Search grounding；穩定背景題可使用模型航空知識。
8. 最新／即時問題只有在 grounding 完整時才回答；其他問題會明確區分站內來源、Google 搜尋與模型知識。
9. model output schema、secret／internal path、來源與 URL 檢查。
10. 前端以安全 DOM API 顯示結果；Google Search Suggestions 只在 sandboxed iframe 顯示。

限制：最多 500 字元問題、最近 6 則對話、history 3,000 字元、草稿正文 12,000 字元、選取文字 4,000 字元、RAG context 12,000 字元。

## 8. Rate limit 與成本控制

預設：

- 每分鐘 8 次。
- 每日 50 次主 LLM attempt。
- Google Search grounded request 每日上限 10 次；一次 grounded request 可能由 Google 拆成多個實際搜尋 query，實際帳單以 Google 計量為準。
- 每日估計預算上限 USD 5。
- 相同問題 30 秒 cooldown。
- Actions `concurrency` 限制同時只有一個 Copilot worker。
- provider fallback 最多 3 次，且不會超過當日剩餘 LLM attempt 數。
- 每個成功或失敗的主模型 attempt 都獨立記錄 token、估計成本與延遲。
- 429 在 RAG、embedding、外部搜尋或主 LLM 前回覆。
- 預算達上限後只回傳安全站內搜尋結果或資料不足，不呼叫主 LLM。

GitHub Pages 無法取得終端使用者 IP；現行安全邊界改以 HMAC 後的 authenticated repository owner identity 計數。status 回覆會明確標示 `rateLimitScope=authenticated-admin-identity`。這是 Beta 已知限制，不能宣稱是每 IP 限流。

## 9. Usage logging 整合

- 直接擴充既有 `data/usage.json` 與 `pipeline/usage.py`，沒有重建 dashboard。
- 新增 30 天、最多 2,000 筆的 `copilotEvents` whitelist。
- 記錄匿名 request ID、route、feature、event、model、input/output/total tokens、估計 USD、latency、status、guardrail、RAG、external search、source count、HMAC user hash、時間。
- 記錄 Copilot request、off-topic、unclear、injection、rate-limited、RAG search、每次 main LLM attempt、successful answer、failed answer、status check 與 index update。
- 沒有 embedding／vector call，因此不虛構 embedding 或 vector usage event；本機檢索標記為 `lexical-v1`。
- 不保存完整問題、history、草稿、PAT、API key 或 secret。
- telemetry 寫入失敗與 provider usage ledger 寫入失敗都不會讓主要回答流程崩潰。
- 既有 usage 頁新增 Copilot request、LLM、blocked、rate limit、token、估計成本、外部搜尋、錯誤與近期事件表。

## 10. 環境變數

新增／使用：

```dotenv
SKYTICAL_COPILOT_ENABLED=false
AI_RATE_LIMIT_PER_MINUTE=8
AI_DAILY_REQUEST_LIMIT=50
AI_EXTERNAL_SEARCH_DAILY_LIMIT=10
AI_DAILY_BUDGET_LIMIT_USD=5
```

重用既有：

```dotenv
AVWIRE_MANUAL_TOKEN=
OPENCODE_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
NVIDIA_API_KEY=
OPENROUTER_API_KEY=
AVWIRE_PROVIDER_ORDER=
```

沒有新增真實 secret；`.env.example` 全部是空值／安全預設。既有 `GEMINI_API_KEY` 同時供一般 Gemini provider 與 Copilot Google Search grounding 使用。

## 11. Feature flag 狀態

- 預設：`SKYTICAL_COPILOT_ENABLED=false`。
- build-time flag 只控制私人補稿台是否渲染 Copilot 面板，不是權限控制。
- Actions worker 每次 job 都獨立檢查同一 server-side flag。
- 關閉時 worker 回安全 404／feature-disabled response，不呼叫 RAG 或模型。

## 12. 實際測試與結果

通過：

- `.venv/Scripts/python.exe -m py_compile pipeline/copilot.py pipeline/usage.py pipeline/build.py`
- `node.exe --check static/copilot.js`
- `.venv/Scripts/python.exe -m pytest -q tests/test_copilot.py`：`26 passed`
- `.venv/Scripts/python.exe tests/test_usage.py`：`46 checks passed, 0 failed`
- `.venv/Scripts/python.exe tests/test_manual_draft.py`：`62 checks passed, 0 failed`
- 逐一獨立執行所有既有 `tests/test_*.py`：27 個腳本中 25 個通過。
- `SKYTICAL_COPILOT_ENABLED=false` production build：189 articles、500 pages、0 failed。
- 私有預覽 build（manual token、usage token、feature flag true）：189 articles、502 pages、0 failed。
- 私有預覽檢查：補稿台含 Copilot 面板、usage 頁含 Copilot 區塊；公開首頁、英文首頁、雙語文章頁、sitemap、robots 無 Copilot 字樣或資產引用。
- Browser 視覺 QA：1440×900 與 390×844 皆無水平 overflow；手機版鎖定列與操作列為單欄；未提供 PAT 時 controls 保持 disabled；console 0 errors。
- `git diff --check` 通過。

既有基準失敗（在未修改的乾淨 `main` worktree 同樣重現）：

- `tests/test_companion.py`：`per-run search budget enforced`，12/13 passed。
- `tests/test_scope.py`：`StopIteration`，測試找不到預期 archived flash。

因此這兩項不是 Copilot regression。repository 的多數測試是 import-time script 並會 `sys.exit`，不能可靠地在同一個 `pytest -q` process 收集；本次依原有格式以獨立 process 執行。

## 13. 已知風險與 Beta 限制

- 沒有傳統 HTTP application server；三個 `/api/admin/copilot/*` 是 encrypted job route contract，不是可由外部呼叫的 HTTP endpoint。
- 現有私人補稿台本身仍是 secret-path 靜態頁；Copilot 額外要求 GitHub owner/admin PAT 並在 worker 端再次檢查 owner，但無法把靜態 HTML 本身變成 session-protected route。
- 限流範圍是 authenticated admin identity，不是 IP。
- 模型自身知識可能過時或不完整；介面會標示來源模式，最新／即時問題不得以未 grounding 的模型知識冒充查證結果。
- Google Search grounding 可能產生額外費用；每日 10 次限制計算的是 Copilot grounded request，不保證等於供應商帳單中的搜尋 query 數。
- Grounded 回答必須連同 Google Search Suggestions 顯示；目前以不允許 script、form 或 same-origin 存取的 sandboxed iframe 隔離第三方 HTML。
- 沒有 embedding 或向量資料庫；目前採適合 189 篇資料量的詞彙索引。資料規模大幅增加後需重新評估。
- 既有 encrypted job 流程已由 owner 在正式環境實際使用；本次新增的 Google grounded 比較題仍需在部署後以單一真實問題確認供應商金鑰、引用與 Search Suggestions。
- `data/copilot/index.json`、rate state 與 encrypted outbox 已由 Actions job 建立；repository 只保存加密 job payload，不保存明文問題與草稿。
- 每次 request 透過 GitHub commit 傳輸，延遲高於一般 HTTP API，適合私人 Beta，不適合公開即時聊天。

## 14. 操作與驗收

1. 在私人補稿台送出一般航空背景題，來源模式應標示 SKYTICAL 或模型航空知識，不應只因站內沒有直接比較文章而拒答。
2. 送出 A350 與 787 的先進程度、規格或性能比較題，來源模式應包含 Google 搜尋，回答應給出有條件的結論並顯示 citation 與 Search Suggestions。
3. 送出「最新／目前／今日」問題；Google grounding 失敗時應明確拒答，不得退回未查證的即時斷言。
4. status 應顯示 `modelKnowledgeEnabled=true`；Actions 有 `GEMINI_API_KEY` 時也應顯示 `externalSearchConfigured=true`。

## 15. Production 發布方式

- 功能程式碼合併至 `main` 後，仍須將 repository variable `SKYTICAL_COPILOT_ENABLED` 設為 `true`，Copilot 面板與 worker 才會啟用。
- 變數啟用後，執行 `manual-article-deploy.yml` 或等待下一次既有建站 workflow，將含 Copilot 面板的私人補稿台發布到 GitHub Pages。
- 發布完成必須確認對應 `main` commit 的 build／deploy jobs 全部成功，並以私人補稿網址實測 owner/admin 驗證、status job、索引及單一站內問答。
- 公開首頁、文章頁、導覽、sitemap 與 robots 不應出現 Copilot 入口或資產；變數設回 `false` 並重新建站即可移除私人頁面的 Copilot 面板。

## 16. 公開頁面確認

**沒有將 Copilot 加入公開頁面。**
公開首頁、Header、Footer、文章頁、搜尋頁、sitemap、robots 與公開導覽均沒有 Copilot 入口、文案或 script／stylesheet 引用。
