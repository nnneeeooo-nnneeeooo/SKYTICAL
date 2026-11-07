# SKYTICAL 私人流量儀表板

## Google 代管的持續登入

`apps/traffic-session/` 提供 Google Apps Script 後端。Google 在伺服器端保留及延續授權，瀏覽器透過 `google.script.run` 查詢報表；Google 存取權杖不會傳到前端，也不需要儲存用戶端密鑰。必須部署為 **以部署者身分執行（USER_DEPLOYING）／僅限自己（MYSELF）**，不得選擇所有人或匿名存取。

部署時使用該目錄的 `Code.gs` 與 `appsscript.json`，在指令碼屬性設定既有的 `GA4_PROPERTY_ID`。權限限定為 GA4 唯讀與讀取本站固定 UI 位址所需的外部連線；不包含 Drive、Gmail 或寫入 Analytics 的權限。Analytics Data 進階服務由 manifest 啟用。首次需完成 Google 授權；之後可持續使用，但 Google 帳號登出、權限撤銷或組織政策要求重新驗證時仍需登入。

確認部署的存取權為僅限自己、實際報表可讀取，以及重新開啟不再顯示應用程式授權畫面後，將正式 `/exec` 網址設定為 repository Actions variable `SKYTICAL_TRAFFIC_APP_URL`。建站只接受 `https://script.google.com/macros/s/<部署ID>/exec` 格式，原私人入口會自動開啟 Google 保護的版本；無效或未設定時保留以下瀏覽器 OAuth 備用路徑。hourly、briefing 與 manual-article-deploy 都會帶入這項設定，避免後續部署恢復舊入口。

後端從本站的 `assets/traffic-dashboard-app.html` 取得共用 UI，後續介面更新可沿用一般 GitHub Pages 部署。該資產只有介面，不包含 GA4 資源 ID、報表資料或權杖；從公開網址直接開啟無法取得私人報表。報表後端僅接受固定 GA4 資源與受限的唯讀指標、維度、來源篩選及最多 366 天的日期範圍。

以下為未啟用 Google 代管後端時的備用連線方式；瀏覽器 Token Client 不具跨天自動更新授權的能力。備用流程已移除每次強制 `prompt=consent` 的行為，讓既有 Google 授權可依官方流程重用。

原本私人補稿臺網址（\`/m/<私人網址權杖>/\`）現在提供 GA4 流量儀表板；舊補稿頁保留在同一網址下的 \`draft/\`。網站由 GitHub Pages 靜態託管，沒有私有伺服器，因此報表必須使用 Google OAuth 認證，**網址本身不能當作登入防護**。

## 初次連接（網站擁有者執行一次）

1. 在 [Google Analytics](https://analytics.google.com/) 的 SKYTICAL 資源，進入 **管理 → 資源詳細資料**，記下數字型的 **資源 ID / Property ID**。它不同於網站追蹤用的 \`G-J45CLL0ZVY\`。
2. 前往 [Google Cloud Console](https://console.cloud.google.com/) 建立或選擇自己的專案。
3. 到 **API 和服務 → 程式庫** 啟用 **Google Analytics Data API**。
4. 設定 **Google Auth Platform / OAuth 同意畫面**，應用程式採 External（若為一般私人 Gmail）；開發測試狀態時將自己的 Google 帳號加入 **Test users／測試使用者**。OAuth 權限範圍為 \`https://www.googleapis.com/auth/analytics.readonly\`，不需要編輯權限。
5. 建立 **OAuth 2.0 Client ID**，類型選 **Web application／網頁應用程式**。**Authorized JavaScript origins** 加入 \`https://skytical.tech\`（只有 origin，無路徑及斜線）。本站使用 Google Identity Services 的彈出視窗 Token Client，不需要另填重新導向 URI。
6. 開啟原本的私人補稿臺網址，在儀表板填入數字 **Property ID** 和 Google Cloud 的 **OAuth Client ID**，點選「使用 Google 帳號連接」，使用具有 SKYTICAL GA4 資源檢視權限的 Google 帳號授權。首次設定值只會記在目前瀏覽器的 localStorage。OAuth 存取權杖不會寫入 localStorage、公開網站或 GitHub。
7. 成功授權後自動顯示 7 天流量；可切換 28 天與手動更新。頁面開啟時每 10 分鐘更新一次。瀏覽器關閉期間 GA4 本身照常追蹤，但此儀表板不會在背景持續向 Google 查詢。

## 資料來源與解釋

- 活躍使用者：\`activeUsers\`；工作階段：\`sessions\`；頁面瀏覽：\`screenPageViews\`；互動率：\`engagementRate\`
- Facebook 導流：\`sessionSource\` 來源符合 Facebook／FB 的工作階段，不等於 Facebook 貼文按讚數，也無法追溯安裝 GA4 前的訪客。
- 每日趨勢依日期統計 \`sessions\`；來源排行依 \`sessionSourceMedium\`；熱門文章依 \`pagePath\` 的瀏覽量。頁面包含當日資料，GA4 可能延遲處理。
- 所有查詢都是登入使用者的瀏覽器直連 [GA4 Data API](https://developers.google.com/analytics/devguides/reporting/data/v1) 的 \`runReport\`，資料不會寫成可公開讀取的 JSON。靜態 HTML/CSS/JS 仍然是公開的，僅報表資料由 Google Analytics 權限保護。

## 故障排除

- \`origin_mismatch\`：檢查 Google Cloud OAuth 網頁用戶端的 Authorized JavaScript origins 是否為 \`https://skytical.tech\`。
- \`403 PERMISSION_DENIED\`：確認 Google Cloud 已啟用 Data API、登入帳號能檢視 GA4 資源，以及數字 Property ID 正確。
- 應用程式尚未驗證：Google Cloud 同意畫面設定為測試模式，並將自己加入測試使用者。勿為了繞過限制開放給所有訪客。
- 完全沒有資料：GA4 追蹤標籤是否已成功安裝、是否有新訪客，以及資料是否仍在處理。歷史流量無法補回。
- 此頁只用於讀取；**不要**在前端、儲存庫或網址加入 Google API secret、service account JSON、access token。
