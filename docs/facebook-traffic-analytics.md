# SKYTICAL 免費流量追蹤設定

SKYTICAL 支援免費版 Google Analytics 4（GA4），以及不需帳號或付費的 UTM 活動連結。目前已預設使用 SKYTICAL 官方 GA4 資料串流測量 ID `G-J45CLL0ZVY`；每次網站重建都會自動載入 Google 官方追蹤程式。

## 驗證 GA4 是否正在記錄

1. 正式網站部署後開啟 https://skytical.tech/，再在 Google Analytics 點選 **Test installation** 或查看即時報表。
2. GA4 所有權由網站擁有者的 Google 帳號管理；訪客數據從標籤實際上線之後開始累積，歷史 Facebook 點擊**不能補回**。
3. 若未來更換 GA4 資源，可到儲存庫 Settings → Secrets and variables → Actions → **Variables** 新增或更新 `SKYTICAL_GA4_MEASUREMENT_ID`，其值將覆蓋程式預設值，並適用所有建站 workflow。測量 ID 屬公開識別碼，並非 API 密鑰。

## Facebook 社團導流

為避免讀者在公開文章頁看到營運者使用的推廣工具，新聞頁**不顯示** Facebook 推廣連結按鈕。營運者要在社團分享時，可從文章正式網址自行加上 UTM 查詢參數（若網址已有 `?`，後續參數以 `&` 串接），例如：

`https://skytical.tech/news/文章ID/?utm_source=facebook&utm_medium=social&utm_campaign=skytical_aviation_news&utm_content=文章ID`

依據實際文章 ID 組合，使用以下四個參數：

- `utm_source=facebook`
- `utm_medium=social`
- `utm_campaign=skytical_aviation_news`
- `utm_content=<新聞文章 ID>`

進入 GA4「報表 → 客戶開發 → 流量開發」或「探索」，依工作階段來源／媒介、活動與手動廣告素材（依介面版本名稱不同）觀察 Facebook 導流。若讀者分享了未標記的連結，GA4 可能仍識別 Facebook 來源，但無法歸屬到特定推廣活動；若讀者的瀏覽器阻擋追蹤，數字也可能低估。

## 隱私與限制

GA4 使用 Google Analytics 官方標籤，不啟用 Google Signals 或廣告個人化訊號。網站仍須遵守適用的隱私、Cookie 與告知規範；這兩項程式設定本身**不等於**完整的同意管理機制。程式不會將 Measurement ID、UTM 或其他查詢參數寫入 canonical、hreflang 或網站地圖。
