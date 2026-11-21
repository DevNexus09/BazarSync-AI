# Comprehensive demo seed report

- As of: 2026-11-21
- Seller: `6bbb309a-1795-498d-88d1-d546bd5b1ebc`
- Products: 15

## Observed totals

- seller_email: demo1@gmail.com
- sales_date_start: 2026-07-24
- sales_date_end: 2026-11-20
- sales_records: 1161
- valid_sales_records: 1146
- excluded_sales_records: 15
- units_sold: 2360
- historical_revenue_bdt: 2392878.44
- inventory_snapshots: 675
- stock_receipts: 45
- competitors: 89
- completed_scrape_runs: 70
- competitor_snapshots: 248
- competitor_events: 116
- rankings: 248
- market_opportunities: 45
- sales_velocity: 76
- stockout_predictions: 76
- reorder_recommendations: 76
- inventory_risks: 76
- aging_snapshots: 91
- dead_stock_assessments: 76
- dead_stock_recovery: 76
- capital_recovery: 76
- elasticity_estimates: 75
- seller_price_history: 135
- promotion_plans: 4
- active_promotions: 1
- completed_promotions: 3
- promotion_results: 3
- pricing_analytics: 73
- dynamic_pricing: 72
- generic_recommendations: 2
- recommendation_jobs: 0
- completed_recommendation_jobs: 0
- alerts: 0
- telegram_inventory_alerts: 15
- rag_documents: 3229
- rag_chunks: 3229
- rag_chunks_embedded: 0
- rag_chunks_pending: 3229
- copilot_conversations: 0
- copilot_messages: 0
- copilot_tool_calls: 0
- copilot_action_proposals: 0
- rag_query_logs: 0
- coverage_distribution: {'COMPLETE': 14, 'PARTIAL': 0, 'UNKNOWN': 1, 'FAILED': 0}
- event_distribution: {'PRICE_DROP': 15, 'PRICE_RISE': 15, 'OUT_OF_STOCK': 15, 'BACK_IN_STOCK': 15, 'NEW_COMPETITOR': 41, 'COMPETITOR_REMOVED': 15}
- pricing_action_distribution: {'PRICE_LOWER': 5, 'PRICE_RAISE': 54, 'HOLD': 13}
- pricing_status_distribution: {'OPEN': 1, 'ACKNOWLEDGED': 5, 'DISMISSED': 5, 'EXPIRED': 0, 'SUPERSEDED': 60, 'INSUFFICIENT_DATA': 1}
- inventory_risk_distribution: {'LOW': 14, 'MEDIUM': 8, 'HIGH': 3, 'CRITICAL': 42}
- generic_recommendation_action_distribution: {'LOWER': 0, 'RAISE': 0, 'HOLD': 2, 'REORDER': 0}
- recommendation_job_status_distribution: {'PENDING': 0, 'RUNNING': 0, 'COMPLETED': 0, 'FAILED': 0}
- margin_guard_rejections: {'BELOW_ABSOLUTE_MINIMUM': 13, 'ABOVE_ABSOLUTE_MAXIMUM': 2}

## Scenario coverage

| Product | Scenario | Valid sales | Inventory | Competitors | Risk | Reorder | Pricing | Recommendation | RAG documents | RAG status |
|---|---|---:|---:|---:|---|---|---|---|---:|---|
| P01 Black Casual Slip-On Shoe For Men | healthy_strong_sales | 120 | 180 | 4 | LOW | HOLD | PRICE_RAISE | - | 255 | PENDING |
| P02 Lex Loafer in Brown for Men | healthy_missing_fee_evidence | 64 | 130 | 4 | LOW | HOLD | HOLD | - | 198 | PENDING |
| P03 NORTH STAR FLORA Kids' Sneakers | low_stock_strong_demand | 120 | 9 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 255 | PENDING |
| P04 BATA (MEN) SOFT MENS SANDALS | low_stock_increasing_demand | 91 | 7 | 26 | CRITICAL | REORDER | PRICE_RAISE | HOLD | 252 | PENDING |
| P05 Sandak NIPUN Rubber Sandal for Women by Bata | reorder_incoming_moq_pack | 120 | 10 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 258 | PENDING |
| P06 Black Casual Shoes For Men | critical_near_stockout | 120 | 2 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 255 | PENDING |
| P07 Bata Comfit AURORA Slip-On Sandal for Women | already_out_of_stock | 23 | 0 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 162 | PENDING |
| P08 Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers | slow_promotion_distorted | 51 | 64 | 4 | MEDIUM | REORDER | HOLD | - | 186 | PENDING |
| P09 Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men | no_recent_demand | 29 | 70 | 4 | - | HOLD | PRICE_LOWER | - | 167 | PENDING |
| P10 B. FIRST LEGO SCHOOL SPORTS | aging_capital_recovery | 68 | 82 | 4 | LOW | HOLD | PRICE_RAISE | - | 203 | PENDING |
| P11 BATA (MEN) MERRELS 2.0 MENS SANDALS | competitive_price_lower | 77 | 34 | 4 | MEDIUM | REORDER | PRICE_LOWER | - | 210 | PENDING |
| P12 PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP | excess_stock_price_lower | 57 | 54 | 11 | LOW | HOLD | PRICE_RAISE | HOLD | 215 | PENDING |
| P13 NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER | strong_demand_price_raise | 120 | 26 | 4 | CRITICAL | REORDER | PRICE_RAISE | - | 255 | PENDING |
| P14 COMFIT MOTION V-2 LADIES COMFIT | scarce_market_price_raise | 82 | 20 | 4 | HIGH | REORDER | PRICE_RAISE | - | 217 | PENDING |
| P15 BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER | insufficient_sales_evidence | 4 | 38 | 4 | - | HOLD | HOLD | - | 140 | PENDING |

## Limitations

- External Groq/Copilot and embedding-provider execution was skipped; local RAG documents/chunks were still built where supported.
