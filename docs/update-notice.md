# 雙語近期更新通知

中英文公開頁面共用 templates/_update_notice.html、static/update-notice.css 及 static/update-notice.js。原生 dialog 覆蓋在目前頁面上；右上角叉叉、繼續閱讀及 Escape 都只關閉浮窗。內容可在浮窗內捲動，關閉鍵和底部按鈕固定；翼標共用團隊頁的圖像與動畫 CSS，遵守減少動態設定。

## 時間規則

- 以實際顯示時刻起算10,800,000毫秒，未滿三小時不再顯示，滿三小時後下次開頁才顯示。
- 關閉浮窗與更新網站內容不重設計時，不在讀者停留期間計時彈出。
- 中英文、首頁和內頁共用同來源 localStorage key：skytical:update-notice:last-shown:v1。
- 支援 Web Locks 的瀏覽器以來源層級鎖避免多分頁同時顯示；其他瀏覽器使用同步讀寫。
- 原本在頁面快取中的內容重新開啟時也會檢查。其他 dialog 開啟時先等待其關閉。
- 儲存被封鎖時保留目前頁面的記憶，不阻擋閱讀；跨頁／跨裝置／清除網站資料後無法維持該瀏覽器的間隔。

## 內容維護

pipeline/update_notice.py 在每次建站時讀取 config/changelog.json，整理近十四天內、日期與提交SHA有效且具中英文內容的紀錄。產生過程完全離線，不呼叫模型或GitHub API，也不依賴 checkout 是否具有完整Git歷史。

功能更新獨立呈現；同主題只採最新說明，避免舊規則與新規則並列。小調整合併一項；合併項目使用最近更新日期，前端只顯示MM/DD。模型升級須同時符合更新紀錄及目前實際設定，相關能力與補查來源的描述也須有紀錄佐證。其他未識別的新功能沿用原有雙語文字，不自行杜撰效能提升。

紀錄可用選填 notice.importance 設為 major 或 minor，調整是否獨立呈現；不在讀者畫面顯示分類標籤。網站更新仍須同步維護雙語changelog，通知會隨建站更新。

config/station-note.json 分別維護 messages.zh、messages.en，enabled 可隱藏留言。來信地址沿用既有團隊頁公開地址，瀏覽器以安全DOM建立mailto連結，不插入原始HTML。文字中的neo使用翼標紅、橙、金色。static/neo-life.jpg 是使用者核准照片的臉部裁切，約30KB；不發布原始整張照片或本機Demo。

## 檢查

- python tests/test_update_notice.py：雙語對應、來源門檻、同主題去重、日期及正式版型。
- node tests/test_update_notice.js：三小時前1毫秒、三小時整、無效及未來時間戳記。
- python tests/browser/notice_check.py：Chromium實際操作，涵蓋中英文320／390／768／1440px、跨語言／分頁間隔、關閉、捲動、照片、來信連結及減少動態。
- update-notice-browser workflow 會保存畫面與檢查結果；上線後可手動帶入 https://skytical.tech 驗證正式站。
