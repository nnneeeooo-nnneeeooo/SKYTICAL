# AVWIRE 航空快訊

> **AI／新對話快速接手：**先讀 [`AGENTS.md`](AGENTS.md)，不要重新盤點整個
> repository。最短指令：`@GitHub 依 AGENTS.md 快速模式處理：先確認【事項】，
> 再修改【內容】；測試通過後直接 commit、合併 main，並確認網站上線。`

全自動航空新聞聚合站。GitHub Actions 每小時整點抓取 FAA / NTSB / ICAO / IATA /
EASA / Eurocontrol / Reuters / The Aviation Herald / 交通部民航局等免費可信來源，
去重合併後由 LLM 自動撰寫雙語（繁中 + EN）新聞稿，產出靜態頁面並部署到
GitHub Pages。每篇文章文末列出所有原始來源連結。

A fully automated aviation news aggregator: fetch trusted free sources hourly,
de-duplicate, draft bilingual stories with an LLM, publish as a static site on
GitHub Pages — with every original source credited at the end of each article.

## 架構

```
avwire/
├─ .github/workflows/hourly.yml   # cron: 0 * * * * + workflow_dispatch
├─ pipeline/
│  ├─ common.py     # 共用設定與來源註冊表
│  ├─ CONTRACTS.md  # 各階段 JSON 資料契約
│  ├─ fetch.py      # 抓取 RSS / HTML / API → data/raw/
│  ├─ dedupe.py     # URL 正規化 + 標題相似度去重、跨來源合併 → data/pending.json
│  ├─ write.py      # LLM 撰稿（zh+en，Anthropic/Gemini/NVIDIA 依序備援）→ data/articles/ 等
│  └─ build.py      # JSON → 靜態 HTML（site/）
├─ templates/       # Jinja2 模板（Modernist 設計系統）
├─ static/          # modernist.css / site.css / app.js
├─ data/            # 原始快照與文章 JSON（commit 進 repo 當作資料庫）
└─ site/            # 建置輸出（gitignored；由 Actions artifact 部署到 Pages）
```

沒有文章時（未設任何撰稿 API key），首頁自動切換為**純聚合模式**：
直接顯示各來源的原文標題，點擊前往原始報導，完全免費。

## 上線設定

1. Settings → Secrets and variables → Actions：新增至少一組撰稿 key（都設也可以，
   會依 `AVWIRE_PROVIDER_ORDER` 順序自動備援）：
   - `ANTHROPIC_API_KEY`（Anthropic，品質最佳、付費）
   - `GEMINI_API_KEY`（Google AI Studio 免費層）
   - `NVIDIA_API_KEY`（NVIDIA NIM 免費額度，DeepSeek 等開源模型）
   - `AEROAPI_KEY`（FlightAware 統計，選用）
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions 頁手動觸發一次 `hourly-update` 驗證。

一組 key 都沒有時管線仍會執行：抓取與建站照常，只是不產生新文章。

撰稿階段內建**事實核驗閘門**（站長編輯規範 v2，見 `docs/editorial-prompt-notes.md`）：

- 模型必須為每項主張附上原文**逐字引文**（`facts[].sourceQuote`）與
  `sourceUrl`；程式端逐字比對，比對不過的主張直接丟棄。每筆 fact 另以
  `evidenceScope` 區分本次來源或受控歷史脈絡。
- 航空／運輸相關性由程式在抓取後與發布前雙重檢查。軍事新聞必須直接涉及
  軍機、空域、軍艦／港口或具體運輸事件；一般軍事政治、演習立場、預算攻防
  與官員視導不屬本站範圍。
- 四種編輯狀態：`publish`、`publish_brief`（短但可信的低風險新事件）、
  `manual_review`、`reject`（本次事件證據不足不發布，附具體理由）。
- **航空安全事件一律 `manual_review`，不自動發布**：草稿完整存入
  `data/review.json` 佇列。要發布時，在 GitHub 網頁編輯該檔，把該筆的
  `"approve": false` 改成 `true` 後 commit，下一個小時的管線就會原稿發布
  並清出佇列；14 天未處理自動過期。
- 完整稿每種語言至少 4 段；繁中至少 500 個實質字元（不計空白與標點），
  英文至少 250 詞。程式會實際計數，未達標自動重試或改用備援模型；證據不足
  時不得重複、灌水或虛構背景湊長度。低風險事件若至少有一項本次來源事實，
  但不足以支撐完整稿，降級為雙語短訊（繁中 180–320 字、英文 90–150 詞、
  各至少 2 段）。
- 撰稿前會以完全本地、deterministic 規則檢索 `data/articles/*.json`：
  只有已發布、帶日期、來源 URL、逐字引文且可解釋直接關聯的舊事件，才能進入
  `<VERIFIED_ARCHIVE_CONTEXT>`；最多 3 個事件／12 項 facts，不使用 embedding、
  搜尋或額外模型呼叫。歷史資料只能補充前情，不得證明本次事件發生。
- 文章 JSON 保存 riskFlags、事件狀態、實體與通過驗證的引文供追溯。
- 已發布資料可用 `"archived": true` 封存：原始 JSON、來源與核驗紀錄完整
  保留，但建站時不產生文章頁，也不出現在首頁、分類、搜尋、摘要或快訊。
`provider-bench` workflow（手動觸發）會用同一批待寫新聞讓每個已設 key 的
供應商各寫一輪並上傳成 artifact，方便比較品質後決定主力順序。

## 本機開發

```bash
pip install -r requirements.txt
python pipeline/fetch.py
python pipeline/dedupe.py
GEMINI_API_KEY=... python pipeline/write.py      # 可省略；或 ANTHROPIC/NVIDIA key
AVWIRE_BASE_PATH= python pipeline/build.py       # 本機預覽用空 base path
python -m http.server -d site 8000
```

環境變數：

| 變數 | 預設 | 說明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic 撰稿（選用） |
| `GEMINI_API_KEY` | — | Google Gemini 撰稿（選用，免費層） |
| `NVIDIA_API_KEY` | — | NVIDIA NIM 撰稿（選用，免費額度） |
| `AVWIRE_PROVIDER_ORDER` | `anthropic,gemini,nvidia` | 撰稿優先鏈，主力在前；token 可用 `平台:模型` 指定模型，同平台可重複出現（例：`nvidia:nvidia/nemotron-3-ultra-550b-a55b,nvidia:nvidia/nemotron-3-super-120b-a12b,gemini`）。主力模型驗證失敗自動重試一次；帳號／額度失效會跳過同平台所有備援模型 |
| `AVWIRE_MODEL` | `claude-opus-5` | Anthropic 模型 |
| `AVWIRE_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini 模型 |
| `AVWIRE_NVIDIA_MODEL` | `deepseek-ai/deepseek-v3.1` | NVIDIA NIM 模型 |
| `NEWS_MAX_AGE_HOURS` | `120` | 新聞新鮮度窗口（小時），驗證範圍 24–336，非法值回退預設並警告 |
| `AEROAPI_KEY` | — | FlightAware AeroAPI（選用統計） |
| `AVWIRE_BASE_PATH` | `/avwire` | 站台子路徑（Pages 專案站台） |

## 稀有民航機偵測（預設關閉）

`rare-aircraft-monitor` workflow 每 5 分鐘用 **一次** Airplanes.live 廣域查詢
（臺灣中心 250 海浬）監測 `config/tw_civil_airports.json` 裡的民用機場，
純程式端判定抵達（多筆觀測狀態機，絕不用單一快照）、計算可解釋的稀有度
（0–100，常態業者/機型與歷史統計扣加分，`config/rare_aircraft_watchlist.json`
可人工加註），候選事件才查 ADSB.lol 交叉確認。軍機、政府專機、LADD/PIA、
緊急代碼與非 ICAO 位址一律排除且不留軌跡；公開資料絕不含即時座標。
確認的事件排入 `data/flightwatch/queue.json`，由每小時撰稿階段以專用
prompt 撰寫並**一律進入 `data/review.json` 人工覆核**，不自動發布。

啟用方式：Repo Variables 設 `FLIGHT_TRACKING_ENABLED=true`。

公開網站另提供 `/radar/`（英文版 `/en/radar/`）台灣民航雷達頁。頁面由
訪客瀏覽器每 5 分鐘直接查詢一次 Airplanes.live 公開 API，以 Leaflet 與
OpenStreetMap 顯示航班呼號、航空公司、機型、高度、地速及航向，並以
ADSBdb 公開呼號端點補充 ICAO／IATA 班號切換與起迄機場，預設以旅客常見的
IATA 班號顯示，仍可切回 ICAO 呼號；兩者皆不需 API key。航線查詢會在訪客
瀏覽器內去重、限制併發並快取，不儲存即時座標；
建立任何標記前會排除軍事、PIA、LADD、緊急狀態、非 ICAO 位址與位置過期
資料。此頁僅供航空資訊參考，不是航管雷達，航線資料查不到時不會猜測。
製造商官方新聞來源另由 `config/manufacturer_sources.json` 管理；Airbus 與
Boeing 顯示於公開來源狀態，其餘製造商來源只供新聞管線使用。官方社群帳號
只保存為未來整合用的中繼資料，不繞過平台 robots 或自動化存取限制。

資料來源授權：Airplanes.live 社群資料（非商業用途；本站無廣告無營利）、
ADSB.lol 開放資料（ODbL，本站僅擷取事件摘要並保留出處標註，不鏡像資料庫）。

## 免責聲明

本站內容為自動生成，可能存在錯誤或遺漏，不構成飛安、法遵或投資建議。
引用以事實改寫為主，原文著作權屬原單位；任何權威資訊請以官方原始來源為準。
