# 編輯規範 prompt — 整合說明

站長撰寫了「航空新聞事實核驗與摘要引擎」prompt：v1（2026-07-27 上午，
原文見 `editorial-prompt-zh.md` / `editorial-prompt-en.md`）與 **v2**
（同日 PDF「Aviation News Verification Engine」/「航空新聞核驗與摘要規範」，
現行整合基準）。v2 相對 v1 的主要變化，均已進入 `pipeline/write.py`：

- 三態 `publish / manual_review / reject`；**航空安全事件一律
  manual_review、不得自動發布** → 落地為 `data/review.json` 人工覆核佇列
  （GitHub 上把 `"approve"` 改 true 即發布，14 天過期，上限 40 筆）。
- `publish` 要求 riskFlags 為空；風險旗標非空只能 manual_review/reject。
  模型自相矛盾時程式一律「向下修正」為 manual_review，絕不反向。
- 廢除 `"none"` 旗標，改用空陣列。
- facts 門檻放寬為 1–6 項，且必須原子化；新增 `factId`（F1、F2…）與
  `headlineSupportedBy` / `summarySupportedBy` 證據綁定（程式驗證引用存在）。
- 新增 `entities`（只收原文出現的實體，不得補全）與 `eventStatus`。
- `reject_reason` 更名 `decisionReason`。
- 字數規格：繁中標題 18–38 字、摘要 80–140 字；英文標題 45–100 字元、
  摘要 70–130 詞（prompt 層執行）。

v1 整合時的三項架構性調整仍然適用：

1. **證據基礎 = RSS 標題與摘要，非全文**。fetch 階段刻意不抓全文
   （robots.txt 與著作權考量；例如 avherald 禁止抓取），因此
   `{article_text}` 佔位符沒有對應資料。source_quote 的逐字驗證改為對
   「實際餵給模型的 title+summary 素材」進行，且由 **程式碼**
   （`write.verify_facts`）做子字串比對強制執行——引文驗證不依賴模型自律；
   引文全數比對失敗的草稿不得發布（v2 的 1–6 項門檻由 schema 執行）。

2. **一次呼叫、雙語輸出**。原設計 zh／en 各一份 prompt（每篇 2 次呼叫）；
   管線維持單次呼叫同時產出 zh+en（免費額度減半、且避免單語 reject
   造成兩語不同步）。繁中摘要上限維持站台版型的 80 字
   （原 prompt 的 80–140 字是為其他版型設計）。

3. **requires_human_review 無人可審**。本站為無人值守小時級管線，
   風險旗標（riskFlags）改為隨文章 JSON 保存供追溯，不阻擋發布；
   高風險但證據不足的案例依 prompt 規則直接 reject。

其餘規則——SOURCE 視為不可信資料（prompt injection 防護）、僅用所給素材、
禁止推論補全清單、保留不確定性、日期紀律、航空安全特別規則、
訂單/意向書等狀態精確度、台灣用語、publish/reject 閘門與 rejectReason、
riskFlags 枚舉、輸出前自我檢查——均已整合。
