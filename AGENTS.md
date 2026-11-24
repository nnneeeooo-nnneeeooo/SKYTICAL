# SKYTICAL 專案作業規則

- 使用繁體中文（臺灣用語）。GitHub repository 為 `nnneeeooo-nnneeeooo/SKYTICAL`，正式分支為 `main`，網站由 GitHub Pages 發布到 <https://skytical.tech/>。
- 優先在目前的 SKYTICAL checkout 或 Codex worktree 作業。修改前用 `git rev-parse --show-toplevel` 與 `git remote get-url origin` 核對工作樹和來源。若目前目錄不屬於本專案，使用桌面版綁定的 `C:\Users\iwnlewn\Documents\ChatGPT\SKYTICAL`。
- 先確認分支、現況與既有差異。用檔名或關鍵字定位，讀取目標檔案及直接相關的程式、設定與測試，保留無關變更。
- 版型與前端在 `templates/`、`static/`；新聞與建站程式在 `pipeline/`；提示詞、設定和文章分別在 `prompts/`、`config/`、`data/`；自動化與測試在 `.github/workflows/`、`tests/`。
- `main` 同時由每小時管線（`hourly-update`，以 `skytical-bot` 提交）、Meta Muse 與 Devin 排程寫入，管線常延遲落地。提交前與合併前都重新抓取最新 `main`，以最新版本為底修改；不得覆蓋其他流程已上線的文章與圖片，不強制推送。同一事件重複刊出時，在自己那篇設 `archived: true` 與 `archiveReason`，檔案保留。

## 依任務載入指引

- **發布、補發或更新新聞**：依 [排程新聞流程](docs/scheduled-news.md#每次執行的工作指令) 查證、去重、撰稿與驗收，並依 [發稿分流](docs/editorial-routing.md#分流) 判斷是否獨立報導。`writer` 與 `writerModels` 寫實際撰稿的代理與模型，例如 `scheduled:Devin • Fable 5.2`。
- **新聞配圖或短訊換圖**：使用 `$skytical-news-images`，工作區檔案為 [SKILL.md](.agents/skills/skytical-news-images/SKILL.md)。優先使用可查證授權的事件原照，沿用既有版型在每篇正文上方直接顯示該篇對應的照片。
- **更新網站公告**：只刊登已查證、對讀者有具體影響且值得主動告知的更新。例行補稿、補圖與內部維護走原本的編輯流程。沒有符合門檻的新項目時，保留現有公告。詳見[公告內容維護](docs/update-notice.md#內容維護)。
- **新增功能、替換技術方案或重做子系統**：先在 GitHub 比對 3–5 個仍維護且直接相關的專案。依 [開源偵察的評估原則](docs/open-source-scouting.md#評估原則) 比較維護狀況、採用規模、語言與依賴、授權、可重用實作及導入成本。記錄值得追蹤的候選；確定導入時另開 issue 或 PR。小型文字、明確修正與設定變更直接處理。
- **變更管線各階段的 JSON 資料格式**：先讀 [資料契約](pipeline/CONTRACTS.md)。

## 發稿與配圖的時間規則

適用於 Codex、GPT、Devin、Muse、Claude、人工私稿工作台與其他發稿代理。

- 新獨立報導的 `publishedUtc` 是實際首次寫入正式文章資料的 UTC 時間。補刊時把查證後的原始來源時間存為 `sourcePublishedUtc`，以同一時間填入 `sortUtc`，讓首頁、搜尋與快訊依新聞時間排序。來源只有日期時，使用來源所列日期的 `00:00:00Z` 並設 `sourceDateOnly: true` 與 `sortDateOnly: true`，讀者只會看到日期。來源有明確時區與時分時轉為 UTC 並設 `sourceDateOnly: false`。來源時間無法查證時省略來源時間及精度，`sortUtc` 使用實際刊登時間。產業動態整期彙整用當期刊登時間排序。
- 更新正文或新增已查證事實時，保留既有 `id`、`publishedUtc` 和 `sortUtc`，更新 `updatedUtc`。資料與圖片可同時首次入庫。既有文章只補圖、換圖或修正圖說時，保留 `publishedUtc`、`sortUtc`、`sortDateOnly`、`sourcePublishedUtc`、`sourceDateOnly`、`updatedUtc` 和查證時間原值，包含原本未填的欄位。補正歷史時間時，另做時間修訂並在 PR 附來源證據。
- 提交前執行 `python pipeline/scheduled_news.py --chronology-base origin/main`。GitHub Actions 會在資料 PR 及排程發稿部署時檢查時間欄位。上線後抽查實際文章、首頁及搜尋，確認刊登資訊與新聞排序各自對應。

## 測試與上線

1. 優先跑直接相關測試，使用專案 `.venv` 的 Python（Windows 為 `.venv/Scripts/python.exe`，Linux／macOS 為 `.venv/bin/python`）。單一功能用 `python -m pytest -q tests/test_<功能>.py`，前端用 `node tests/test_<功能>.js`；影響共用管線、資料契約或跨功能時跑 `python -m pytest -q`。
2. 完整 PR 自動回歸測試在變更 [`hourly.yml`](.github/workflows/hourly.yml) `pull_request.paths` 所列路徑時執行。文章時間另有 `manual-article-deploy` 的 PR 檢查。其餘變更（含多數 `templates/`、`static/`）合併前在本機驗證；文章與圖片照 [`manual-article-deploy.yml`](.github/workflows/manual-article-deploy.yml) 的步驟執行到 `python pipeline/build.py`，並在輸出確認該篇有產生頁面。
3. 檢查 staged diff，排除 `.env`、金鑰、token、憑證、`site/` 與其他產物。驗證通過後提交至功能分支，建立 PR 並合併到 `main`。
4. 涉及網站發布時，等本次 `main` commit 的 GitHub Pages 工作完成並核對正式頁面。只改 `data/` 的 push 不觸發 `hourly-update`；`manual-article-deploy` 只在變更 `data/articles/scheduled-*.json` 或 `.github/deploy-trigger` 時執行，其餘資料變更要等下一次部署才上線。回覆列出修改、驗證、commit／PR 與適用的部署結果。
