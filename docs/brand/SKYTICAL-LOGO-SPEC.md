# SKYTICAL Logo 規格與重現方式

本文件定義 SKYTICAL 網站的唯一 Logo 母版、色票、裁切方式與衍生資產。未來更新 Logo 時，必須以 `SKYTICAL-master.svg` 為唯一來源，禁止重新描圖、替換字型或手動調整各個輸出檔。

## 品牌內容

- 主字標：`SKYTICΛL`
- 自訂字元：倒 V／希臘 Lambda `Λ`，不可改成一般字母 `A`
- 標語：`SKYLINE TO AVIATION NEWS`
- 構圖：左側三層掠翼，右側主字標，標語置於主字標下方
- 背景：正式 Logo 必須透明；`#F3F2F2` 僅可用於預覽與社群分享圖

## 標準色票

| 用途 | 色號 | 名稱 |
| --- | --- | --- |
| 機翼上層 | `#EC3013` | Aviation Warning Red |
| 機翼中層 | `#F2643C` | Coral Orange |
| 機翼下層 | `#F2A23A` | Sunrise Gold |
| 主字標 | `#48515C` | Titanium Grey |
| 標語 | `#75808C` | Light Slate Grey |
| 預覽／社群背景 | `#F3F2F2` | Preview Grey |

## 唯一母版

- 檔案：`docs/brand/SKYTICAL-master.svg`
- 原始畫布：`2000 × 2000`
- 原始 `viewBox`：`0 0 1500 1499.999933`
- SHA-256：`53ccee38ecb372a446ebd89737070852e0d8876b04af7efdb1709e78d8553621`
- 來源：2026-08-11 由 Canva 匯出的使用者核准版本

母版文字已轉成 SVG 路徑，不依賴外部字型。Canva 將機翼圖層以內嵌 PNG 儲存在 SVG 中，因此這份檔案雖然是 SVG 容器，機翼本身不是純向量；邊緣抗鋸齒像素可能不是單一標準色。重現時應保留內嵌影像，不得重新取樣、描圖或套用濾鏡。

## 網站衍生資產

| 檔案 | 尺寸／裁切 | 用途 |
| --- | --- | --- |
| `static/skytical-logo.svg` | `1000 × 220`；`viewBox="250 660 1000 220"` | 頁首與頁尾橫式 Logo |
| `static/skytical-mark.svg` | `220 × 220`；`viewBox="250 650 250 220"` | favicon 與結構化資料 Logo |
| `static/skytical-social.png` | `1200 × 630`，Logo 為 `1000 × 220` 並置中 | Open Graph／X 分享圖 |

目前核准輸出的 SHA-256：

- `static/skytical-logo.svg`：`58a11ba2c4d10551e59683056dc5383f137eeb03228be8539fd46f4d7559325a`
- `static/skytical-mark.svg`：`484c4e0efd1d7b899928f9cf77988f6c06278e006b981c3992bb0bcd259b7dc5`
- `static/skytical-social.png`：`e0003ccba52f1a4210e9ce6be5704a7f2d83ff256984f8793044d0b9f223fcec`

橫式 Logo 與翼標的產生規則只有兩項：

1. 從母版移除 `#FFFFFF` 與 `#F3F2F2` 的兩個全畫布 `<rect>`，使背景透明。
2. 只修改根 `<svg>` 的輸出尺寸與 `viewBox`，不得修改任何 Logo 圖層、路徑、遮罩、位置或比例。

社群分享圖使用 `#F3F2F2` 的 `1200 × 630` 畫布，將透明橫式 Logo 以 `1000 × 220` 尺寸置於 `(100, 205)`。

## 驗收標準

- `SKYTICΛL` 與標語拼字完全一致，`Λ` 不得變成 `A`。
- 三層機翼順序固定為紅、橘、金；不得反轉、混色或套用漸層、陰影與濾鏡。
- 頁首、頁尾、favicon、結構化資料與社群分享圖均來自同一母版。
- 橫式與翼標 SVG 背景透明，不含白色或灰色背景矩形。
- 桌機與手機版均維持原有容器尺寸，不因母版的方形畫布產生額外空白。
- 母版 SHA-256 必須與本文件相同；若不同，應視為新的品牌版本並同步更新本文件、衍生資產與快取版本。
