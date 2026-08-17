# SKYTICAL AI 快速作業規則

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
