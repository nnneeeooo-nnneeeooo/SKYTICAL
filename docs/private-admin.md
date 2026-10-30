# 私人管理版

正式站維持原樣；私人入口啟用此分頁的管理模式，再返回原生網站網址。
新聞直接在 /news/<id>/（英文為 /en/news/<id>/）就地編輯，不使用 iframe 或另開編輯頁。
沒有帳密登入，持有管理網址的人能開啟編輯介面；發布仍由 GitHub 驗證 PAT。

## 啟用與使用

1. repository Actions Secret `ADMIN_KEY` 設為至少 32 字元的高熵亂數。
2. 完成建站後，在瀏覽器開啟 `https://skytical.tech/admin/#<ADMIN_KEY>`。
   把 `<ADMIN_KEY>` 換成自行保存的值；不要貼到 issue、PR 或聊天。
   瀏覽器會清除網址片段，以 SHA-256 衍生的私人入口啟用 sessionStorage 中的管理模式，再返回原站首頁。
   可收藏帶片段的私人入口；按「結束管理」停用此分頁的管理模式。
   同一瀏覽器仍開著管理分頁時，右鍵或中鍵開啟的新聞新分頁會透過同來源 BroadcastChannel 延續模式，網址保持原生新聞網址。
   模式不寫入 localStorage；沒有管理分頁回應時，新分頁維持普通網站。
   「結束管理」會讓目前分頁拒絕再次自動加入；重新使用私人入口可再次啟用。
3. 「發布連線」設定 repository 管理員的 fine-grained PAT，只授權本 repository 的 Contents 讀寫。
   若分支規則禁止直接寫入 main，GitHub 會拒絕發布，不會繞過規則。
4. 在原生新聞網址直接編輯，工具列切換「文字」或「圖片」。游標移入可編輯內容會出現半透明框，點擊修改。
   Enter 儲存草稿，Shift+Enter 換行；圖片游標移入時可上傳配圖，再直接修改圖片下方來源文字。
   修改自動加密儲存為此瀏覽器的草稿，包含尚未上傳的圖片；下次開啟同篇文章會還原。
   Ctrl+S（Mac 亦支援 ⌘S）或「儲存並送出」開啟變更確認頁，確認後才發布。

PAT 以管理網址衍生的 AES-GCM 金鑰加密儲存在 localStorage；換瀏覽器需重新設定。
這不等同帳號驗證，也無法防禦同來源惡意程式。按「清除連線」移除保存的憑證。
管理入口不在公開選單或 sitemap，標記 noindex 與 no-referrer，robots 排除 /admin/。
原始 ADMIN_KEY 不寫入產物、日誌或 repository；變更 Secret 後須重新部署才撤換舊入口。
金鑰不足 32 字元或未設定時，不產生管理頁面。

## 編輯與發布契約

- 保留文章 ID、來源、原始 writer 與未編輯欄位；顯示模型署名使用 writerModels。
- 時間輸入固定臺北時間；儲存 UTC。publishedUtc 和 sortUtc 可分別編輯。
- 發布增加 revision、updatedUtc，設 editorialLocked 和 editorialImageLocked。
  前者沿用自動撰稿保護，後者防止圖片自動補回或替換人工選圖。
- 人工版本同時寫入獨立的 data/editorial-overrides/，建站與自動撰稿讀取時優先採用。
  即使先前啟動的自動流程稍後提交舊批次，也不會讓正式網站退回舊文章。
- 圖片在瀏覽器解碼、縮至最長 2400 px 並轉 JPEG；與文章及部署觸發檔在同一次 Git commit 發布。
- 每次提交以最新 main 讀取批次，檢查該篇是否改變；其他文章修改會保留。
  ref 更新禁止 force，分支競爭最多重試三次；文章衝突須重新載入。
- 草稿儲存在瀏覽器 localStorage，並以管理網址衍生金鑰加密；不是雲端草稿。
  空間不足時明確提示失敗，未保存或發布中關頁會提醒。捨棄草稿需要確認。
  正式文章在草稿期間被更新時，保留草稿並拒絕覆寫，讓管理員先取回文字再重新編輯。
- 提交後輪詢正式文章的 modified_time，確認本次更新已上線；逾時保留 commit，提示檢查 Actions。

日後可用帳密／OAuth 後端替換 static/admin.js 的 transport 與憑證保存層，
沿用 static/admin-core.js 的內容更新契約與編輯表單；不用複製原網站版型。
