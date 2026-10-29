# SKYTICAL Open-source Scouting

更新日期：2026-10-25


## 規則式官方公告短訊（2026-10-25）

以 GitHub API、README 與授權資料比較三個仍維護中的正文抽取專案；沒有複製程式碼或新增依賴。

| 專案 | 最近推送 | Stars | 語言／授權 | 架構、借鑑方向與額外複雜度 |
| --- | --- | --- | --- | --- |
| [Trafilatura](https://github.com/adbar/trafilatura) | 2026-10-23 | 7,021 | Python／Apache-2.0 | 正文、metadata 與重複段落抽取；有完整抽取流程，但本需求重點為已取得正文的欄位核驗，不需替換現有抽取器。 |
| [Mozilla Readability](https://github.com/mozilla/readability) | 2026-08-04 | 11,514 | JavaScript／Apache-2.0 | DOM 主要內容辨識；引入 Node／DOM 執行環境會增加 Python 新聞管線複雜度。 |
| [Goose3](https://github.com/goose3/goose3) | 2026-07-23 | 916 | Python（API 主要語言標為 HTML）／Apache-2.0 | 抽取文章正文與 metadata；增加另一套清理與設定，無法取代航空語意與欄位驗證。 |

採用既有 BeautifulSoup 正文段落與官方來源白名單，自行實作完整句型辨識及中英欄位模板。首次支援英文交機、航線啟用／恢復、每週增減班與機場設施啟閉的明確句型；不作任意全文翻譯。公告須是單一核准官方 URL、發布時間明確且在現有時效窗口內、正文非空、標題與核心實體相符，並通過既有逐字引文、欄位、專名與航空範圍核驗。否定、不確定、撤回、更正、多事件或不支援語句交回正常模型流程。先嘗試規則路徑，再做模型可用性探測，符合條件時零模型呼叫；獨立公告短訊格式與程式整理署名不改變一般稿件的篇幅契約。

## 雷達對應實機照片（2026-10-24）

查證官方 Photo API 文件與三個開源專案；不複製第三方實作。

| 專案 | 最近推送 | Stars | 語言／授權 | 比較與導入成本 |
| --- | --- | --- | --- | --- |
| [tar1090](https://github.com/wiedehopf/tar1090) | 2026-10-19 | 1,941 | JavaScript／NOASSERTION | 成熟 ADS-B 介面，參考選取航機再顯示資訊的流程；整套導入過重。 |
| [SkyWatcher](https://github.com/Sperryfreak01/SkyWatcher) | 2026-04-24 | 0 | JavaScript／未宣告授權 | 近期功能包含按 hex 查詢照片與攝影者署名；僅比較 API 整合方式，不使用其程式碼。 |
| [contrails](https://github.com/gauravdraj/contrails) | 2026-10-21 | 0 | JavaScript／MIT | 輕量 plane spotting、照片 metadata 快取；不導入其 Worker 與代理層。 |

採用原生瀏覽器 fetch 與現有 Leaflet popup，僅點選航機時依完整六位 ICAO hex 查詢照片。依 [Planespotters 官方規範](https://www.planespotters.net/photo/api) 保留 API 回傳的原始縮圖／原圖連結 URL、顯示攝影者文字署名；縮圖直接由顯示它的瀏覽器載入，不下載、重存或代理圖片。metadata 僅記憶體快取一小時、無照片十五分鐘；查無照片與失敗均不改用同機型其他實機。官方 hex 端點依已知現役實機查詢，未知 hex 由其資料庫對應註冊號；未加入機型 fallback 參數。

## 民航雷達介面與機型剪影（2026-10-24）

透過 GitHub 搜尋及官方 API 比較，僅借鑑地圖優先、機型剪影與選取資訊的互動概念，沒有複製第三方程式碼或圖示。

| 專案 | 最近推送 | Stars | 語言／授權 | 比較與導入成本 |
| --- | --- | --- | --- | --- |
| [tar1090](https://github.com/wiedehopf/tar1090) | 2026-10-19 | 1,941 | JavaScript／GitHub 標示 NOASSERTION | 完整 ADS-B 地圖、依機型顯示標記；整套接入會引入額外地圖與資料流程。本次自行繪製 SVG，不重用其授權未辨識素材。 |
| [dump1090](https://github.com/flightaware/dump1090) | 2026-10-19 | 1,149 | C／GitHub 標示 NOASSERTION | 接收解碼與地圖顯示；需要接收器與後端，超出靜態網站介面需求，沒有引用程式碼。 |
| [Leaflet](https://github.com/Leaflet/Leaflet) | 2026-10-23 | 45,771 | JavaScript／BSD-2-Clause | 既有地圖工具；沿用 divIcon、popup 與縮放控制就能完成，無新增依賴。 |

保留現有 OSM 圖磚、來源署名、民航安全過濾與快照時效限制。剪影由 SKYTICAL 原創，以明確 ICAO 機型代碼對應類別及相對尺寸；未知機型保留通用圖示，不由航空公司推測機型。符號尺寸以辨識為目的，並非地理比例。此階段不導入其他開源子系統。

## 團隊頁與創辦人介紹（2026-10-23）

透過 GitHub repository search、官方 API 與 README 比較三個仍在維護的個人網站主題。僅參考內容層級與版面設計，未複製程式碼或新增依賴。

| 專案 | 最近提交 | Stars | 語言／授權 | 架構、借鑑方向與導入成本 |
| --- | --- | --- | --- | --- |
| [al-folio](https://github.com/alshedivat/al-folio) | 2026-10-19 | 16,268 | HTML／MIT | Jekyll 個人網站；參考照片、個人介紹與內容分段。整套導入需要 Ruby／Jekyll，與現有建站流程重複。 |
| [Minimal Mistakes](https://github.com/mmistakes/minimal-mistakes) | 2026-10-09 | 13,588 | HTML／MIT | Jekyll 雙欄個人網站；參考介紹與主要內容的閱讀層級。需要 Jekyll 與 include-cache 外掛，不適合只為一頁加入。 |
| [Blowfish](https://github.com/nunocoracao/blowfish) | 2026-10-07 | 2,916 | HTML／MIT | Hugo 與 Tailwind CSS 4；參考響應式介紹頁。需要另一套建站與 CSS 工具，不導入。最近推送為 2026-10-21，與最近主分支提交日期分開記錄。 |

SKYTICAL 已有 Jinja2 共用導覽、雙語路徑與主題色票；保留現況，用一份雙語設定、一個版型與頁面限定 CSS 完成。使用創辦人提供的照片，以 CSS 控制顯示範圍，保留原始影像。沒有需要另開 issue 導入的套件。

## 日本突發飛安搜尋與來源零筆提示（2026-10-23）

本次透過 GitHub API 查證維護狀態、授權與 README，並實測日本語 RSS：

| 專案 | 最近推送 | Stars | 語言／授權 | 比較結果 |
| --- | --- | --- | --- | --- |
| [GNews](https://github.com/ranahaani/GNews) | 2026-10-09 | 1,018 | Python／MIT | 可參考語言、國家與查詢設定；SKYTICAL 已有 RSS 與來源署名流程，不需再加封裝。 |
| [google-news-scraper](https://github.com/lewisdonovan/google-news-scraper) | 2026-10-15 | 384 | JavaScript／MIT | v3 改用 RSS，部分功能仍需 Puppeteer；增加 Node／瀏覽器流程不符本次需求。 |
| [feedparser](https://github.com/kurtmckee/feedparser) | 2026-10-06 | 2,448 | Python／BSD 類授權，上游 API 標示 NOASSERTION | 已有依賴，保留現行 RSS 正規化；零筆健康判斷屬 SKYTICAL 作業狀態，放在既有抓取流程。 |
| [google-news-url-decoder](https://github.com/SSujitX/google-news-url-decoder) | 2026-10-18 | 302 | Python／MIT | 實測確認站內轉址後需簽章查詢才能取得原文。僅在既有 resolver 修補必要協定，不導入套件、批次系統或非同步架構；協定 context 的授權聲明保存在 `docs/licenses/google-news-url-decoder.txt`。 |

保留現有 requests、feedparser、BeautifulSoup 與來源／正文核驗。新增日本語搜尋與少量日文航空用語，所有解析失敗的 Google 連結仍不進入待稿；重要媒體連續三次成功抓取卻無可用新聞時才提示，低頻官方公告不套用此警示。原文解析相容修補屬現有功能 bugfix，沒有引入新套件或替換子系統。

## 撰稿模型搜尋評估（2026-10-18）

透過 GitHub API 查證下列搜尋專案；本次只比較設計，未複製程式碼。

| 專案 | 最近推送 | Stars | 語言／授權 | 可借鑑設計與導入成本 |
| --- | --- | --- | --- | --- |
| [MiniSearch](https://github.com/lucaong/minisearch) | 2025-09-16 | 6,173 | TypeScript／MIT | 欄位搜尋與結果過濾；需新增瀏覽器套件及索引流程。 |
| [FlexSearch](https://github.com/nextapps-de/flexsearch) | 2026-06-28 | 13,807 | JavaScript／Apache-2.0 | 文件欄位與標籤索引；設定與打包成本高於目前需求。 |
| [Fuse](https://github.com/krisk/Fuse) | 2026-08-09 | 20,506 | JavaScript／Apache-2.0 | 多欄位搜尋；模糊比對可能混淆精確模型版本。 |

SKYTICAL 已有靜態 JSON 索引與零套件搜尋。本次保留現況，將公開模型署名加入獨立欄位，再以模型名稱篩選結果；支援連寫與連字號，模型條件不套用放寬比對。這樣可避免內部 provider ID 進入公開索引，也不需要新增依賴。MiniSearch 的欄位過濾可留待資料量成長後評估，目前不導入。

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

### 2026-10-06 — Sites 暖備援調查

以下比較用於判斷獨立 RSS／儲存與 Python runtime；未複製第三方程式碼、
未新增 production 依賴。詳細備援能力及驗收見 `docs/sites-standby.md`。

| 專案 | 最近 push（UTC 日期）／stars | 語言／授權 | 可參考架構 | 導入成本與決定 |
| --- | --- | --- | --- | --- |
| [acviana/cloud-reader](https://github.com/acviana/cloud-reader) | 2026-03-28／0 | TypeScript／API 未標示授權 | Workers、D1、RSS 與靜態 UI | 架構參考；未確認授權，不搬用程式碼 |
| [johnwmail/tsrss](https://github.com/johnwmail/tsrss) | 2026-09-09／7 | TypeScript／MIT | RSS 服務及部署方式 | 須重新接上來源核驗與事件去重，保留既有管線 |
| [cloudflare/workers-py](https://github.com/cloudflare/workers-py) | 2026-10-06／120 | Python／MIT | Pyodide Python Workers | 不等同一般 CPython；套件及 runtime 契約需測試，暫不導入 |
| [thematters/matters-rss-service](https://github.com/thematters/matters-rss-service) | 2026-08-02／2 | JavaScript／MIT | RSS 來源整理服務 | 無法代替既有撰稿／證據核驗／發布管線，僅參考 |

結論：既有 Python 管線的核驗規則較完整，暫時不為備援重寫成另一套 RSS
服務。本次僅實作可重跑的閱讀快照匯出；全系統接管須有獨立執行器、
資料持久化與故障演練，不能把 Sites 靜態頁面視為完整接管。

截至 2026-09-26，GitHub-first 階段可在不碰 production 的項目已完成：

- 正文抽取比較工具與手動 workflow 已建立。
- 去重／事件分群比較工具、標註資料集與手動 workflow 已建立。
- GitHub-first 規則已寫入 `AGENTS.md`。
- benchmark 依賴均與 production requirements 分離。

下一步只剩「依 benchmark 真實結果決定是否導入」。在沒有實測報告前，不直接替換 `pipeline/fulltext.py` 或 `pipeline/dedupe.py`，避免為了套件而增加 production 風險。

## 模型新聞搜尋入口（2026-10-29）

比較 openai/openai-python（31,995 stars、Apache-2.0、2026-10-29 仍維護）、openai/openai-agents-python（30,371 stars、MIT、2026-10-27 仍維護）及 BerriAI/litellm（62,297 stars、2026-10-29 仍維護；GitHub 未能辨識單一授權，因此不引用程式碼）。前者適合標準 Responses SDK；Agents 適合多工具調度；LiteLLM 適合多平台閘道。現有快報已以 requests 接入 Responses web_search 與用量記錄，重用該入口較輕量，不新增 SDK、agent loop 或外部搜尋服務，沒有複製第三方程式碼。
