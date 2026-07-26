# AVWIRE 航空快訊

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

- 模型必須為每項主張附上原文**逐字引文**（`facts[].sourceQuote`），程式端
  逐字比對，比對不過的主張直接丟棄；標題與摘要只能使用 facts 裡的資訊。
- 三種編輯狀態：`publish`（無風險才直接上站）、`manual_review`、`reject`
  （證據不足不發布，附具體理由）。
- **航空安全事件一律 `manual_review`，不自動發布**：草稿完整存入
  `data/review.json` 佇列。要發布時，在 GitHub 網頁編輯該檔，把該筆的
  `"approve": false` 改成 `true` 後 commit，下一個小時的管線就會原稿發布
  並清出佇列；14 天未處理自動過期。
- 文章 JSON 保存 riskFlags、事件狀態、實體與通過驗證的引文供追溯。
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
| `AVWIRE_PROVIDER_ORDER` | `anthropic,gemini,nvidia` | 撰稿供應商優先順序（主力在前） |
| `AVWIRE_MODEL` | `claude-opus-5` | Anthropic 模型 |
| `AVWIRE_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini 模型 |
| `AVWIRE_NVIDIA_MODEL` | `deepseek-ai/deepseek-v3.1` | NVIDIA NIM 模型 |
| `AEROAPI_KEY` | — | FlightAware AeroAPI（選用統計） |
| `AVWIRE_BASE_PATH` | `/avwire` | 站台子路徑（Pages 專案站台） |

## 免責聲明

本站內容為自動生成，可能存在錯誤或遺漏，不構成飛安、法遵或投資建議。
引用以事實改寫為主，原文著作權屬原單位；任何權威資訊請以官方原始來源為準。
