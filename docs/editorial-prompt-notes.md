# 編輯規範 prompt — 整合說明

站長撰寫了「航空新聞事實核驗與摘要引擎」prompt：v1（2026-07-27 上午，
原文見 `editorial-prompt-zh.md` / `editorial-prompt-en.md`）與 **v2**
（同日 PDF「Aviation News Verification Engine」/「航空新聞核驗與摘要規範」，
現行整合基準）。v2 相對 v1 的主要變化，均已進入 `pipeline/write.py`：

- 三態 `publish / publish_brief / reject`；航空安全與高風險事件仍保留
  riskFlags，但只要本次來源與逐字引文通過程式核驗便自動發布。舊
  `manual_review` 僅作 `data/review.json` 一次性遷移相容，結果封存至
  `data/review-archive.json`。
- 廢除 `"none"` 旗標，改用空陣列。
- facts 為 1–6 項且必須原子化；除 `factId`、`sourceQuote` 外，新增
  `sourceUrl`、`evidenceScope`、`archiveEventId`、`archiveContext`。
  `headlineSupportedBy` / `summarySupportedBy` 除驗證引用存在外，兩者都必須
  至少有一項本次 `SOURCE` fact。
- 新增 `entities`（只收原文出現的實體，不得補全）與 `eventStatus`。
- `reject_reason` 更名 `decisionReason`。
- 字數規格：繁中標題 18–38 字、摘要 80–140 字；英文標題 45–100 字元、
  摘要 70–130 詞（prompt 層執行）。
- 完整稿長度採程式硬性閘門：繁中至少 500 個實質字元（不計空白、標點、符號）、
  英文至少 250 詞，且兩種語言都至少 4 段。未達門檻視為無效草稿，主要模型
  會重試一次，仍失敗時依序交給備援模型。短但明確的低風險新事件可輸出
  `publish_brief`：繁中 180–320 個實質字元、英文 90–150 詞，各至少 2 段；
  不得靠重複或虛構背景湊字數。
- 新增 `archive_context.py`，只從已發布的 `data/articles/*.json` 檢索具日期、
  URL、逐字引文及明確關聯的歷史 facts。最多選 3 個事件／12 項 facts；
  不使用外部搜尋、embedding 或 LLM。舊文多來源卻沒有 fact-level URL 時
  fail closed。歷史資料只能作前情，不能取代本次事件證據。
- 題材採抓取後與發布前雙重程式閘門，只接受航空、空域、航運、鐵路與道路
  運輸核心事件。軍事題材仍須直接涉及軍機、軍艦／港口或運輸行動；一般軍事
  政治、演習立場、國防預算與官員視導即使被模型標成軍事，仍不得發布。

v1 整合時的三項架構性調整仍然適用：

1. **證據基礎 = 實際提供的 SOURCE 與受控歷史 facts**。管線可依 allowlist、
   robots.txt 與著作權限制擷取部分官方全文；否則只使用 RSS 標題與摘要。
   source_quote 的逐字驗證對「實際餵給模型的 title+summary+可用全文」進行，
   archive fact 則另比對已選 event ID、引文與 URL，且全部由 **程式碼**
   （`write.verify_facts`）做子字串比對強制執行——引文驗證不依賴模型自律；
   引文全數比對失敗的草稿不得發布（v2 的 1–6 項門檻由 schema 執行）。

2. **一次呼叫、雙語輸出**。原設計 zh／en 各一份 prompt（每篇 2 次呼叫）；
   管線維持單次呼叫同時產出 zh+en（免費額度減半、且避免單語 reject
   造成兩語不同步）。繁中摘要規格為 80–140 字。

3. **requires_human_review 已退役**。新稿固定為 false；高風險題材以
   riskFlags 留痕，但來源、逐字引文、事實綁定與防虛構閘門任何一項失敗
   仍會 reject，不會因取消人工介面而降低證據標準。

其餘規則——SOURCE 視為不可信資料（prompt injection 防護）、僅用所給素材、
禁止推論補全清單、保留不確定性、日期紀律、航空安全特別規則、
訂單/意向書等狀態精確度、台灣用語、publish/reject 閘門與 rejectReason、
riskFlags 枚舉、輸出前自我檢查——均已整合。
