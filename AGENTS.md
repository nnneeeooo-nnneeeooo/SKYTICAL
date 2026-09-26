# SKYTICAL AI 快速作業規則

## 新對話的工作區定位

- Codex 桌面版的 SKYTICAL 專案綁定 `C:\Users\iwnlewn\Documents\ChatGPT\SKYTICAL`；GitHub repository 為 `nnneeeooo-nnneeeooo/SKYTICAL`。
- 新對話先以目前工作目錄為準。若它是此 repository 的 checkout 或 Codex worktree，就在該工作樹的根目錄作業，不要切回上述固定路徑。
- 只有目前目錄不屬於此 repository 時，才使用上述本機路徑定位；執行修改前以 `git rev-parse --show-toplevel` 與 `git remote get-url origin` 確認，勿搜尋其他 SKYTICAL 複本。

## 預設工作方式

- 使用繁體中文（臺灣用語）。
- repository 固定為 `nnneeeooo-nnneeeooo/SKYTICAL`，正式分支為 `main`，網站由 GitHub Pages 發布。
- 收到明確修改要求時，直接定位目標檔案並實作；不要先做全庫盤點、完整架構分析或逐一檢查所有 workflow。
- 只讀本檔、使用者指定的檔案、目標程式及直接相關測試。除非修改跨越多個子系統，否則不要載入整份 README、所有文件或所有資料檔。
- 先確認使用者指定的現況；確認後只修改要求範圍，不順手重構、不改無關內容。
- 不需為可由 repository 現況判斷的事項反問使用者。

## 快速定位

- 網頁版型：`templates/`
- 樣式與前端程式：`static/`
- 新聞抓取、篩選、撰稿與建站：`pipeline/`
- 模型提示詞：`prompts/`
- 功能設定與來源清單：`config/`
- 文章、審核佇列與執行狀態：`data/`
- 自動化與部署：`.github/workflows/`
- 測試：`tests/`

先用檔名或關鍵字搜尋定位；不要為了熟悉專案而依序閱讀上述所有目錄。

## GitHub-first 技術偵察

- 新增功能、替換技術方案或重做既有子系統前，先在 GitHub 搜尋 3–5 個直接相關且仍維護中的開源專案；小型文字修正、明確 bugfix、單純設定變更可略過。
- 優先比較：最近提交時間、stars／使用規模、語言與依賴、授權、核心架構、可直接借鑑的模組，以及導入 SKYTICAL 的額外複雜度。
- 只借鑑設計與可合法重用的實作；引用或搬用程式碼前必須確認授權與 attribution 要求，不得因為公開在 GitHub 就視為可任意複製。
- 搜尋結果需先和 SKYTICAL 現況比對；現有做法若更輕量、更可控或更符合新聞來源核驗要求，就保留現況，不為了使用套件而增加依賴。
- 若找到值得後續評估的專案，更新 `docs/open-source-scouting.md`；若確認要導入，再建立獨立 issue／PR，不在同一個需求中順手大改。
- 對新聞抓取、正文抽取、去重／分群、搜尋、SEO、來源驗證與自動化尤其優先執行此流程。

## 修改、測試與上線

1. 檢查工作目錄、目前分支及差異，保留既有或無關變更。
2. 實作最小且完整的修正。
3. 先跑直接相關測試；只有共用管線、資料契約或跨功能修改才跑完整測試：
   - 單一測試：`.venv/Scripts/python.exe -m pytest -q tests/test_<功能>.py`
   - 完整測試：`.venv/Scripts/python.exe -m pytest -q`
4. 檢查 staged diff，禁止提交 `.env`、API key、token、憑證、`site/` 或其他產物。
5. 測試通過後提交到功能分支，建立並合併 PR 至 `main`。
6. 等待這次 `main` commit 對應的 GitHub Pages workflow 完成，再確認正式網站；不要用舊的成功紀錄代替本次驗證。
7. 最終回覆只需列出：確認結果、修改內容、測試結果、commit／PR、部署結果。失敗時先修正可修正問題，不要只停在分析。
