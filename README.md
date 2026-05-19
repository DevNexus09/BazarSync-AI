# BazarSync-AI
A Bangla-first AI commerce OS for marketplace sellers. Monitors competitor prices, promotions, and stockouts in real-time, delivering margin-safe optimization via a web dashboard and urgent WhatsApp alerts. 

## Security note
The frontend currently stores JWTs in `localStorage`, which is vulnerable to token theft if an XSS occurs. For production deployments, prefer httpOnly cookies (or another mitigated storage strategy) and enforce a strong CSP + input sanitization to reduce XSS risk.

Database bootstrap helpers run only when `DB_BOOTSTRAP_ON_STARTUP` is enabled (defaults to `true` in development and `false` otherwise). Use migrations for predictable schema changes in multi-instance environments.
