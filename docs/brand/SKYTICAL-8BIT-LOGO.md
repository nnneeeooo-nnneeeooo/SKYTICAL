# SKYTICAL 8-bit Logo

此版本依 2026-10-19 的使用者要求製作，供 8-bit 隱藏主題使用。於頁尾「資料來源」點擊 `8-bit`，重新整理後即可選擇像素主題；解鎖與主題儲存在同一瀏覽器中。

## 品牌保留項目

- 以 `SKYTICAL-master.svg` 內嵌的翼形與遮罩為來源，將可視範圍轉為 `40 × 28` 像素格；外圍保留 2 格透明留白，翼標畫布為 `44 × 32`。
- 保留原有掠翼輪廓及紅、橘、金的上下順序，統一使用品牌色 `#EC3013`、`#F2643C`、`#F2A23A`。
- 主字標固定為 **SKYTICΛL**。第七個字元是倒 V／希臘 Lambda `Λ`（U+039B），無橫槓，不可使用一般字母 A。
- 標語仍為 `SKYLINE TO AVIATION NEWS`。標語中的 `AVIATION` 使用正常的 A。
- 字標與標語採自含式像素向量格，不依賴外部字型。SVG 與 PNG 都是透明背景，不加漸層、陰影、濾鏡或背景板。

## 可直接調用的資產

| 檔案 | 尺寸 | 用途 |
| --- | --- | --- |
| `static/skytical-logo-8bit.svg` | 212 × 48 | 淺底橫式 Logo，主字標與標語維持正式灰色色票 |
| `static/skytical-logo-8bit-dark.svg` | 212 × 48 | 深底橫式 Logo，米白字標與淺藍灰標語；翼形三色維持原樣 |
| `static/skytical-mark-8bit.svg` | 44 × 32 | 獨立翼標，供圖示或 favicon 調用 |
| `static/skytical-logo-8bit.png` | 848 × 192 | 淺底版透明 PNG，4 倍整數放大 |
| `static/skytical-logo-8bit-dark.png` | 848 × 192 | 深底版透明 PNG，4 倍整數放大 |
| `static/skytical-mark-8bit.png` | 176 × 128 | 翼標透明 PNG，4 倍整數放大 |

網站建置時，`static/` 資產會複製至 `/assets/`。像素主題的頁首、頁尾使用深底版，favicon 使用獨立翼標；亮／暗主題仍使用原版 Logo。深底版的範例：

```html
<img src="/assets/skytical-logo-8bit-dark.svg"
     alt="SKYTICΛL — SKYLINE TO AVIATION NEWS"
     width="212" height="48">
```

優先使用 SVG，保留長寬比；盡量以整數倍尺寸呈現。PNG 使用整數倍縮放及 `image-rendering: pixelated`，避免柔化像素邊緣。

## 像素母版與重現方式

`docs/brand/SKYTICAL-8BIT-master.json` 保存翼形每一格的顏色、手工像素字形、精確拼字，以及來源母版的 SHA-256。這是像素版的重建資料，不取代正式品牌母版。

2026-10-19 的視覺平衡修正記錄於 `lockup`：翼標原點由 `(0, 8)` 調整至 `(0, 4)`，字標與標語由 `x=58` 左移至 `x=50`，畫布寬度由 `220` 收至 `212`。紅色翼標與主字標頂端同為 `y=6`，水平對齊；兩者留白由 `16` 格縮至 `8` 格。獨立翼標不受橫式排版調整影響。

在 repository 根目錄執行：

```powershell
python docs/brand/generate_8bit_logo.py
```

產生器只使用 Python 標準函式庫，不需要安裝圖片套件、字型、SVG 轉檔程式，也不連線網路。SVG 僅含整數格點矩形；PNG 由同一組矩形以 4 倍整數比例輸出。

修改像素版時，先編輯 JSON，再重新產生六個輸出檔。勿個別修改輸出檔，勿改動 `SKYTICAL-master.svg` 或原有正式資產。發布前檢查倒 V 無橫槓、翼形色序、透明背景與深淺底對比。

## 主題字型與授權

像素主題使用 [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font/releases/tag/2026.10.16) 的 12px 比例字寬 `zh_tw` 版本，對應臺灣繁體字形。字型以 `static/fusion-pixel-tw-v2026-10-16.woff2` 隨站提供，授權及上游字型聲明保存於 `static/fusion-pixel-LICENSE.txt`；採 SIL Open Font License 1.1，不依賴外部字型 CDN。

樣式位於 `static/pixel.css`；網站使用者的主題鍵沿用 `avwire-theme`，解鎖鍵為 `skytical-8bit-unlocked`。無法使用 localStorage 時，僅於當前分頁暫時解鎖並顯示說明，不要求會失去解鎖狀態的重新整理。
