# Comprehensive demo seed report

- As of: 2026-11-24
- Seller: `0e9494ab-0d90-4e19-870e-df79094b8703`
- Products: 25

## Observed totals

- seller_email: bazardemo@gmail.com
- sales_date_start: 2026-07-27
- sales_date_end: 2026-11-23
- sales_records: 3514
- valid_sales_records: 3340
- excluded_sales_records: 174
- units_sold: 3574
- historical_revenue_bdt: 885087.00
- inventory_snapshots: 1125
- stock_receipts: 50
- competitors: 168
- completed_scrape_runs: 106
- competitor_snapshots: 427
- competitor_events: 193
- rankings: 427
- market_opportunities: 75
- sales_velocity: 25
- stockout_predictions: 25
- reorder_recommendations: 25
- inventory_risks: 25
- aging_snapshots: 25
- dead_stock_assessments: 25
- dead_stock_recovery: 25
- capital_recovery: 25
- elasticity_estimates: 25
- seller_price_history: 225
- promotion_plans: 4
- active_promotions: 1
- completed_promotions: 3
- promotion_results: 3
- pricing_analytics: 25
- dynamic_pricing: 25
- generic_recommendations: 3
- recommendation_jobs: 0
- completed_recommendation_jobs: 0
- alerts: 0
- telegram_inventory_alerts: 19
- rag_documents: 5462
- rag_chunks: 5462
- rag_chunks_embedded: 55
- rag_chunks_pending: 5407
- copilot_conversations: 1
- copilot_messages: 2
- copilot_tool_calls: 1
- copilot_action_proposals: 0
- rag_query_logs: 0
- coverage_distribution: {'COMPLETE': 24, 'PARTIAL': 0, 'UNKNOWN': 1, 'FAILED': 0}
- event_distribution: {'PRICE_DROP': 25, 'PRICE_RISE': 25, 'OUT_OF_STOCK': 25, 'BACK_IN_STOCK': 25, 'NEW_COMPETITOR': 68, 'COMPETITOR_REMOVED': 25}
- pricing_action_distribution: {'PRICE_LOWER': 1, 'PRICE_RAISE': 17, 'HOLD': 7}
- pricing_status_distribution: {'OPEN': 22, 'ACKNOWLEDGED': 1, 'DISMISSED': 1, 'EXPIRED': 0, 'SUPERSEDED': 0, 'INSUFFICIENT_DATA': 1}
- inventory_risk_distribution: {'LOW': 9, 'MEDIUM': 4, 'HIGH': 0, 'CRITICAL': 9}
- generic_recommendation_action_distribution: {'LOWER': 0, 'RAISE': 0, 'HOLD': 3, 'REORDER': 0}
- recommendation_job_status_distribution: {'PENDING': 0, 'RUNNING': 0, 'COMPLETED': 0, 'FAILED': 0}
- margin_guard_rejections: {'BELOW_MINIMUM_SAFE_PRICE': 14, 'BELOW_MINIMUM_MARGIN': 14, 'BELOW_MINIMUM_UNIT_PROFIT': 3, 'BELOW_ABSOLUTE_MINIMUM': 4, 'MISSING_FEE_DATA': 8}

## Scenario coverage

| Product | Scenario | Valid sales | Inventory | Competitors | Risk | Reorder | Pricing | Recommendation | RAG documents | RAG status |
|---|---|---:|---:|---:|---|---|---|---|---:|---|
| P01 Arabic Aura Watch – Carbon Fiber Look Body with Sleek & Modern Design | healthy_strong_sales | 266 | 180 | 26 | LOW | HOLD | PRICE_RAISE | HOLD | 358 | MIXED |
| P02 OLEVS 2872 Stylish Men's Watch – Perfect for Casual and Formal Wear | healthy_missing_fee_evidence | 67 | 130 | 4 | LOW | HOLD | HOLD | - | 145 | MIXED |
| P03 Curren 8301 Men's Watch – Stylish and Durable | low_stock_strong_demand | 265 | 9 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 353 | MIXED |
| P04 OLEVS Stainless Steel Watch for Men – Model 9931, Elegant & Robust | low_stock_increasing_demand | 118 | 7 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 201 | MIXED |
| P05 POEDAGAR 930 Men's Stainless Steel Watch – Water Resistant, Luminous Display, Date & Day Feature | reorder_incoming_moq_pack | 260 | 10 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 350 | MIXED |
| P06 Children’s Sports Wristwatch – Lightweight & Easy to Use | critical_near_stockout | 264 | 2 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 355 | MIXED |
| P07 Couple Combo Watch Set – CRRJU 5003 Silver Blue Dial Men’s Watch with Date + Dior Magnetic Ladies Watch | already_out_of_stock | 43 | 0 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 129 | MIXED |
| P08 Men's Fashion Analog Watch – Classic Design with Quartz Movement | slow_promotion_distorted | 107 | 64 | 28 | MEDIUM | REORDER | HOLD | HOLD | 194 | MIXED |
| P09 Folding Alarm Clock – Silent, Loud Hammer, Glow Hands, Steel Shell – Multicolor | no_recent_demand | 21 | 70 | 4 | - | HOLD | HOLD | - | 102 | MIXED |
| P10 Twin Bell Alarm Clock – Loud Heavy Alarm Clock | aging_capital_recovery | 127 | 82 | 4 | LOW | HOLD | HOLD | - | 211 | MIXED |
| P11 O'levs 6898 Men's Analog Wrist Watch – PU Leather Strap | competitive_price_lower | 133 | 34 | 4 | MEDIUM | REORDER | PRICE_LOWER | - | 213 | MIXED |
| P12 Star Shaped Bell Table Alarm Clock – Retro Twin Bell Design | excess_stock_price_lower | 124 | 54 | 4 | MEDIUM | REORDER | PRICE_RAISE | - | 211 | MIXED |
| P13 Stylish Women's Bracelet-Type Analog Wristwatch - Elegant Design | strong_demand_price_raise | 264 | 26 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 351 | MIXED |
| P14 Curren Model 9081 Ladies Wristwatch – Classic Design | scarce_market_price_raise | 119 | 20 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 205 | MIXED |
| P15 OLEVS Model 1020 Men's Stainless Steel Watch | insufficient_sales_evidence | 4 | 38 | 4 | - | HOLD | HOLD | - | 81 | MIXED |
| P16 Magnetic Wrist Watch for girls and women - Watch For Women - Ladies Watch | steady_budget_seller | 70 | 64 | 4 | LOW | HOLD | PRICE_RAISE | - | 152 | MIXED |
| P17 SKMEI Model 1260 Men's Stainless Steel Watch | rising_demand_healthy | 133 | 45 | 4 | MEDIUM | REORDER | PRICE_RAISE | - | 218 | MIXED |
| P18 Classic Bell Alarm Clock – Apple Shape Desktop Timepiece | seasonal_gift_clock | 66 | 40 | 4 | LOW | HOLD | PRICE_RAISE | - | 144 | MIXED |
| P19 Poedagar 613 Quartz Wristwatch for Men – Stainless Steel, Elegant Design | declining_aged_premium | 122 | 58 | 4 | LOW | HOLD | HOLD | - | 205 | MIXED |
| P20 Men’s Luxury Analog Watch – Premium Design | intermittent_gift_box | 28 | 22 | 26 | LOW | HOLD | PRICE_RAISE | HOLD | 112 | MIXED |
| P21 OLEVS 9931 Women's Fashion Watch – Perfect for Daily Wear | best_seller_price_raise | 264 | 30 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 360 | MIXED |
| P22 Men’s Analog Wrist Watch – Durable and Lightweight | low_stock_reorder_now | 260 | 6 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 352 | MIXED |
| P23 Luxury Watch Model 810 WATCH | healthy_steady_mid_range | 69 | 38 | 4 | LOW | HOLD | PRICE_RAISE | - | 148 | MIXED |
| P24 SKMEI WATCH MODEL 9069 | dead_stock_no_recent_sales | 25 | 72 | 4 | - | HOLD | HOLD | - | 106 | MIXED |
| P25 Men's Casual Waterproof Square Watch with Rubber Strap | new_arrival_rising | 121 | 80 | 4 | LOW | HOLD | PRICE_RAISE | - | 204 | MIXED |
