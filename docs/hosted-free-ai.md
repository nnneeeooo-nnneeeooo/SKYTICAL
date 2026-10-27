# Groq 與 Cloudflare Workers AI

兩條路由加入既有自動撰稿備援鏈，位於 OpenAI 最終備援之前。未設定憑證時自動略過。
Groq 使用 GPT-OSS 120B，Workers AI 使用 Qwen3 30B A3B；所有既有來源證據、品質驗證與免費路由固定來源測試仍適用。
只有通過 `free_provider_probe` 的路由能進入自動撰稿。每日額度耗盡會停用該服務於本次執行；Groq 的短暫分鐘限制依下述方式處理。

## 設定

到 https://github.com/nnneeeooo-nnneeeooo/SKYTICAL/settings/secrets/actions 新增：

- `GROQ_API_KEY`：https://console.groq.com/keys
- `CLOUDFLARE_ACCOUNT_ID`：Cloudflare dashboard 的 32 位十六進位 Account ID。
- `CLOUDFLARE_API_TOKEN`：限目標帳號，具 Account → Workers AI → Read 權限的 Token。

請勿將憑證放入 repository、前端或文章。無須部署額外 Worker，管線直接使用 Workers AI API。
設定後可手動執行 Actions 的 `free-model-validation`，指定 `provider_order` 為
`groq:openai/gpt-oss-120b,cloudflare:@cf/qwen/qwen3-30b-a3b-fp8` 可只驗證新服務；
留空則測試全部免費路由。檢查 provider probe artifact；下一次 hourly 會重新驗證。
手動工作臺同樣提供這兩個模型，模型覆寫使用 `AVWIRE_GROQ_MODEL` 與 `AVWIRE_CLOUDFLARE_MODEL`。

## 免費額度

免費額度取決於帳號方案，並非無限使用。Cloudflare 請使用 Workers Free；Workers Paid 超額可能計費。
本整合不升級方案、不購買額度。Groq 的免費方案依模型套用速率與每日上限。
目前 token 與 HTTP 用量沿用既有帳本；未設定牌價的模型不捏造成本。

## 介接參考

- https://console.groq.com/docs/api-reference
- https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
- https://developers.cloudflare.com/workers-ai/get-started/rest-api/
- https://developers.cloudflare.com/workers-ai/platform/pricing/

實作前比較 groq/groq-python（Apache-2.0、官方 Python SDK）、cloudflare/cloudflare-python
（Apache-2.0、官方通用 SDK）及 BerriAI/litellm（MIT、跨服務 gateway）。前兩者適合原生 SDK，
LiteLLM 適合大型路由管理；本專案已有 requests adapter、用量與品質閘門，故沿用現有架構、
不增加依賴、不複製第三方程式碼。三者均有近期維護紀錄。

2026-10-25 實測：Groq Llama 3.3 為 Enterprise 模型、帳號 catalog 不提供，改用正式 GPT-OSS 120B。
Workers AI 憑證已確認可連線；補強既有文章長度契約提示，品質與來源證據閘門維持不變。
Workers AI 的 Llama 兩次測試皆未達短訊門檻，改用多語系 Qwen3。
Groq 重試保留完整來源與驗證回饋、略去舊稿，避免超過免費帳號每次請求大小限制。

## 每分鐘速率限制與原生輸出

Groq GPT-OSS 路由以原生 strict JSON Schema 傳送完整資料契約，避免提示詞內重複附上 schema。
回應仍經過原有引文、事實、實體、字數及發布檢查；不自動補造或刪改模型的證據。
明確的 TPM／RPM HTTP 429 且 Retry-After 在 60 秒內時，最多等待後重送一次。
每日／信用額度耗盡、缺少有效 Retry-After 或過長等待不重送；每次 HTTP 呼叫都獨立計數。
持續的每分鐘限制只冷卻該路由一分鐘，不當成六小時的額度耗盡。
Workers AI 在來源與重試回饋之後另附發布檢查提示，區分文章日期與發布時間，
要求重寫完整內文並自行檢查雙語篇幅；原始來源、資料契約與所有發布閘門仍保留。

實際驗證結果：Groq GPT-OSS 120B 已通過同一公開來源的完整發布檢查（Actions run 40184741052）；
2026-10-27 Workers AI Qwen3 30B A3B 第一稿即通過（Actions run 40463490818）。
評估過的 GLM-4.7-Flash 未通過引文核驗，維持 Qwen3 預設設定。
