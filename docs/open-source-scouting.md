# SKYTICAL Open-source Scouting

更新日期：2026-09-26

這份文件記錄在新增功能前值得研究的成熟 GitHub 專案。它不是依賴清單，也不代表應直接導入；每次實作仍需先和 SKYTICAL 現有架構、授權、維護成本與新聞核驗要求比較。

## 評估原則

1. 最近仍有維護活動，且不是已封存專案。
2. 功能直接對應 SKYTICAL 的抓取、抽取、去重、搜尋、SEO 或新聞資料處理。
3. 優先選擇授權清楚、Python 生態成熟、可局部借鑑的方案。
4. 不因 stars 高就直接導入；若現有 deterministic 流程更便宜、更透明，就保留現況。
5. 複製或修改第三方程式碼前，另外確認 LICENSE 與 attribution 義務。

## 第一批值得研究的專案

### adbar/trafilatura

- GitHub: https://github.com/adbar/trafilatura
- 方向：網頁正文與 metadata 抽取、文字清理、爬取。
- 授權：Apache-2.0。
- SKYTICAL 可研究：當 RSS 只有摘要時，用於補抓官方／新聞頁面的主要正文與 metadata；特別適合拿來和目前 HTML 抽取 fallback 做準確率比較。
- 導入前驗證：抓取規範、robots／來源條款、對動態網站的成功率，以及是否會提高 workflow 執行時間。

### fhamborg/news-please

- GitHub: https://github.com/fhamborg/news-please
- 方向：新聞網站 crawler + article information extraction。
- 授權：Apache-2.0。
- SKYTICAL 可研究：新聞日期、作者、正文等 metadata 的解析方式，以及多新聞站點 extraction pipeline 的設計。
- 建議：以架構與測試案例為主，不直接把完整 crawler 帶進來，避免讓目前來源白名單模型變得過重。

### kurtmckee/feedparser

- GitHub: https://github.com/kurtmckee/feedparser
- 方向：Python RSS / Atom parsing。
- SKYTICAL 可研究：異常 feed、日期格式與 namespace 的容錯處理。
- 建議：若 SKYTICAL 已使用 feedparser，將它視為上游基準；新增自訂解析器前先確認是否已有原生處理方式。

### huggingface/sentence-transformers

- GitHub: https://github.com/huggingface/sentence-transformers
- 方向：sentence embeddings、semantic similarity、retrieval。
- 授權：Apache-2.0。
- SKYTICAL 可研究：跨來源標題／摘要的語意去重與事件分群 benchmark。
- 注意：目前 deterministic URL + title similarity 流程成本低、可解釋；只有在實測能明顯降低跨語言或改寫標題漏網率時才值得導入，且應避免讓去重必須依賴 GPU 或遠端 API。

### AndyTheFactory/newspaper4k

- GitHub: https://github.com/AndyTheFactory/newspaper4k
- 方向：新聞文章、標題與 metadata extraction。
- 授權：MIT。
- SKYTICAL 可研究：作為 trafilatura 的對照組，測試不同新聞來源的正文與發布日期抽取表現。

## SKYTICAL 優先研究題目

### P1 — 正文抽取 fallback benchmark

**狀態：已建立可重跑 benchmark（`benchmarks/fulltext_benchmark.py` + `fulltext-benchmark` 手動 workflow）。正式管線尚未改動。**

目標：挑 20–30 個目前常見來源，使用現行抽取器、Trafilatura、Newspaper4k 比較：
- 成功率
- 正文乾淨度
- 發布日期／作者 metadata 正確率
- 執行時間
- 失敗時是否可安全 fallback

只有結果顯著優於現況才導入。

執行方式：GitHub Actions → `fulltext-benchmark` → Run workflow。報告會寫入 Actions Step Summary，並上傳 `fulltext-benchmark` artifact。每個 URL 只抓一次，同一份 HTML 交給所有抽取器，並沿用現有 allowlist、robots 與 redirect host 驗證。

### P1 — 去重漏網率 benchmark

**狀態：已建立可重跑 benchmark（`benchmarks/dedupe_benchmark.py` + `benchmarks/dedupe_pairs.json` + `dedupe-benchmark` 手動 workflow）。正式 `pipeline/dedupe.py` 尚未改動。**

資料集目前含 30 組航空新聞標題配對（15 組同事件、15 組不同事件），涵蓋中英文／跨語言、相似機型、同航空公司不同事件等容易誤判的情境。benchmark 比較現行 deterministic `same_event()` 與 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，並輸出 precision、recall、F1、accuracy、執行時間與誤判案例。

執行方式：GitHub Actions → `dedupe-benchmark` → Run workflow。結果會寫入 Actions Step Summary 並上傳 artifact。

**導入門檻：**不得只因單次 F1 較高就切換 production。至少還要擴充獨立 holdout 樣本，確認 false positive 沒有明顯上升，並評估 CPU 執行時間、模型下載／快取與 Actions 成本後，才可另開 PR 做 production experiment。

### P2 — GitHub 專案搜尋成為新功能預設步驟

**狀態：已完成。`AGENTS.md` 已將 GitHub-first 技術偵察設為新功能／子系統替換的預設流程。**

之後新增：
- 新聞抓取方式
- SEO／sitemap
- 搜尋
- article clustering
- source verification
- 航班／航空器資料處理
- GitHub Actions 自動化

都先搜尋 3–5 個直接相關專案，再決定自己實作或導入套件。

## 不做的事

- 不把 GitHub 當大量圖片、影片或無上限資料倉庫。
- 不把第三方 repo 整份 vendoring 進 SKYTICAL，只因為「可能以後會用」。
- 不為了 GitHub SEO 複製每篇新聞全文到 repository。
- 不把公開原始碼視為沒有授權限制。

## 目前結論

截至 2026-09-26，GitHub-first 階段可在不碰 production 的項目已完成：

- 正文抽取比較工具與手動 workflow 已建立。
- 去重／事件分群比較工具、標註資料集與手動 workflow 已建立。
- GitHub-first 規則已寫入 `AGENTS.md`。
- benchmark 依賴均與 production requirements 分離。

下一步只剩「依 benchmark 真實結果決定是否導入」。在沒有實測報告前，不直接替換 `pipeline/fulltext.py` 或 `pipeline/dedupe.py`，避免為了套件而增加 production 風險。
