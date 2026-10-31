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

## 預算與會計

`config/luna_policy.json`：每個臺北曆月 US$30；每日 US$0.80 提醒、US$1.50
硬上限。分配目標為撰稿／救稿 US$20、審稿 US$8、整理 US$2。審稿及整理可
共用 US$10 彈性額度，保留 US$20 給出稿；撰稿可使用尚未花掉的彈性額度，
所有用途仍共用每日／每月總上限。提醒以 Actions warning 顯示，不另發送訊息。

- `AVWIRE_PAID_BUDGET_ENABLED=true` 才啟用。正式 hourly、briefing、manual-draft、
  Copilot 與 IATA 的付費執行步驟均啟用；本機及 PR 離線測試預設不啟用。
- 每個實際 HTTP 呼叫（含格式修復）都先在 `data/paid-budget.json` 預留上界。
  請求內容的 UTF-8 位元組數加框架餘量保守估算輸入；輸出使用實際 token 上限，
  Luna 各流程最多 48,000，供 MAX 推理及最終內容共用。搜尋另預留完整 context 與工具次數。
- 官方標準單價輸入 US$0.10／百萬、輸出 US$0.50／百萬；會計以輸入單價 1.25 倍
  保守涵蓋 cache-write，不將快取折扣先當成可花額度。因此本站記帳可能略高於帳單。
  推理 token 已包含在 API 的 `output_tokens`，不重複加計。
- 收到用量後才結算。逾時、程序中止、無用量或無法解析回應，保留整筆預留額；
  不自動釋放未知費用。Ledger 損毀、未知模型單價、無上限工具或輸出均拒絕呼叫。
- 以臺北日／月切換新額度桶，歷史用量及未結算預留不會被刪除。此上限只計算
  本功能啟用後、通過本站預算入口的支出，不是 OpenAI 帳戶全域費用上限。
  其他程式、人工 benchmark 或同 API 組織的外部使用不在此 ledger 範圍內。
- 模型私有對應沿用既有 secret，只在 HTTP 邊界解析，不寫入記帳或公開資料。

## 每日整理與跨工作流程持久化

重用既有每日三版雙語快報及其來源證據驗證、digest 快取與最多兩次呼叫；
快報撰寫計入 summary，既有來源搜尋計入 draft。不另加一個重複摘要排程。
整理額度不足時，快報維持既有擷取式降級，不阻塞完整快報。

五個正式 API 工作流程（含雲端 IATA）共用 `skytical-paid-api-${{ github.ref }}` concurrency group，
不取消執行中的作業。每次先用 repository token 讀取最新 ledger，再允許付費步驟；
第一次付費呼叫前，先以 GitHub contents API 的 SHA compare-and-swap 保存該日
剩餘預算的保守 escrow（仍受當月剩餘額度約束），同次執行後續呼叫不重複提交。
保存失敗就不送付費請求。結束後以 `if: always()` 保存實際費用與未知呼叫的預留額，
釋放未用 escrow；即使建站／模型步驟失敗也保存帳本，不提交其他未完成的內容。
不同執行程序的本機扣款另有 Windows／Linux 檔案鎖。

外部修改 ledger 造成 SHA 不符時拒絕覆寫並使工作流程失敗；網路或 GitHub API 故障
若阻止最後的結算保存，遠端仍保留先前 escrow，後續工作只能少用預算，不能將
該筆支出當成零。需檢查該次工作流程，依 API 步驟後上傳的獨立帳本 artifact 補回
結算。不得在未確認未知費用前手動清零預留額。

## 驗證與檢視

- `python -m pytest -q tests/test_paid_budget.py tests/test_luna_editorial.py tests/test_luna_workflows.py`
- `python tests/test_write_offline.py`：包含提早接手、審稿保留來源與修復後重新核驗的整合測試。
- Windows 執行既有測試時使用 `PYTHONUTF8=1`，避免子程序輸出以 cp950 解碼。
- 全庫 pytest 仍會在既有 `tests/test_briefing_writer.py` 收集時因 `sys.exit()` 中止；
  其測試改以獨立腳本執行。

觀察至少七天的記帳與審稿結果，再比較成功發布成本、失敗類型、審稿攔下的有效問題
及出稿時間；審稿模型的問題數不等同人工確認的錯誤數。

官方依據：[Luna 模型／價格](https://developers.openai.com/api/docs/models/gpt-6-luna)、
[推理 token 計費](https://developers.openai.com/api/docs/guides/reasoning)、
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。

整合上線時，首次共用帳本會保留既有 IATA 檢查已累計的保守費用。超過 272,000 輸入 token 的長 context 請求另保留輸入 2 倍、輸出 1.5 倍費率；搜尋動態 context 也納入此上界。
