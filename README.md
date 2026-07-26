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
│  ├─ write.py      # Anthropic API 撰稿（zh+en）→ data/articles/、flashes、incidents
│  └─ build.py      # JSON → 靜態 HTML（site/）
├─ templates/       # Jinja2 模板（Modernist 設計系統）
├─ static/          # modernist.css / site.css / app.js
├─ data/            # 原始快照與文章 JSON（commit 進 repo 當作資料庫）
└─ site/            # 建置輸出（gitignored；由 Actions artifact 部署到 Pages）
```

沒有文章時（未設 `ANTHROPIC_API_KEY`），首頁自動切換為**純聚合模式**：
直接顯示各來源的原文標題，點擊前往原始報導，完全免費。

## 上線設定

1. Settings → Secrets and variables → Actions：新增 `ANTHROPIC_API_KEY`
   （撰稿用，必要）與 `AEROAPI_KEY`（FlightAware 統計，選用）。
2. Settings → Pages → Source 選 **GitHub Actions**。
3. Actions 頁手動觸發一次 `hourly-update` 驗證。

沒有 `ANTHROPIC_API_KEY` 時管線仍會執行：抓取與建站照常，只是不產生新文章。

## 本機開發

```bash
pip install -r requirements.txt
python pipeline/fetch.py
python pipeline/dedupe.py
ANTHROPIC_API_KEY=... python pipeline/write.py   # 可省略
AVWIRE_BASE_PATH= python pipeline/build.py       # 本機預覽用空 base path
python -m http.server -d site 8000
```

環境變數：

| 變數 | 預設 | 說明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | 撰稿用；未設定時跳過撰稿 |
| `AEROAPI_KEY` | — | FlightAware AeroAPI（選用統計） |
| `AVWIRE_BASE_PATH` | `/avwire` | 站台子路徑（Pages 專案站台） |
| `AVWIRE_MODEL` | `claude-opus-5` | 撰稿模型 |

## 免責聲明

本站內容為自動生成，可能存在錯誤或遺漏，不構成飛安、法遵或投資建議。
引用以事實改寫為主，原文著作權屬原單位；任何權威資訊請以官方原始來源為準。
