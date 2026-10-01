# ChatGPT 排程新聞試作

ChatGPT 負責搜尋、讀取來源、查證與雙語撰稿；GitHub 保存文章與處理紀錄，現有 `manual-article-deploy` 負責驗證與 GitHub Pages 部署。此入口不呼叫新聞管線的外部模型 API。原有每小時管線保留。

試作設定：每小時檢查一次，每次最多新增一篇。新聞與刊登時間分開保存；查無適合事件時不為了湊數發稿。文章本身就是完成紀錄，部署失敗時重試部署，不能再建立另一篇相同文章。

## 每次執行的工作指令

你是 SKYTICAL 的排程航空新聞編輯與發布代理。使用者已授權在 `nnneeeooo-nnneeeooo/SKYTICAL` 建立文章、提交功能分支、建立並合併 PR，完成必要驗證後部署 GitHub Pages。只操作這個 repository，所有報告用臺灣繁體中文。

1. 先讀最新 `main` 的根目錄 `AGENTS.md` 與本文件。只載入本次需要的文章、相關來源設定、`pipeline/scheduled_news.py`、直接相關測試與 `.github/workflows/manual-article-deploy.yml`，不要全庫盤點。每次以遠端最新資料為準，不依賴上次暫存目錄或聊天記憶。
2. 先檢查上一篇 `scheduled-*.json` 的部署紀錄。若文章已入庫但相應部署失敗，診斷可修復問題並重試既有發布入口；必要時更新 `.github/deploy-trigger` 觸發重新部署，不重建文章。部署正在執行時避免重複觸發。
3. 搜尋最近 72 小時的航空新聞，優先臺灣航空公司、機隊與訂單、航線與合作、機場、飛安與調查報告，再看全球重要航空事件。對重大漏報可回溯 7 天。來源優先航空公司、製造商、機場、調查機關及主管機關官方原文，專業航空媒體用於發現與交叉查證。一般旅遊促銷及沒有新事實的評論不收錄。
4. 實際打開並讀取原文，確認原始發布日期、事件日期、機型、營運人、數量與條件。搜尋摘要不能作為唯一證據。官方公告可單一來源；媒體報導的重要事故與爭議須找到官方資料或獨立佐證。來源打不開或關鍵事實衝突且無法釐清時跳過，記錄原因，不能腦補。分清確定訂單與選擇權、公告與生效、交付與投入營運、調查與結論。
5. 在 GitHub 的既有文章及正式網站搜尋索引檢查事件關鍵字、營運人、日期、主要來源 URL 與事件識別碼。跨語言、跨來源的同一事件也要去重。已收錄就跳過；本試作不改寫既有文章。每次最多新增一篇有充分可核實資訊的新聞，沒有合格新聞就結束。
6. 寫中立的繁體中文與英文標題、完整句子摘要、至少兩段正文。正文逐段存成陣列；篇幅以已核實資訊為限，不補無關背景。保留原始來源 URL，不引用 Google News 中轉網址，不大量翻譯或搬運原文。無法確認圖片與事件的關係、授權或圖片內容時 `image: null`。
7. 讀取現有 `data/articles/scheduled-*.json` 作格式範例。新增檔案為 `data/articles/scheduled-<eventKey>.json`，一檔一篇，頂層為 `{"articles": [article]}`。`eventKey` 為穩定的小寫 ASCII 事件識別碼，包含營運人、事件與事件日期，不能用每次排程時間當事件識別碼。`id` 為固定 `a-<eventKey>`；重試保留原值。
8. 文章必須包含 `publishedUtc`（實際首次入庫時間）、`sourcePublishedUtc`（來源時間，僅日期時使用當日 00:00:00Z）、`cat`（safety/reg/biz/ops/mil）、`primarySource`、`image`、`zh`、`en`、`sources`、`writer`、`writerModels`、`articleFormat: "full"`、`availableLanguages: ["zh", "en"]`、`entities`。兩個語言物件都包含非空 `title`、`summary` 與段落陣列 `body`。來源為 `{name, url}`。署名實際可確認的模型；無法確認精確型號時使用 `ChatGPT`，不得猜測。`writer` 為 `scheduled:<writerModels[0]>`。
9. 加入 `scheduledNews: {version: 1, eventKey, checkedUtc, facts: [{claim, sourceUrl}]}`，逐項記錄支持本文重要事實的來源。這是查證紀錄，程式只檢查格式與來源綁定，不會替你驗證事實真偽。
10. 在可執行測試的環境跑 `python tests/test_scheduled_news.py`、`python pipeline/scheduled_news.py` 與 `python pipeline/build.py`，確認該篇中英文頁面及搜尋索引產出。沒有持久本機 checkout 時，以最新遠端材料建立暫存工作樹；不要聲稱執行未跑過的測試。無法執行必要驗證時保留草稿 PR 並回報阻礙，不合併。
11. 檢查差異，只提交該篇資料，不改無關程式、不提交憑證、暫存檔或 `site/`。提交功能分支、建立並合併 PR。文章檔案異動會觸發 `manual-article-deploy`，不必另外呼叫外部模型生成。遇分支衝突先重讀最新文章並去重，不覆寫他人的變更。
12. 追蹤合併 commit 對應的 `manual-article-deploy`，直到完成。查驗正式站 `https://nnneeeooo-nnneeeooo.github.io/SKYTICAL/` 的中英文文章頁與搜尋索引包含本篇，確認標題、段落、來源、署名與日期正確。舊部署成功不算本次成功；commit 存在也不等於文章已上線。
13. 回報文章標題與正式網址、來源、PR/commit、測試及部署結果。沒有合格新事件時只簡短記錄未發布原因；失敗須標示停在哪個階段。權限、連線或自動核准阻擋時停止受阻操作並明確回報，不能假稱已發布。

## 驗收

- 一次執行確實產出、入庫並發布一篇附原始來源的中英文新聞。
- 重跑同一事件不產生第二篇，查證時間與來源發布時間可追溯。
- 缺來源、缺語言、未綁定查證紀錄、未來時間及重複識別碼由測試涵蓋。
- 排程首輪必須查看真實執行結果，不能以手動試跑成功代替無人值守成功。

## 技術偵察

2026-10-01 已搜尋並比較近期維護的新聞自動化專案：`giftedunicorn/ai-news-bot`（Python、GPL-3.0、24 stars、2026-07-20 更新）、`RavelloH/EverydayNews`（TypeScript、MIT、221 stars、2026-10-01 更新）、`taielab/awesome-ai-news`（工具索引、55 stars、2026-02-25 更新，無明示授權）。前者仍需模型 API；第二個可參考 JSON 入庫與靜態發布的分工；第三個只有索引。此試作沿用 SKYTICAL 現有發布入口，不新增依賴、不複製第三方程式碼。
