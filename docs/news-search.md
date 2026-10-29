# 模型新聞搜尋

一般撰稿仍只讀管線提供的來源。新 `news_search.py` 沿用快報的 OpenAI Responses web_search 找候選連結，再由管線獨立擷取核准網站原文；搜尋摘要與模型日期不當成文章證據。

- hourly 啟用 `NEWS_WEB_SEARCH=true`，沿用 `OPENAI_API` 與私密 `OPENAI_MODEL_ID`。公開顯示名稱維持 GPT 6。
- 每個已持久化搜尋窗口至少間隔 6 小時；單輪最多 4 次搜尋工具呼叫、8 個候選原文頁。失敗也保留下次嘗試時間。額度依賴 `data/news-search.json` 成功提交；提交失敗可能造成下輪重試，這是頻率控制而非帳戶美元硬上限。
- 僅接受既有 fulltext 核准主機、HTTPS、robots 允許、無轉址的頁面。原文需含 h1、至少 200 字元正文，以及有時區、近 24 小時的文章發布／更新 metadata；不以模型回傳日期代替。
- 抓不到原文或時間不明就略過。搜尋失敗不阻斷既有來源。候選新聞進入原有去重、航空範圍、逐字引文、篇幅與發布核驗，不直接發布搜尋摘要。
- 原文可保留到 24 小時，後續搜尋無結果時不立即抹除尚未處理的有效候選。
- 原有快報搜尋與撰稿仍另外計費；新增 33 美元額度不代表取消上限或保證可用多久。既有 usage 帳本記錄搜尋請求的 token；搜尋工具費仍需以 OpenAI 帳務為準，不捏造成本。

參考：https://developers.openai.com/api/docs/guides/tools-web-search
