# SKYTICAL 免費流量追蹤設定

SKYTICAL 支援免費版 Google Analytics 4（GA4），以及不需帳號或付費的 UTM 活動連結。尚未設定 GA4 網站資料串流前，分析程式不會載入，也不會記錄任何訪客。

## 完成 GA4 設定（網站擁有者執行一次）

1. 前往 https://analytics.google.com/ ，建立或選取 GA4 資源，新增「網頁」資料串流，網站網址設定為 `https://skytical.tech`。
2. 在資料串流詳細資料複製測量 ID（格式 `G-XXXXXXXXXX`；**不要**使用他人的 ID）。
3. 到本儲存庫 Settings → Secrets and variables → Actions → **Variables**，建立 `SKYTICAL_GA4_MEASUREMENT_ID`，填入上述公開測量 ID。
4. 手動執行 `hourly-update` workflow（或等待下一次自動重建），確保所有文章都含 GA4 程式碼。本站的 `daily-briefing`、`manual-article-deploy` 建站也會沿用同一變數。
5. 在 GA4 即時報表打開網站確認有測試造訪。資料收集開始前的歷史 Facebook 點擊**不能補回**。

## Facebook 社團導流

在每篇 SKYTICAL 新聞內按「複製 Facebook 推廣連結」，貼進社團。連結自動附加：

- `utm_source=facebook`
- `utm_medium=social`
- `utm_campaign=skytical_aviation_news`
- `utm_content=<新聞文章 ID>`

進入 GA4「報表 → 客戶開發 → 流量開發」或「探索」，依工作階段來源／媒介、活動與手動廣告素材（依介面版本名稱不同）觀察 Facebook 導流。若讀者分享了未標記的連結，GA4 可能仍識別 Facebook 來源，但無法歸屬到特定推廣活動；若讀者的瀏覽器阻擋追蹤，數字也可能低估。

## 隱私與限制

GA4 使用 Google Analytics 官方標籤，不啟用 Google Signals 或廣告個人化訊號。網站仍須遵守適用的隱私、Cookie 與告知規範；這兩項程式設定本身**不等於**完整的同意管理機制。程式不會將 Measurement ID、UTM 或其他查詢參數寫入 canonical、hreflang 或網站地圖。
