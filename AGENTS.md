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

## 航空短訊彙整配圖

- 每則短訊各有一張配圖，使用 `roundupItems[i].image` 的一般圖片物件；找不到合適圖片時保留 `null`，前端該張顯示預設圖。不得只修改文章頂層 `image` 就宣稱全部配圖完成。
- 手動要求 GPT 配圖時，逐則核對主題、來源、授權與說明，將圖片寫入對應項目，圖片設 `curated: true`、該項設 `editorialImageLocked: true`；保留其餘項目圖片與 `imageContext`。若有 editorial override，也須同步更新對應紀錄。頂層 `image` 是相容封面，由第一張有效項目圖片同步取得。
- 使用與首頁相同的輪播程式；張數必須等於短訊數量，含預設圖，並逐張驗證中英文、手機與桌機切換。

## 修改、測試與上線

### 新聞配圖（含 GPT 手動配圖）

- 自動與手動配圖均使用 `images` 圖片物件陣列；每篇最多 5 張，依關聯程度排序，只保留最合適的圖片。短訊彙整每則 1 張、整篇最多 3 張。`image` 同步為最有關聯的第一張，供首頁縮圖、社群與舊介面使用。
- 優先找可查證重用授權、且確實拍到本次事件的原照。先找主辦方、當事單位或明示媒體轉載條件的供稿平台，例如[中央社財經訊息平台的媒體供稿](https://www.cna.com.tw/business/notice)。逐張比對供稿原文、照片內容、圖說和適用的授權條款；供稿平台的轉載條款以該平台供稿為限。
- 每篇沿用既有配圖版型，以單張圖片網址在正文上方直接顯示該篇對應的原照，附中英文圖說、攝影者或供圖者、來源與授權。文章配圖限用可查證授權的實拍照片。找不到合適的事件原照時，依序找同一註冊號實機、同航空公司且同機型、直接相關地點或主題的授權資料照，並標明是資料照。找不到合適照片時使用網站預設圖；重複照片與不同尺寸版本只保留一張。
- GPT 收到手動配圖要求時，主動搜尋並實際檢視適合的候選，確認授權、作者、來源、機型（如適用）及與新聞的關係。每張包含 `url`、`link`、`subject`、`subjectEn`、`credit`、`license`、`provider`、`kind` 與可查證的 `description`，並在可取得時以 `licenseUrl` 記錄授權條款網址。編輯核對後才可設 `curated: true`；有一張合適的事件原照即可使用單圖。
- 一般新聞寫入 `article.images`；短訊彙整寫入每則 `roundupItems[i].images`，同步其 `image`，不可跨短訊混圖。需要保留人工選圖時設 `editorialImageLocked: true`。圖片更新保留原始刊登時間、文章正文與作者署名。
- 多張圖片須確認中英文文章均能輪播、前後切換、點選圓點及手機滑動，且切換後圖說與授權連結同步；僅一張時正常顯示單圖，零張時使用網站預設圖。

1. 檢查工作目錄、目前分支及差異，保留既有或無關變更。
2. 實作最小且完整的修正。
3. 先跑直接相關測試；只有共用管線、資料契約或跨功能修改才跑完整測試：
   - 單一測試：`.venv/Scripts/python.exe -m pytest -q tests/test_<功能>.py`
   - 完整測試：`.venv/Scripts/python.exe -m pytest -q`
4. 檢查 staged diff，禁止提交 `.env`、API key、token、憑證、`site/` 或其他產物。
5. 測試通過後提交到功能分支，建立並合併 PR 至 `main`。
6. 等待這次 `main` commit 對應的 GitHub Pages workflow 完成，再確認正式網站；不要用舊的成功紀錄代替本次驗證。
7. 最終回覆只需列出：確認結果、修改內容、測試結果、commit／PR、部署結果。失敗時先修正可修正問題，不要只停在分析。
