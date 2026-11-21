# SKYTICAL 專案作業規則

- 使用繁體中文（臺灣用語）。GitHub repository 為 `nnneeeooo-nnneeeooo/SKYTICAL`，正式分支為 `main`，網站由 GitHub Pages 發布。
- 優先在目前的 SKYTICAL checkout 或 Codex worktree 作業。修改前用 `git rev-parse --show-toplevel` 與 `git remote get-url origin` 核對工作樹和來源。若目前目錄不屬於本專案，使用桌面版綁定的 `C:\Users\iwnlewn\Documents\ChatGPT\SKYTICAL`。
- 先確認分支、現況與既有差異。用檔名或關鍵字定位，讀取目標檔案及直接相關的程式、設定與測試，保留無關變更。
- 版型與前端在 `templates/`、`static/`；新聞與建站程式在 `pipeline/`；提示詞、設定和文章分別在 `prompts/`、`config/`、`data/`；自動化與測試在 `.github/workflows/`、`tests/`。

## 依任務載入指引

- **新聞配圖或短訊換圖**：使用 `$skytical-news-images`，工作區檔案為 [SKILL.md](.agents/skills/skytical-news-images/SKILL.md)。優先使用可查證授權的事件原照，沿用既有版型在每篇正文上方直接顯示該篇對應的照片。
- **更新網站公告**：只刊登已查證、對讀者有具體影響且值得主動告知的更新。例行補稿、補圖與內部維護走原本的編輯流程。沒有符合門檻的新項目時，保留現有公告。詳見[公告內容維護](docs/update-notice.md#內容維護)。
- **新增功能、替換技術方案或重做子系統**：先在 GitHub 比對 3–5 個仍維護且直接相關的專案。依 [開源偵察的評估原則](docs/open-source-scouting.md#評估原則) 比較維護狀況、採用規模、語言與依賴、授權、可重用實作及導入成本。記錄值得追蹤的候選；確定導入時另開 issue 或 PR。小型文字、明確修正與設定變更直接處理。

## 測試與上線

1. 優先跑直接相關測試。單一功能用 `.venv/Scripts/python.exe -m pytest -q tests/test_<功能>.py`；影響共用管線、資料契約或跨功能時跑 `.venv/Scripts/python.exe -m pytest -q`。
2. 檢查 staged diff，排除 `.env`、金鑰、token、憑證、`site/` 與其他產物。驗證通過後提交至功能分支，建立 PR 並合併到 `main`。
3. 涉及網站發布時，等本次 `main` commit 的 GitHub Pages 工作完成並核對正式頁面。回覆列出修改、驗證、commit／PR 與適用的部署結果。
