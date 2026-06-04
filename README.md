# BazarSync-AI
A Bangla-first AI commerce OS for marketplace sellers. Monitors competitor prices, promotions, and stockouts in real-time, delivering margin-safe optimization via a web dashboard and urgent WhatsApp alerts. 

## Security note
The frontend currently stores JWTs in `localStorage`, which is vulnerable to token theft if an XSS occurs. For production deployments, prefer httpOnly cookies (or another mitigated storage strategy) and enforce a strong CSP + input sanitization to reduce XSS risk.

Database bootstrap helpers run only when `DB_BOOTSTRAP_ON_STARTUP` is enabled (defaults to `true` in development and `false` otherwise). Use migrations for predictable schema changes in multi-instance environments.

## Telegram product intelligence snapshots

**Frontend flow**
1. Open **Telegram Alerts**.
2. In **Product Intelligence Snapshot**, select a product and click **Send Snapshot**.
3. A success toast appears and the realtime activity feed updates.

**API endpoint**
`POST /api/v1/telegram/send-product-snapshot`

**cURL example**
```bash
curl -X POST http://localhost:8000/api/v1/telegram/send-product-snapshot \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"product_id":"UUID"}'
```

**Postman example**
1. Method: `POST`
2. URL: `http://localhost:8000/api/v1/telegram/send-product-snapshot`
3. Headers: `Authorization: Bearer TOKEN`, `Content-Type: application/json`
4. Body (raw JSON): `{"product_id":"UUID"}`

**Expected Telegram output**
```
📊 BazarSync AI Product Intelligence

🛒 Product:
Dove Body Lotion 200ml

💰 Current Price:
৳320

📦 Current Stock:
45 units

🚚 Supplier Lead Time:
5 days

📉 Competitor Median Price:
৳305

⚠️ Price Gap:
-4.7%

🤖 Latest AI Recommendation:
PRICE LOWER

🧠 AI Reason:
Competitor prices are currently lower while 2 sellers are out-of-stock. Lowering price slightly may capture additional demand.

📈 Confidence:
HIGH

⏰ Updated:
2026-05-28 10:45 PM
```

## Telegram bot setup (webhook)

Set these environment variables in production so Telegram can reach your webhook:

1. `TELEGRAM_BOT_TOKEN` — Bot API token from BotFather.
2. `TELEGRAM_WEBHOOK_URL` — Public HTTPS URL ending in `/api/v1/telegram/webhook`.
3. `TELEGRAM_WEBHOOK_SECRET` (optional) — Secret token Telegram will echo in `X-Telegram-Bot-Api-Secret-Token`.

When `TELEGRAM_WEBHOOK_URL` is set, the backend registers the webhook on startup.
