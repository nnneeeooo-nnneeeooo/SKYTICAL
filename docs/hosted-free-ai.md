# Groq 與 Cloudflare Workers AI

兩條路由加入既有自動撰稿備援鏈，位於 OpenAI 最終備援之前。未設定憑證時自動略過。
使用 Llama 3.3 70B；所有既有來源證據、品質驗證與免費路由固定來源測試仍適用。
只有通過 `free_provider_probe` 的路由能進入自動撰稿，HTTP 429 會停用該服務於本次執行。

## 設定

到 https://github.com/nnneeeooo-nnneeeooo/SKYTICAL/settings/secrets/actions 新增：

- `GROQ_API_KEY`：https://console.groq.com/keys
- `CLOUDFLARE_ACCOUNT_ID`：Cloudflare dashboard 的 32 位十六進位 Account ID。
- `CLOUDFLARE_API_TOKEN`：限目標帳號，具 Account → Workers AI → Read 權限的 Token。

請勿將憑證放入 repository、前端或文章。無須部署額外 Worker，管線直接使用 Workers AI API。
設定後可手動執行 Actions 的 `free-model-validation`，檢查 provider probe artifact；下一次 hourly 會重新驗證。
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
