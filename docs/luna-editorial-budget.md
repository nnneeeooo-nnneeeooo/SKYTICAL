# Luna 備援、審稿與預算

2026-11-01：依使用者提供的 US$50 現有額度、每月至少 US$33 補充規劃。
這些數字是預算輸入，不是程式查得的帳戶餘額；程式不會自動加值。

## 備援與審稿

- `AVWIRE_LUNA_EDITORIAL=true` 啟用逐篇路由。臺灣、飛安／重大營運事件及
  已發布的重大適航指令等監管行動，在主模型失敗後接手；一般新聞在兩個
  不同平台失敗，或前序模型累計約 60 秒後接手。重複嘗試同平台不算兩個平台。
- 前序模型先嘗試一次，避免原地修稿耗盡時間；Luna 保留原有一次修復機會。
  模型拒絕或編輯退稿仍終止該次路由，不轉交其他模型強行發布。
- 一般新聞開放 Luna 備援，但不因此開放其他付費模型。概念展示、例行測試、
  小型交易等既有 niche 類別維持免費路由。來源核驗、事實引用、用語及去重門檻不變。
- 重要新聞全部審稿；一般新聞以來源 URL 的 SHA-256 固定抽查 70%，重跑不重抽。
  選中的規則式公告也走同一審稿流程，不從零模型公告捷徑略過。
- 審稿只使用當次來源標題、摘要、已擷取正文與中英文稿，不使用模型記憶或
  歷史 companion 當新證據。每個問題須指定稿件欄位、稿件逐字引句、來源索引及
  可在來源找到的逐字引句；無法驗證的審稿結果視為不可用。
- 有證據的問題最多觸發一次定向重寫，重新通過所有原有機器核驗與一次審稿後
  才發布。再次失敗、審稿拒絕、預算不足或服務不可用，都保留來源待重試，
  不標記已發布、不覆蓋既有編輯稿。修復仍失敗會使用內容失敗重試額度。
- `data/luna-editorial.json` 僅保留最近 1,000 次的時間、group ID、輸入摘要雜湊、
  結果及問題數，不保留擷取原文、提示詞、私有模型名稱或推理內容。
- Luna 所有撰稿、審稿、修復、雙語快報、來源搜尋及手動呼叫統一使用 `max`，
  不因修復、舊環境變數或手動較低檔位而降級。其他平台仍依各自支援的參數執行。

## Terra API 記帳及每日 US$2 GitHub 通知（2026-11-15）

- 站內每日及每月金額硬上限均已取消。config/luna_policy.json 中
  daily_limit_usd 保持 null；原有共用每月 US$30、用途分配額度，
  及 IATA 每月 US$8 上限都已移除。
- daily_warning_usd = 2.0 僅用於提醒，不會停止模型請求。
  臺灣時間每日 00:00 重新計算；當站內帳本的已結算保守估算金額
  達 US$2，Actions 顯示 warning 並建立一則指派給儲存庫擁有者的
  GitHub Issue。同一天若已經有同名 Issue 就不重複建立。
  App 或 Email 是否推播仍依 GitHub 個人通知設定。
- 預先保留的 token 上界不算達標；逾時或缺少 usage 的呼叫
  繼續保留保守預留額，但不被誤判為已結算用量。舊版的 warned
  US$0.80 旗標不影響新版 warned_usd2。
- AVWIRE_PAID_BUDGET_ENABLED=true 啟用記帳；正式 hourly、briefing、
  manual-draft、Copilot、IATA 及 token-retry 都走共享帳本。
  每次付費 HTTP 請求前，先保存保守預留額；收到 usage 後結算。
- Terra 標準參考價每百萬輸入 US$1／輸出 US$5。
  輸入採 1.25 倍保守估計，超長 context 與工具呼叫另納入預留。
  推理 token 已包含在 output，不重複計算。
- Terra 不指定 max_output_tokens；記帳時以官方原生 128,000
  輸出 token 估算預留費用，但不以此截斷模型生成。
  未知模型費率、無上界工具、無效輸出參數與帳本損毀仍拒絕呼叫，
  這些都是資料安全檢查，並非金額硬上限。
- 此帳本不等於 OpenAI 組織帳單，也不包含其他使用同一 API 組織的
  專案。移除站內硬上限之後，官方免費額度耗盡可能產生實際費用。

## 每日快報與跨工作流程持久化

沿用每日三版雙語快報、來源證據驗證及原有摘要快取。
正式付費工作流程仍共用 skytical-paid-api- 前綴的 concurrency group，
避免不同 GitHub Actions 同時覆寫帳本。每筆請求先透過
SHA compare-and-swap 持久化**該請求**的保守預留額；
工作完成後，即使主要步驟失敗，也在 always 步驟保存用量。
舊制每月剩餘額度 escrow 已取消，因為月度金額已無上限。

GitHub token 必須有 contents: write 及 issues: write 權限。
無法事先保存預留額時，為避免遺失記帳，該請求不送出付費 HTTP。
達標 Issue 建立失敗時，persist 步驟會報錯；下一輪執行會重試，
並以當日 Issue 標題去重。

## 驗證與檢視

- `python -m pytest -q tests/test_paid_budget.py tests/test_luna_editorial.py tests/test_luna_workflows.py`
- `python tests/test_write_offline.py`：包含提早接手、審稿保留來源與修復後重新核驗的整合測試。
- Windows 執行既有測試時使用 `PYTHONUTF8=1`，避免子程序輸出以 cp950 解碼。
- 全庫 pytest 仍會在既有 `tests/test_briefing_writer.py` 收集時因 `sys.exit()` 中止；
  其測試改以獨立腳本執行。

觀察至少七天的記帳與審稿結果，再比較成功發布成本、失敗類型、審稿攔下的有效問題
及出稿時間；審稿模型的問題數不等同人工確認的錯誤數。

官方依據：[Terra 模型／價格](https://developers.openai.com/api/docs/models/gpt-6.1-terra)、
[推理 token 計費](https://developers.openai.com/api/docs/guides/reasoning)、
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。

整合上線時，首次共用帳本會保留既有 IATA 檢查已累計的保守費用。超過 272,000 輸入 token 的長 context 請求另保留輸入 2 倍、輸出 1.5 倍費率；搜尋動態 context 也納入此上界。

2026-11-07：依站方指示，Luna 不設程式層處理時限。撰稿、修復、審稿、快報、手動呼叫及 IATA 的 HTTP 讀取等待無上限，來源搜尋也移除原有 120 秒等待；連線建立仍限 10 秒。Luna 不套用單次 180 秒、稿件 360 秒或整輪 15 分鐘的截止時間；其他模型維持既有時間限制。免費模型整輪時間用完後，符合付費分流的剩餘新聞仍可交給 Luna。

當時 MAX、呼叫／修復次數、來源核驗與月度額度規則維持；月度額度限制已於 2026-11-15 移除。IATA 不另設 45 分鐘作業上限，所有工作仍受 GitHub 託管 runner 每個 job 最長 6 小時限制（[官方執行限制](https://docs.github.com/en/actions/reference/limits)）。此設定避免本機等待期限中止慢請求，不保證服務端不發生限流、錯誤或斷線；中止與未知用量仍保留預留額。

2026-11-07：依站方指示，移除所有 Luna 呼叫及格式修復的 `max_output_tokens`，包含撰稿、審稿、快報、手動呼叫、來源搜尋及 IATA。服務端原生容量仍適用；官方 Luna 目前最多輸出 128,000 token，並非無限輸出。共用預算與 IATA 帳本以此原生容量預留，收到用量後按實值結算；即使服務回傳量超出預留估算，也完整記帳，不截斷回應。當時每日無上限，月度與用途額度仍有限制；這些金額限制於 2026-11-15 移除，MAX 及處理等待設定仍維持。
