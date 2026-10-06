# SKYTICAL Sites 備援

## 現況

GitHub Actions／Pages 仍是主系統及唯一發布者。Sites 專案 ID 保存於
`backup/sites/.openai/hosting.json`，不可再次建立另一個同名專案。

本次提供的是 **私人閱讀快照**，不是全系統備援。執行
`.venv/Scripts/python.exe backup/export_sites.py` 會以既有建站程式產生
`.sites-work/standby/dist/`，不呼叫抓取、撰稿、付費模型或發布程式。
每頁皆標示快照時間並設定 `noindex`，canonical 保持指向主站。
`/standby/` 與 `/standby.json` 明確列出功能及來源 commit。
生成檔案與 Sites 本機 source checkout 不提交至 GitHub。

| 功能 | 本次快照 | 完整備援所需 |
| --- | --- | --- |
| 中英文文章、首頁、列表、搜尋、來源、說明、changelog | 可閱讀 | 獨立持久資料與定期同步 |
| 既有快報、事故紀錄 | 可閱讀 | 獨立產生與更新管線 |
| 航班雷達與稀有航空器 | 既有畫面及過期隱藏規則；未接通 updater | 獨立排程、來源取用及相同隱私過濾 |
| 新聞抓取、去重、證據核驗、AI 撰稿、重試 | 未接通 | 經驗證的 Python 執行器或等價改寫 |
| 三期快報與逾期補發 | 未接通 | 相同時窗、complete guard、模型憑證 |
| 手動發布／Copilot | 不輸出私人工作台及 GitHub 寫入前端 | 獨立授權、佇列、撰稿及發布端點 |
| 私有模型用量報表 | 不輸出 | 獨立身分授權與安全帳務資料 |
| 自動同步、健康檢查、接管、恢復後回寫 | 未啟用 | 以下雙系統協調契約及故障演練 |

外部圖片、地圖、新聞來源與模型供應商仍各自構成依賴。快照不宣稱能在
所有外部服務失效時完整運作，亦不宣稱支援自動更新或公開流量。

## 完整備援設計

採用 GitHub 主系統＋Sites 暖備援。平常只同步已核驗資料，不重複呼叫模型。
Sites 的 D1 保存文章索引、任務、重試、去重 ID、發布者租約和狀態；R2 保存
文章／快報、建站內容、證據及獨立程式副本。不能故障時才從 GitHub 取得
必要程式、資料或密鑰。GitHub Secrets 不可透過 API 取出，必須另外安全配置。

Sites hosted runtime 是 Cloudflare Workers，現有 requests／lxml／cryptography
等 Python 管線不能直接以既有 Actions 命令部署。Sites 雲端排程可以啟動
雲端工作，但只有建立排程不等於已確認 Python、套件、來源網路及憑證可用。
保留現有核驗邏輯的方案是獨立雲端 Python 執行器搭配 Sites updater。
在未完成全新雲端執行測試前，不啟用接管排程。

若採用外部雲端執行器，需另行決定服務與費用；Sites 公測包含於符合資格
方案的使用額度，並不保證無限或永久免費。模型 API 費用也不包含在網站託管中。

### 接管與恢復契約

1. 監測網站 HTTP、Actions 執行結果、最近成功抓取與發布狀態；不能只看首頁
   200，也不能以沒有新文章判定故障。模型或來源故障另行分類。
2. 建議初始接管條件：連續三次主站探測失敗，或任務超過已配置週期與寬限
   時間且獨立檢查確認主執行器失效。閾值是設計值，本次並未啟用。
3. 開啟備援發布前取得唯一發布者租約。GitHub 與備援都必須遵守同一租約；
   不得讓兩邊同時獨立抓取與發布，防止文章及付費呼叫重複。
4. 保留新聞來源、核驗、繁體中文、圖片相關性、pending／retry 限制與三期
   快報契約。已完整發布的快報不得再次產生。
5. 主服務恢復後先停止備援新增任務、完成在途任務、回寫文章及重試狀態，
   再驗證去重與一致性，最後把發布者租約交回 GitHub。
6. 主站網域仍指向 GitHub。Sites 使用獨立備援網址；網域自動導流需要
   獨立 DNS／入口控制及相應權限，本次沒有調整 DNS 或公開存取範圍。

## 必須通過的全系統驗收

- 模擬 GitHub API、Actions、Pages 全部不可用，電腦關機，從獨立資料及
  程式副本完成抓取→去重→撰稿→證據核驗→建站→發布。
- 完成三期快報／逾期補發、雷達及稀有航空器更新、手動發布與用量紀錄。
- 已完成的文章與快報不重複產生；來源／模型故障不造成無限重試。
- 重啟雲端執行器後資料、證據、去重與 retry 狀態仍在。
- 驗證唯一發布者、復原回寫、相同事件去重、私有工作台授權與外部訪客存取。
- 成功建立 Site、成功部署頁面、建立排程、通過上述接管演練是不同里程碑，
  報告時必須分開，不得以其中一項替代其他項目。

## 官方能力來源

- [Sites 使用與雲端排程](https://help.openai.com/en/articles/20001339-creating-and-using-chatgpt-sites)
- [Sites 開發文件](https://learn.chatgpt.com/docs/sites)
- [Work cloud 執行環境](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security)

Sites schedule 無法借用訪客的 connected-app 授權。執行器、持久儲存及秘密
必須有可供無人值守工作使用的獨立授權路徑；不得把 key 或 bearer 寫入
排程文字、來源包、前端或 GitHub。
