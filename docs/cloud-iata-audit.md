# 雲端每四小時機場 IATA 檢查

以 GitHub Actions 的 `airport-iata-audit` 執行，不依賴本機電腦或 Codex 開啟。
使用網站既有 `OPENAI_API`、`OPENAI_MODEL_ID` secret，只有本流程的 Luna 呼叫
固定 `max`，並與撰稿、70% 一般新聞審稿及雙語快報共用預算保護。

- 首個區間：臺北時間 2026-11-01 00:00（含）至 04:00（不含）。
- 每日臺北時間 00、04、08、12、16、20 時觸發；UTC cron 為 `0 */4 * * *`。
  Actions 可能延遲，因此程式以固定四小時邊界及持久化 checkpoint 補查漏跑區間，
  每次最多補十二個區間；失敗時保留上次成功位置，不把漏查視為通過。
- 檢查 main 快照的全部新刊登／修訂文章，不採 70% 抽樣。除文章時間外，
  還比較 Git 歷史內的標題及正文變更，涵蓋沒有更新 updatedUtc 的修正。
- Luna 先獨立找出中英文標題與正文各自首次提及的機場，回傳實際欄位與逐字引句；
  必須覆蓋所有輸入文章。程式再驗證引句、IATA 本機資料與既有首次提及規則。
  城市名稱不猜機場，陌生名稱／模型提案與本機資料衝突均列為待核驗，不自動寫入文章。
- 未提機場者列為不適用；同內容重新出現可重用已完成的檢查，不因換圖片重花 API。
  過大的單篇或無法解析的資料會明確失敗，不截斷後宣稱全量檢查。
- 輸出 JSON artifact 與 Actions 摘要，含時間窗、篇數、文章連結及問題欄位。
  有缺漏／錯碼時作業回傳非零狀態，可使用 GitHub 原有 Actions 失敗通知；
  正常時不建立 issue、不送信，也不新增其他通訊工具。
- 不修改新聞、別名表或網站，不建站、不部署。唯一持久化寫入為
  `data/iata-audit/state.json`（checkpoint、可重用結果及保守費用總額）。
  寫入使用 SHA compare-and-swap，commit 帶 `[skip ci]`。
- 本檢查的費用上限每日 US$0.80、每月 US$8。每次 HTTP 呼叫先將輸入上界及
  48,000 輸出 token 的預留額保存至 GitHub，保存失敗就不呼叫模型；取得用量才
  結算，逾時或缺少用量保留預留額，避免重啟後忘記費用。這是本檢查的上限，
  另受共用每日 US$1.50、每月 US$30 上限約束。其他正式 API 工作也使用同一預算入口；外部程式不在本站帳本範圍內。

本機離線測試：`python -m pytest -q tests/test_iata_audit.py`、
`python tests/test_airport_codes.py`。部署後第一個 push 作業會先驗證 secret
設定，起始時間前不呼叫 Luna；首輪真實內容檢查由 04:00 排程開始。

技術偵察沿用已比較的 promptfoo（固定樣本評測）與 Instructor（結構化輸出），
並確認 mborsetti/airportsdata 在 2026-10-30 仍維護（169 stars、Python；GitHub
授權標示 NOASSERTION）。保留 repository 已採用的 airportsdata 套件與 requests
provider，不複製第三方程式碼、不新增 production 依賴。排程直接使用 GitHub
原生 cron，不引入外部排程服務。
