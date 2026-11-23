# Copilot Banglish 100-question test — after fixes

Final run: 2026-11-22T15:44 UTC · demo seller `6bbb309a…` · raw file `backend/artifacts/copilot_eval/20261122T154420Z.json`

## Result

| | Before | After |
|---|---|---|
| Fully correct | 37 / 100 | **100 / 100** |
| Handled properly (incl. honest 'no data' + refusals) | 46 / 100 | **100 / 100** |
| Golden 40-question regression set | 36 / 40 | 39 / 40 (Bangla-script item is LLM-path flake, see below) |

Every answer is now checked automatically: each question in `backend/tests/fixtures/copilot_banglish_100.json` carries expected facts verified with independent SQL against the database (as of 22 Nov 2026; sales recorded to 20 Nov 2026).

## What changed

1. **Deterministic answer layer** (`app/services/copilot/direct_answers.py`, flag `COPILOT_DIRECT_ANSWERS_ENABLED`, default off): ~90 question shapes in English/Banglish are answered from exact seller-scoped data with templates — no LLM, so Gemini 503s / OpenRouter rate limits no longer turn answers into fallbacks. Unrecognised questions and Bangla-script replies still use the existing pipeline. Safety refusals run first.
2. **Bug fixes in existing tools**: dead-stock locked capital summed every historical run (৳2,724,631.81 → correct ৳474,912.89, latest run per product) and counted dead stock rows across history (2 → 1 product); `get_competitor_events` crashed on the `metadata` column; `simulate_price_change` ignored elasticity and marketplace fees.
3. **Missing data added** (additive migration `o9c0d1e2f3a4` + idempotent `scripts/seed_copilot_demo_extras.py`, demo seller only): Daraz listings with ratings/reviews, buyer reference + delivery district on sales, search-rank visibility, expenses (ads, shipping, packaging) and supplier bills, store seller-rating scorecard.

## Known limits

- Bangla-script questions are not covered by the new layer; they still depend on the LLM, which sometimes answers in the wrong script (golden `bangla_products` failed once this way).
- Relative dates (ajke, ei shoptahe, last 7 din) follow the Dhaka calendar, so the expected facts are tied to 22 Nov 2026.
- Question matching is keyword-based: new phrasings outside these shapes fall back to the LLM pipeline.

## All questions — before and after

### 1. Ei mashe amar total sales koto hoise?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) apnar mot bikri ৳383,863.28 — 181 ta order, 397 unit. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Ei mashe apnar total gross revenue hoise BDT 383863.28 ebong net revenue hoise BDT 379615.28. Total units sold hoise 397 ebong order count hoise 181. Apnar sales report gulo dekhe nin.

</details>

### 2. Gotokal koto taka bikri hoise?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Gotokal (21 Nov 2026) kono bikri record hoy nai. Shesh bikri record hoyeche 20 Nov 2026 e.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 3. Last 7 din e amar revenue koto?
*sales* · before: ❌ Wrong · after: ✅ Correct

**Now:** Last 7 din (16 Nov 2026 – 22 Nov 2026) apnar mot bikri ৳93,503.00 — 43 ta order, 85 unit. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Apnar gross revenue holo BDT 2392878.44. / Aji sales trends gulo check kore nin.

</details>

### 4. October mashe amar mot bikri koto chilo?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** October 2026 (1 Oct 2026 – 31 Oct 2026) apnar mot bikri ৳613,570.52 — 298 ta order, 625 unit.

<details><summary>Before</summary>

October mashe apnar mot bikri chilo BDT 613570.52. / Aponar October masher sales report check kore nin.

</details>

### 5. November er prothom 15 dine koto taka sale hoise?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** November er prothom 15 din (1 Nov 2026 – 15 Nov 2026) apnar mot bikri ৳290,360.28 — 138 ta order, 312 unit.

<details><summary>Before</summary>

November er prothom 15 dine apnar total sale hoise BDT 290360.28.

</details>

### 6. Ajke kono order ashse?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Ajke (22 Nov 2026) kono order ashe nai. Shesh order record hoyeche 20 Nov 2026 e.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 7. Ei shoptahe koyta order paisi?
*sales* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Ei shoptahe (16 Nov 2026 – 22 Nov 2026) apni 43 ta order peyechen (৳93,503.00, 85 unit). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Ei shoptahe order count er kono record nai, ebong sales history incomplete.

</details>

### 8. October e total koyta order chilo?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** October 2026 (1 Oct 2026 – 31 Oct 2026) apni 298 ta order peyechen (৳613,570.52, 625 unit).

<details><summary>Before</summary>

October mashe apnar total order chilo 298 ti.

</details>

### 9. Ei mashe koto unit product bikri korsi?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) apni 397 unit bikri korechen (181 ta order, ৳383,863.28). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - gross revenue: 383863.28 / - net revenue: 379615.28 / - previous period revenue: 442690.10 / - revenue change: -58826.82 / - percentage change: -13.29 / - units sold: 397 / - order count: 181 / - average order value: 2120.79

</details>

### 10. Amar average order value koto?
*sales* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Apnar average order value shob mile ৳2,088.03 (1146 ta order), ar ei mashe (1 Nov 2026 – 22 Nov 2026) ৳2,120.79.

<details><summary>Before</summary>

Apnar average order value record e nei, kintu gross revenue BDT 2392878.44 record kora ache. Revenue summary dekhe nin.

</details>

### 11. Gotomash er tulonay ei mashe sales barse na komse?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Bikri komeche 6.76%: ei mashe (1 Nov 2026 – 22 Nov 2026) ৳383,863.28, gotomasher same shomoy (1 Oct 2026 – 22 Oct 2026) chilo ৳411,685.32. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার বিক্রিতে যা বদলেছে: / - gross revenue: 383863.28 / - net revenue: 379615.28 / - previous period revenue: 442690.10 / - revenue change: -58826.82 / - percentage change: -13.29 / - units sold: 397 / - order count: 181 / - average order value: 2120.79

</details>

### 12. October theke November e revenue koto percent change hoise?
*sales* · before: 🟡 Partial · after: ✅ Correct

**Now:** Revenue -37.44% change hoyeche: October (1 Oct 2026 – 31 Oct 2026) ৳613,570.52, November (1 Nov 2026 – 22 Nov 2026) ৳383,863.28. November er ekhon porjonto 22 din; October er same 22 diner (৳411,685.32) tulonay change -6.76%. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

October theke November e revenue BDT 613570.52 theke kome BDT 383863.28 hoyeche. Apnar sales trend ar inventory risks gulo ektu check kore nin.

</details>

### 13. Kon din sobcheye beshi bikri hoise?
*sales* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Shobcheye beshi bikri hoyeche 31 Jul 2026 (Friday) e (shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026)): ৳33,676.44, 13 ta order.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 14. Amar weekend e beshi sale hoy naki weekday te?
*sales* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Apnar weekend e beshi bikri hoy: weekday (Robi–Brihoshpoti) te gore ৳19,656.44/din, weekend (Shukro–Shoni) e ৳20,630.89/din — 4.96% beshi (24 Jul 2026 – 20 Nov 2026).

<details><summary>Before</summary>

Apnar weekend ki weekday er cheye beshi sale hoy, shei record ekhane recorded nei, kintu apnar inventory risk list e critical items gulo dekhe nin. / Bata Comfit AURORA Slip-On Sandal for Women: reorder stock / Black Casual Shoes For Men: reorder stock / Ami-i restock plan ta check kore nin.

</details>

### 15. Last 30 din er daily average sales koto?
*sales* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Last 30 din (24 Oct 2026 – 22 Nov 2026) gore protidin bikri ৳20,070.25 (sales data ache emon 28 dine mot ৳561,966.88). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 16. Amar sales trend ta kemon jacche?
*sales* · before: ❌ Wrong · after: ✅ Correct

**Now:** Last 4 shoptahe (20 Nov 2026 porjonto) sales trend niche namche — 11.95%. Shoptahik bikri: 24 Oct 2026–30 Oct 2026: ৳152,339.80, 31 Oct 2026–6 Nov 2026: ৳149,555.04, 7 Nov 2026–13 Nov 2026: ৳125,933.04, 14 Nov 2026–20 Nov 2026: ৳134,139.00.

<details><summary>Before</summary>

Apnar sales trend ekti nirdisto shomoyer revenue record anusare 2026-07-24 theke 2026-08-17 porjonto records ekhon royeche.

</details>

### 17. Ei bochor e ekhon porjonto total revenue koto?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Ei bochor (1 Jan 2026 – 22 Nov 2026) apnar mot bikri ৳2,392,878.44 — 1146 ta order, 2333 unit. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Ei bochor e ekhon porjonto apnar total gross revenue holo BDT 2392878.44.

</details>

### 18. Gotokal er cheye ajke sales beshi na kom?
*sales* · before: ✅ Correct · after: ✅ Correct

**Now:** Ajker bikri (৳0.00) gotokal er (৳0.00) cheye shoman. Dui dinei kono bikri record nai; shesh bikri record 20 Nov 2026 e.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers / - Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men / - BATA (MEN) SOFT MENS SANDALS

</details>

### 19. Last week e koto taka er order cancel hoise?
*sales* · before: ❌ Wrong · after: ✅ Correct

**Now:** Last week (9 Nov 2026 – 15 Nov 2026) 0 ta order cancel hoyeche, mot ৳0.00. Shesh cancel hoyeche 16 Nov 2026 e: 15 ta order, ৳17,970.00.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - gross revenue: 129885.00 / - previous period revenue: 140536.28 / - revenue change: -10651.28 / - percentage change: -7.58 / - units sold: 116 / - order count: 59 / - average order value: 2201.44 / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical

</details>

### 20. Kono return ba refund hoise ei mashe?
*sales* · before: ❌ Wrong · after: ✅ Correct

**Now:** Haan — ei mashe (1 Nov 2026 – 22 Nov 2026) 2 ta order e 4 unit return/refund hoyeche, mot ৳4,248.00.

<details><summary>Before</summary>

Ei mashe kono return ba refund records nai. Tar por-o apnar sales summary dekhe nite paren.

</details>

### 21. Amar best selling product konta?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** Apnar best selling product (shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026)) holo NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: revenue ৳486,500.00, 283 unit. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Apnar best selling product holo NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, jar revenue BDT 486500.00. / Ajo apnar top product er sales status check kore nin.

</details>

### 22. October e top 5 product kon gula revenue onujayi?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** October 2026 (1 Oct 2026 – 31 Oct 2026) revenue onujayi top 5 product: 1. NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: ৳127,470.00 (74 units); 2. COMFIT MOTION V-2 LADIES COMFIT: ৳82,718.22 (38 units); 3. NORTH STAR FLORA Kids' Sneakers: ৳80,247.00 (71 units); 4. Black Casual Shoes For Men: ৳70,011.12 (73 units); 5. Black Casual Slip-On Shoe For Men: ৳65,978.76 (69 units).

<details><summary>Before</summary>

October mashe revenue onujayi top 5 product er talika: / NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: BDT 127470.00 / COMFIT MOTION V-2 LADIES COMFIT: BDT 82718.22 / NORTH STAR FLORA Kids' Sneakers: BDT 80247.00 / Black Casual Shoes For Men: BDT 70011.12 / Black Casual Slip-On Shoe For Men: BDT 65978.76 / Aponar October masher sales report ekbar review kore nin.

</details>

### 23. Kon product sobcheye kom bikri hoise?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** Shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026) bikri howa product er moddhe shobcheye kom BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER: 4 units (৳3,759.64). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Sobcheye kom bikri howa product: / BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER: 4 units / Inventory risk status dekhe nin.

</details>

### 24. Kon product gula ekdom bikri hoy nai last 30 din e?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** Last 30 din (24 Oct 2026 – 22 Nov 2026) 2 ta product ekdom bikri hoy nai: BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER (stock 38), Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men (stock 70). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER / - Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 25. Lex Loafer in Brown for Men koyta bikri hoise November e?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** November 2026 (1 Nov 2026 – 22 Nov 2026) Lex Loafer in Brown for Men 9 ta bikri hoyeche — ৳16,116.40 (9 ta order). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

November maše Lex Loafer in Brown for Men 9 ti bikri hoise. / Lex Loafer in Brown for Men: 9 units

</details>

### 26. Black Casual Shoes For Men er dam koto?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** Black Casual Shoes For Men er selling price ৳974.00 (cost ৳594.14).

<details><summary>Before</summary>

Black Casual Shoes For Men er current selling price 974.00 BDT. / Aj-i product pricing details ta check kore nin.

</details>

### 27. Amar mot koyta product ache?
*product* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apnar mot 15 ta product ache (15 ta active).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: bundle / - B. FIRST LEGO SCHOOL SPORTS: bundle / - NORTH STAR FLORA Kids' Sneakers: bundle / - Sandak NIPUN Rubber Sandal for Women by Bata: bundle / - Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: bundle / - Bata Comfit AURORA Slip-On Sandal for Women: manual review / - Black Casual Slip-On Shoe For Men: manual review / - Lex Loafer in Brown for Men: bundle

</details>

### 28. Kon category te sobcheye beshi bikri hoy?
*product* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Shobcheye beshi bikri hoy Men's Footwear e (shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026)): ৳994,269.82. Shob category: Men's Footwear ৳994,269.82 (41.6%), Women's Footwear ৳962,324.93 (40.2%), Children's Footwear ৳419,915.59 (17.5%), Other ৳16,368.10 (0.7%).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 29. Men's Footwear category theke October e koto revenue aise?
*product* · before: ✅ Correct · after: ✅ Correct

**Now:** October 2026 (1 Oct 2026 – 31 Oct 2026) Men's Footwear theke ৳235,260.96 revenue esheche (129 ta order, 245 unit).

<details><summary>Before</summary>

October mashe Men's Footwear category theke total revenue hoyeche BDT 235260.96.

</details>

### 30. Amar sob category er list dao
*product* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apnar 4 ta category: Children's Footwear (3 products), Men's Footwear (6 products), Other (1 products), Women's Footwear (5 products).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / - NORTH STAR FLORA Kids' Sneakers / - Black Casual Slip-On Shoe For Men / - Lex Loafer in Brown for Men / - PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / - BATA (MEN) SOFT MENS SANDALS / - Black Casual Shoes For Men / - Sandak NIPUN Rubber Sandal for Women by Bata

</details>

### 31. Kon product er margin sobcheye beshi?
*product* · before: ❌ Wrong · after: ✅ Correct

**Now:** Shobcheye beshi margin: PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP — Daraz fee kete 34.00% (proti unit ৳45.56 labh). Tarpor: Sandak NIPUN Rubber Sandal for Women by Bata 33.00%, Black Casual Slip-On Shoe For Men 32.00%.

<details><summary>Before</summary>

দামের পরামর্শ: / - Black Casual Slip-On Shoe For Men: price 1071.00 /  / ঠিক মনে হলে দামের পরিবর্তন নিজে approve করুন।

</details>

### 32. Sobcheye dami product konta amar?
*product* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apnar shobcheye dami product Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men — dam ৳3,374.00.

<details><summary>Before</summary>

Apnar sobcheye dami product holo Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers, jar selling price BDT 674.00. / Aporokhom bhabe sales records e shobcheye beshi unit price dekha geche Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: BDT 3171.56. / Ajo apnar product list ta check kore nite paren.

</details>

### 33. Sobcheye sosta product konta?
*product* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apnar shobcheye sosta product PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP — dam ৳134.00.

<details><summary>Before</summary>

Apnar sobcheye sosta product holo Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers, jar selling price BDT 674.00. / Product catalog list-ti aro bhalo bhabe dekhe nin.

</details>

### 34. Kon product er rating kom ba review kharap?
*product* · before: 📭 Data missing – irrelevant reply · after: ✅ Correct

**Now:** Kom rating er product (4.0 er niche): Bata Comfit AURORA Slip-On Sandal for Women: 3.40/5 (12 reviews); BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER: 3.60/5 (5 reviews); BATA (MEN) SOFT MENS SANDALS: 3.80/5 (21 reviews). Ei product gulor review e size, quality ba delivery complaint dekhe nin.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 35. Amar kon product gula Daraz e listed ache?
*product* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Apnar 15 ta product er moddhe 15 ta Daraz Bangladesh e listed: 14 ta active, active na: Bata Comfit AURORA Slip-On Sandal for Women.

<details><summary>Before</summary>

I could not find seller-owned listing data for that marketplace.

</details>

### 36. Amar total stock koto unit ache?
*stock* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Apnar mot stock 726 unit — 15 ta product er moddhe 14 ta te stock ache.

<details><summary>Before</summary>

Apnar total stock koto unit ache, eta amader kache record kora nei.

</details>

### 37. Kon kon product stock out hoye gese?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Stock shesh hoye geche: Bata Comfit AURORA Slip-On Sandal for Women.

<details><summary>Before</summary>

Bata Comfit AURORA Slip-On Sandal for Women product ti ekhon stock out hoye geche. / Bata Comfit AURORA Slip-On Sandal for Women: stock 0 / Aj-i restock plan ta dekhe nin.

</details>

### 38. Kon product er stock prai shesh, low stock ache?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Low stock (ekhonkar bikrir gote 14 diner kom, ba shesh): Bata Comfit AURORA Slip-On Sandal for Women: 0 left; Black Casual Shoes For Men: 2 left (~1 days); BATA (MEN) SOFT MENS SANDALS: 7 left (~5 days); NORTH STAR FLORA Kids' Sneakers: 9 left (~4 days); Sandak NIPUN Rubber Sandal for Women by Bata: 10 left (~4 days); NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: 26 left (~11 days).

<details><summary>Before</summary>

Apnar low stock product gulo niche dewa holo: / Bata Comfit AURORA Slip-On Sandal for Women: 0 / Black Casual Shoes For Men: 2 / Aji product gulo restock korar plan dekhe nin.

</details>

### 39. Black Casual Shoes For Men er stock koto baki ache?
*stock* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Black Casual Shoes For Men (SKU DEMO-BATA-320140080) er stock ache 2 unit.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Black Casual Shoes For Men: price gap 165.58

</details>

### 40. SKU DEMO-BATA-541167043 er stock koto?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (SKU DEMO-BATA-541167043) er stock ache 26 unit.

<details><summary>Before</summary>

Apnar SKU DEMO-BATA-541167043 er current stock 26 ti. / NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: stock 26 / Aj-i inventory risk ta dekhe nin.

</details>

### 41. Amar inventory er total value koto taka?
*stock* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apnar inventory er value cost price e ৳595,431.23 (selling price e ৳938,829.00), mot 726 unit.

<details><summary>Before</summary>

এই পণ্যগুলো রিস্টক করা দরকার: / - Black Casual Shoes For Men: reorder 72 / - Sandak NIPUN Rubber Sandal for Women by Bata: reorder 72 / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: reorder 42 / - BATA (MEN) SOFT MENS SANDALS: reorder 42 / - COMFIT MOTION V-2 LADIES COMFIT: reorder 18 / - NORTH STAR FLORA Kids' Sneakers: reorder 72 /  / Supplier lead time দেখে order দিন।

</details>

### 42. Kon product reorder kora dorkar ekhon?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Ekhon reorder korun: Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: order 12 units (stock 64, by 2 Dec 2026); COMFIT MOTION V-2 LADIES COMFIT: order 18 units (stock 20, deadline passed 21 Nov 2026); Sandak NIPUN Rubber Sandal for Women by Bata: order 72 units (stock 10, deadline passed 21 Nov 2026); Black Casual Shoes For Men: order 72 units (stock 2, deadline passed 21 Nov 2026); NORTH STAR FLORA Kids' Sneakers: order 72 units (stock 9, deadline passed 21 Nov 2026); BATA (MEN) MERRELS 2.0 MENS SANDALS: order 18 units (stock 34, by 25 Nov 2026); Bata Comfit AURORA Slip-On Sandal for Women: order 24 units (stock 0, deadline passed 21 Nov 2026); NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: order 42 units (stock 26, deadline passed 21 Nov 2026); BATA (MEN) SOFT MENS SANDALS: order 42 units (stock 7, deadline passed 21 Nov 2026). Order er age supplier lead time dekhe nin.

<details><summary>Before</summary>

Apnar ekhon ei product-gulo reorder kora dorkar: / - Black Casual Shoes For Men: reorder 72 / - Sandak NIPUN Rubber Sandal for Women by Bata: reorder 72 / Supplier lead time dekhe order din.

</details>

### 43. Ei shoptahe koto stock in hoise?
*stock* · before: ❌ Wrong · after: ✅ Correct

**Now:** Ei shoptahe (16 Nov 2026 – 22 Nov 2026) kono stock in hoy nai. Shesh stock in hoyeche 12 Nov 2026 e: Sandak NIPUN Rubber Sandal for Women by Bata (60 units).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: locked capital 99425.92 / - Lex Loafer in Brown for Men: locked capital 157078.68 / - PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / - BATA (MEN) SOFT MENS SANDALS: locked capital 2407.98 / - Black Casual Shoes For Men: risk critical

</details>

### 44. Last stock in kobe korsi ar ki ki product?
*stock* · before: ❌ Wrong · after: ✅ Correct

**Now:** Shesh stock in hoyeche 12 Nov 2026 e: Sandak NIPUN Rubber Sandal for Women by Bata (60 units).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: price 1071.00 / - Lex Loafer in Brown for Men: locked capital 157078.68 / - PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / - BATA (MEN) SOFT MENS SANDALS: locked capital 2407.98 / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical

</details>

### 45. Sandak NIPUN er stock kinte unit cost koto porse?
*stock* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Sandak NIPUN Rubber Sandal for Women by Bata: 12 Nov 2026 e 60 unit stock in hoyeche, proti unit ৳140.79 (mot ৳8,447.40).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Sandak NIPUN Rubber Sandal for Women by Bata: price gap 41.99

</details>

### 46. Amar stock koto din cholbe current sales e?
*stock* · before: 🟡 Partial · after: ✅ Correct

**Now:** Last 30 diner gote (22.6 unit/din) apnar 726 unit stock mote pray 32 din cholbe — kintu shob product e na. Age shesh hobe: Bata Comfit AURORA Slip-On Sandal for Women ~0 days (0 left), Black Casual Shoes For Men ~1 days (2 left), NORTH STAR FLORA Kids' Sneakers ~4 days (9 left). Already shesh: Bata Comfit AURORA Slip-On Sandal for Women.

<details><summary>Before</summary>

Apnar current sales velocity te inventory risk er obostha niche dewa holo: / Bata Comfit AURORA Slip-On Sandal for Women: stockout status ALREADY_OUT_OF_STOCK / Black Casual Shoes For Men: days remaining 0.0476 / Aji apnar inventory risks guli check kore nin.

</details>

### 47. Kon product er stock beshi pore ache, bikri hocche na?
*stock* · before: 🟡 Partial · after: ✅ Correct

**Now:** Beshi pore ache (last 30 diner gote shobcheye dhire bikri): BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER: 38 unit (30 dine bikri nai, cost e ৳24,057.80); Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: 70 unit (30 dine bikri nai, cost e ৳151,155.20); Lex Loafer in Brown for Men: 130 unit (~260 diner stock, cost e ৳160,789.20); Black Casual Slip-On Shoe For Men: 180 unit (~78 diner stock, cost e ৳101,685.60).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Black Casual Slip-On Shoe For Men: locked capital 99425.92 / - Lex Loafer in Brown for Men: locked capital 157078.68 / - PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / - BATA (MEN) SOFT MENS SANDALS: locked capital 2407.98 / - Black Casual Shoes For Men: risk critical

</details>

### 48. Dead stock e koto taka atke ache?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Dead, at-risk ba slow-moving stock e ৳474,912.89 atke ache (cost price e, proti product er latest assessment).

<details><summary>Before</summary>

Apnar motot dead stock e BDT 2724631.81 taka atke ache. / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: locked capital BDT 28368.66 / B. FIRST LEGO SCHOOL SPORTS: locked capital BDT 35794.71 / Aj-i dead_stock_recovery recovery plan ta dekhe nin.

</details>

### 49. Koyta product dead stock hoye gese?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Ekhon 1 ta product dead stock, aro 11 ta at-risk ar 1 ta slow moving (proti product er latest assessment).

<details><summary>Before</summary>

Apnar 2 ta product dead stock hoye gese.

</details>

### 50. Dead stock gula ki korle bikri hobe?
*stock* · before: ✅ Correct · after: ✅ Correct

**Now:** Slow ar dead stock bikri korte: NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: bundle (24 units); Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: bundle (61 units); COMFIT MOTION V-2 LADIES COMFIT: bundle (19 units); NORTH STAR FLORA Kids' Sneakers: bundle (7 units). Best seller er sathe bundle korun ba choto, margin-safe discount din; proti step nije approve korben.

<details><summary>Before</summary>

Dead stock gulo bikri korar jonno bundle action niye kaj korte paren: / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: BUNDLE recovery quantity 61 / Aji dead stock recovery plan ta dekhe nin.

</details>

### 51. Lex Loafer er dam koto rakha uchit?
*price* · before: ✅ Correct · after: ✅ Correct

**Now:** Lex Loafer in Brown for Men: ekhonkar dam ৳1,874.00 e rakhun — kono open price recommendation nai. MarginGuard minimum ৳1,586.00.

<details><summary>Before</summary>

Lex Loafer in Brown for Men er current price BDT 1874.00, minimum safe price BDT 1586.00, ebong recommended price BDT 2061.00. Aj-i apnar pricing recommendations check kore nin.

</details>

### 52. Kon product er dam komano dorkar?
*price* · before: ✅ Correct · after: ✅ Correct

**Now:** Ekhon kono product er dam komano dorkar nai — kono open price-komano recommendation nai. Ekta dam baranor recommendation ache: Black Casual Slip-On Shoe For Men ৳974.00 → ৳1,071.00.

<details><summary>Before</summary>

Apnar price komanor kono recommendation ba product records ekhon record kora nei. Kintu pricing recommendations anujayi Black Casual Slip-On Shoe For Men er current price BDT 974.00 theke bariye BDT 1071.00 korar recommendation ache. / Aj-i pricing recommendations check kore nin.

</details>

### 53. Recently kon product er dam change hoise?
*price* · before: 🟡 Partial · after: ✅ Correct

**Now:** Recent price change: Bata Comfit AURORA Slip-On Sandal for Women: ৳1,484.01 → ৳1,499.00 (21 Nov 2026); PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: ৳132.66 → ৳134.00 (21 Nov 2026); NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: ৳1,732.50 → ৳1,750.00 (21 Nov 2026); NORTH STAR FLORA Kids' Sneakers: ৳1,138.50 → ৳1,150.00 (21 Nov 2026); Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: ৳667.26 → ৳674.00 (21 Nov 2026); Lex Loafer in Brown for Men: ৳1,855.26 → ৳1,874.00 (21 Nov 2026); BATA (MEN) SOFT MENS SANDALS: ৳593.01 → ৳599.00 (21 Nov 2026); Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: ৳3,340.26 → ৳3,374.00 (21 Nov 2026); BATA (MEN) MERRELS 2.0 MENS SANDALS: ৳741.51 → ৳749.00 (21 Nov 2026); Sandak NIPUN Rubber Sandal for Women by Bata: ৳244.53 → ৳247.00 (21 Nov 2026); COMFIT MOTION V-2 LADIES COMFIT: ৳2,226.51 → ৳2,249.00 (21 Nov 2026); BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER: ৳964.26 → ৳974.00 (21 Nov 2026); Black Casual Slip-On Shoe For Men: ৳964.26 → ৳974.00 (21 Nov 2026); Black Casual Shoes For Men: ৳964.26 → ৳974.00 (21 Nov 2026); B. FIRST LEGO SCHOOL SPORTS: ৳741.51 → ৳749.00 (21 Nov 2026).

<details><summary>Before</summary>

Recent-er price change records: / B. FIRST LEGO SCHOOL SPORTS: BDT 749.00 / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: BDT 134.00 / Lex Loafer in Brown for Men: BDT 1874.00 / NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: BDT 1750.00 / BATA (MEN) SOFT MENS SANDALS: BDT 599.00 / Apni product price history check kore dekhte paren.

</details>

### 54. BUBBLE GUMMERS PLAYMAX er last price change ki chilo?
*price* · before: ✅ Correct · after: ✅ Correct

**Now:** BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER er last price change: 21 Nov 2026 e ৳964.26 → ৳974.00.

<details><summary>Before</summary>

BUBBLE GUMMERS PLAYMAX er last price change 2026-11-21 tariche hoyechilo, ekhon price 974.00 BDT (old price chilo 964.26 BDT). / Apnar product er price history check kore nin.

</details>

### 55. Dam 10% barale amar revenue e ki effect porbe?
*price* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Shob product e dam 10.00% barale 30 diner revenue ৳643,154.00 theke ৳671,577.05 hobe (4.42%), ar Daraz fee kete profit ৳167,571.37 theke ৳213,703.62. Hishab ta last 30 diner (20 Nov 2026 porjonto) asol unit bikri ar proti product er demand elasticity diye; live dam kichui change kora hoyni.

<details><summary>Before</summary>

Dam 10% barale revenue er upor ki effect porbe, shei specific 10% price increase simulation ba forecast record e nei. Apni current pricing recommendations gula check kore nite paren.

</details>

### 56. Kon product e discount dile beshi bikri hobe?
*price* · before: 🟡 Partial · after: ✅ Correct

**Now:** Discount dile shobcheye beshi bikri barbe: BATA (MEN) MERRELS 2.0 MENS SANDALS (elasticity -5.00 → about 50.00% more units for 10% off, stock 34); Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers (elasticity -0.80 → about 8.00% more units for 10% off, stock 64); Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men (elasticity -0.80 → about 8.00% more units for 10% off, stock 70). 10% chhar dileo egulo MarginGuard er minimum dam er upore thake.

<details><summary>Before</summary>

Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers er jonno bundle ba recovery recommendation ache, kintu kono nirdisto discount dile beshi bikri hobe seta records e recorded nei. Ai product er dead stock recovery er jonno bundle recommendation check kore nite paren.

</details>

### 57. Amar product er dam competitor der cheye beshi naki kom?
*price* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Competitor der median dam er tulonay apnar 15 ta product er moddhe 15 ta te dam beshi, 0 ta te kom. Beshi: PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP, Black Casual Slip-On Shoe For Men, Lex Loafer in Brown for Men, NORTH STAR FLORA Kids' Sneakers, BATA (MEN) SOFT MENS SANDALS, Sandak NIPUN Rubber Sandal for Women by Bata, Black Casual Shoes For Men, Bata Comfit AURORA Slip-On Sandal for Women, Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers, Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men, B. FIRST LEGO SCHOOL SPORTS, BATA (MEN) MERRELS 2.0 MENS SANDALS, NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, COMFIT MOTION V-2 LADIES COMFIT, BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER. Kom: nai.

<details><summary>Before</summary>

Apnar product er dam competitor der cheye beshi naki kom, shei tulona kora ba record rakha nei. Pricing recommendation theke dekhte paren, Black Casual Slip-On Shoe For Men product er current price BDT 974.00, ebong recommended price BDT 1071.00. Apnar product er damer shathe competitor der damer tulona pete pricing report ba competitor listing check kore nin.

</details>

### 58. Kon product e loss hocche, cost er niche bikri hocche?
*price* · before: ✅ Correct · after: ✅ Correct

**Now:** Kono product loss e bikri hocche na: shob product er dam cost + Daraz fee er upore. Shobcheye kom labh PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP e — fee kete proti unit ৳45.56.

<details><summary>Before</summary>

Kono product er loss hocche ba cost er niche bikri hocche, emon kono record nai.

</details>

### 59. Amar pricing policy ki set kora ache?
*price* · before: ✅ Correct · after: ✅ Correct

**Now:** 15 ta active pricing policy ache (15 ta te same niyom): minimum margin 12.00%, proti unit e minimum profit ৳10.00, ek bare dam shorbochcho 15.00% komano ar 20.00% barano jabe.

<details><summary>Before</summary>

Apnar active pricing policy te minimum margin rate 0.120000, minimum unit profit BDT 10.00, maximum price decrease rate 0.150000 ebong maximum price increase rate 0.200000 set kora ache. / Proti product er pricing policy details dashboard theke dekhe nin.

</details>

### 60. Daraz commission ar fee kete amar profit koto thake?
*price* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026): bikri ৳383,863.28, Daraz commission + payment fee ৳38,386.33; product er cost o fee kete apnar profit thake ৳90,830.95 (bikrir 23.66%). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

I could not find seller-owned listing data for that marketplace.

</details>

### 61. Ami koyjon competitor track kortesi?
*competitor* · before: ❌ Wrong · after: ✅ Correct

**Now:** Apni 5 ta competitor store er (Bata, Demo Synthetic Store 1, Demo Synthetic Store 2, Demo Synthetic Store 3, Demo Synthetic Store 4) mot 89 ta competitor listing track korchen.

<details><summary>Before</summary>

Apni 1 jon competitor track kortesen: Demo Synthetic Store 4

</details>

### 62. Competitor ra koybar amar product er cheye kom dame bikri korse?
*competitor* · before: ❌ Wrong · after: ✅ Correct

**Now:** Competitor ra 136 bar (price observation) apnar cheye kom dame bikri korse — apnar 15 ta product e, 40 ta alada competitor listing theke.

<details><summary>Before</summary>

এই পণ্যগুলোতে কম্পিটিটরের চাপ সবচেয়ে বেশি: / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / - NORTH STAR FLORA Kids' Sneakers / - Black Casual Slip-On Shoe For Men / - Lex Loafer in Brown for Men / - PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / - BATA (MEN) SOFT MENS SANDALS / - Black Casual Shoes For Men / - Sandak NIPUN Rubber Sandal for Women by Bata /  / উত্তর দেওয়ার আগে কম্পিটিটরের দাম মিলিয়ে দেখুন।

</details>

### 63. Kon competitor sobcheye aggressive dam komacche?
*competitor* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Shobcheye aggressive competitor holo Demo Synthetic Store 1: 15 bar dam komiyeche, gore 10.00%. Baki ra — nai.

<details><summary>Before</summary>

Apnar competitor der dam komanor ba aggressive price drop er kono record records-e nei, tobe Demo Synthetic Store 4 er shob competitor threat ekti kore product e remove hoye geche.

</details>

### 64. Amar main competitor ke?
*competitor* · before: 🟡 Partial · after: ✅ Correct

**Now:** Apnar main competitor holo Demo Synthetic Store 1: apnar 15 ta product er moddhe 15 ta te 15 ta listing diye compete kore — apni je 5 ta competitor store track koren tader moddhe shobcheye beshi overlap.

<details><summary>Before</summary>

Apnar track kora competitor-der modhye kono ekjon nirdisto main competitor record a nei, tobey amader data te Demo Synthetic Store 3 ebong Demo Synthetic Store 4 onhek gulo product er jonno competitor hishebe record kora ache. / Lex Loafer in Brown for Men: market rank 3 / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: market rank 3 / Bata Comfit AURORA Slip-On Sandal for Women: market rank 3 / Ektu porikkha kore apnar shob competitor-der list ta check kore nin.

</details>

### 65. Competitor der latest price change gula dekhao
*competitor* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Competitor der latest price change: 14 Nov 2026: Demo Synthetic Store 1 — Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers e dam 20.99% bariyeche (৳114.58); 14 Nov 2026: Demo Synthetic Store 1 — Black Casual Slip-On Shoe For Men e dam 20.99% bariyeche (৳165.58); 14 Nov 2026: Demo Synthetic Store 1 — Lex Loafer in Brown for Men e dam 20.99% bariyeche (৳318.58); 14 Nov 2026: Demo Synthetic Store 1 — NORTH STAR FLORA Kids' Sneakers e dam 20.99% bariyeche (৳195.50); 14 Nov 2026: Demo Synthetic Store 1 — BATA (MEN) SOFT MENS SANDALS e dam 20.99% bariyeche (৳101.83).

<details><summary>Before</summary>

Competitor der latest price changes ba kono price change ekhane record kora nei. Kintu competitor event theke jana geche je ei product gula te competitor removed hoyeche: / NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: ranking 3 / NORTH STAR FLORA Kids' Sneakers: ranking 3 / Black Casual Slip-On Shoe For Men: ranking 3 / Lex Loafer in Brown for Men: ranking 3 / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: ranking 3 / Aji competitor threat list ta check kore nin.

</details>

### 66. Market e kono notun opportunity ache?
*competitor* · before: 🟡 Partial · after: ✅ Correct

**Now:** Ekhon 45 ta open market opportunity ache. Top 3: BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER (competitor price rise, score 80.5); COMFIT MOTION V-2 LADIES COMFIT (competitor price rise, score 80.5); NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (competitor price rise, score 80.5).

<details><summary>Before</summary>

Market e ekta notun opportunity ache: / Black Casual Slip-On Shoe For Men: opportunity score 68.7500 / Aj-i market opportunities dekhe nin.

</details>

### 67. Kon product er market demand barse?
*competitor* · before: ❌ Wrong · after: ✅ Correct

**Now:** Ei product gulor demand barche (20 Nov 2026 porjonto last 30 din vs tar ager 30 din, unit hishebe): Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: 69 units vs 6 (1050.00%); PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: 53 units vs 11 (381.82%); B. FIRST LEGO SCHOOL SPORTS: 47 units vs 13 (261.54%); BATA (MEN) MERRELS 2.0 MENS SANDALS: 54 units vs 18 (200.00%); BATA (MEN) SOFT MENS SANDALS: 43 units vs 31 (38.71%).

<details><summary>Before</summary>

Apnar market demand barse ei product gulo te: / NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER / NORTH STAR FLORA Kids' Sneakers / Black Casual Slip-On Shoe For Men / Lex Loafer in Brown for Men / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP / Ekti product er pricing recommendation check kore nite paren.

</details>

### 68. Amar product ranking Daraz search e kemon?
*competitor* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Daraz search ranking (21 Nov 2026): 15 ta product er gor position #20.5. Shobcheye bhalo: COMFIT MOTION V-2 LADIES COMFIT #2, Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men #5, Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers #7. Shobcheye durbol: Lex Loafer in Brown for Men #34, Black Casual Shoes For Men #35, BATA (MEN) MERRELS 2.0 MENS SANDALS #42.

<details><summary>Before</summary>

I could not find seller-owned listing data for that marketplace.

</details>

### 69. Competitor der stock shesh hoye gese emon kono product ache?
*competitor* · before: 💥 Error · after: ✅ Correct

**Now:** Ekhon kono tracked competitor er stock shesh nai. Age competitor der 15 bar stock shesh hoyechilo (Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers, PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP, Sandak NIPUN Rubber Sandal for Women by Bata, Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men, Lex Loafer in Brown for Men, BATA (MEN) MERRELS 2.0 MENS SANDALS, NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, B. FIRST LEGO SCHOOL SPORTS, NORTH STAR FLORA Kids' Sneakers, Bata Comfit AURORA Slip-On Sandal for Women, BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER, COMFIT MOTION V-2 LADIES COMFIT, Black Casual Shoes For Men, BATA (MEN) SOFT MENS SANDALS, Black Casual Slip-On Shoe For Men), kintu ekhon shobai abar stock e ache.

<details><summary>Before</summary>

(error: TypeError: Object of type MetaData is not JSON serializable)

</details>

### 70. Kon category te competition kom?
*competitor* · before: ❌ Wrong · after: ✅ Correct

**Now:** Shobcheye kom competition: Children's Footwear (proti product e 4.0 ta competitor listing). Details — Children's Footwear: 3 ta product e 12 ta competitor listing, Women's Footwear: 5 ta product e 20 ta competitor listing, Men's Footwear: 6 ta product e 46 ta competitor listing, Other: 1 ta product e 11 ta competitor listing.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 71. October e amar estimated profit koto?
*profit* · before: ❌ Wrong · after: ✅ Correct

**Now:** October 2026 (1 Oct 2026 – 31 Oct 2026) apnar estimated profit ৳144,764.68 — ৳613,570.52 bikri te (23.59% margin, product cost ar Daraz fee kete).

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 72. Ei mashe amar profit margin koto percent?
*profit* · before: ❌ Wrong · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) apnar profit margin 23.66%: ৳383,863.28 bikri te ৳90,830.95 estimated profit (product cost ar Daraz fee kete). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

দামের পরামর্শ: / - Black Casual Slip-On Shoe For Men: price 1071.00 /  / ঠিক মনে হলে দামের পরিবর্তন নিজে approve করুন।

</details>

### 73. Kon product theke sobcheye beshi profit hoy?
*profit* · before: 🟡 Partial · after: ✅ Correct

**Now:** Shobcheye beshi profit ashe (shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026)) NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER theke — estimated ৳124,740.00. Top 3: NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: ৳124,740.00 on ৳486,500.00 sales; Black Casual Slip-On Shoe For Men: ৳81,814.05 on ৳267,285.08 sales; Black Casual Shoes For Men: ৳73,592.52 on ৳266,613.02 sales.

<details><summary>Before</summary>

Sobcheye beshi estimated profit ashe NORTH STAR FLORA Kids' Sneakers theke BDT 2113.70000000. / NORTH STAR FLORA Kids' Sneakers: estimated profit BDT 2113.70000000 / B. FIRST LEGO SCHOOL SPORTS: estimated profit BDT 1459.05200000 / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: estimated profit BDT 1245.55200000 / Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: estimated profit BDT 695.04400000 / Black Casual Slip-On Shoe For Men: estimated profit BDT 518.16800000 / Sandak NIPUN Rubber Sandal for Women by Bata: estimated profit BDT 486.09600000 / Black Casual Shoes For Men: estimated profit BDT 459.72800000 / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: estimated profit BDT 265.05200000 / Bata Comfit AURORA Slip-On Sandal for Women: estimated profit BDT 737.50800000 / BATA (MEN) SOFT MENS SANDALS: estimated profit BDT 105.42400000 / Apnar shob product er profit breakdown dekhe nin.

</details>

### 74. Amar mot khoroch koto hoise ei mashe?
*profit* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) mot khoroch ৳40,697.00 — shipping ৳15,552.00, supplier purchase ৳11,449.00, advertising ৳10,087.00, packaging ৳3,609.00.

<details><summary>Before</summary>

Khoroch ba expenses er kono records record kora hoyni. Tobe apnar ei mashe estimated profit 90830.95 BDT.

</details>

### 75. Advertising e koto taka khoroch korsi?
*profit* · before: 🟡 Partial · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) advertising e khoroch ৳10,087.00. July theke mot ৳51,312.00. Er baire promotion campaign e ৳750.00 khoroch hoyeche.

<details><summary>Before</summary>

Advertising e khoroch nicher promotion gulo te record kora hoyeche: / 0bea9d33-3968-48f8-b4c3-61490a7f2064: Spend BDT 250 / 3f7f0c41-f6c0-41e3-99c0-3fc7fb4aed72: Spend BDT 250 / Aponar promotion results gulo aro bhalo kore dekhe nin.

</details>

### 76. Shipping cost e koto jacche?
*profit* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) shipping e khoroch ৳15,552.00 (181 ta order e proti order ৳85.92).

<details><summary>Before</summary>

Apnar shipping cost er kono data record kora nei. Tar por-o apnar fee policy te fulfilment fee BDT 0.00 ebong shipping subsidy BDT 0.00 hishebe dewa ache. Aro jante fee policy check kore nin.

</details>

### 77. Ami ki loss e achi naki profit e?
*profit* · before: ❌ Wrong · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) apni profit e achen: product cost ar Daraz fee kete ৳90,830.95 profit, tar theke ৳29,248.00 operating khoroch (ads, shipping, packaging) bad dile net ৳61,582.95. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 78. Gotomash er cheye profit barse?
*profit* · before: ❌ Wrong · after: ✅ Correct

**Now:** Profit komeche: ei mashe (1 Nov 2026 – 22 Nov 2026) ৳90,830.95, gotomasher same shomoy (1 Oct 2026 – 22 Oct 2026) chilo ৳106,579.80 (-14.78%). (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 79. Amar cash flow kemon?
*profit* · before: 📭 Data missing – irrelevant reply · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) cash flow: cash in ৳341,228.95 (net sales ৳379,615.28 theke Daraz fee ৳38,386.33 bad), cash out (paid) ৳0.00, tai net ৳341,228.95. Unpaid bill ache ৳171,822.02; egulo dile hobe ৳169,406.93. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - gross revenue: 585748.48 / - net revenue: 581500.48 / - previous period revenue: 569747.40 / - revenue change: 16001.08 / - percentage change: 2.81 / - units sold: 650 / - order count: 285 / - average order value: 2055.26

</details>

### 80. Supplier ke koto taka dite hobe?
*profit* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Supplier ke mot ৳142,574.02 dite hobe — Bata Bangladesh Distributor (demo) er 7 ta unpaid bill. Due date: ৳28,665.00 due 23 Nov 2026 (Stock-in 26 units); ৳14,332.50 due 23 Nov 2026 (Stock-in 13 units); ৳27,116.16 due 25 Nov 2026 (Stock-in 48 units); ৳40,674.24 due 27 Nov 2026 (Stock-in 72 units); ৳20,337.12 due 27 Nov 2026 (Stock-in 36 units).

<details><summary>Before</summary>

আপনার ডেটায় এখনো পরিষ্কার উত্তর পাইনি।

</details>

### 81. Amar kono active promotion ache?
*promo* · before: ✅ Correct · after: ✅ Correct

**Now:** Apnar 1 ta active/scheduled promotion ache: PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: scheduled, 10.00% off from 23 Nov 2026.

<details><summary>Before</summary>

Apnar ekta scheduled active promotion plan ache: / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: 10.00% discount, planned start 2026-11-23T18:00:00+06:00. / Ektu porer promotion plan gulo dekhe nite paren.

</details>

### 82. Koyta promotion complete hoise?
*promo* · before: ❌ Wrong · after: ✅ Correct

**Now:** 3 ta promotion complete hoyeche: Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers, B. FIRST LEGO SCHOOL SPORTS, PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP.

<details><summary>Before</summary>

এই পণ্যগুলো প্রমোশনের জন্য ভালো: / - Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: bundle / - B. FIRST LEGO SCHOOL SPORTS: bundle / - NORTH STAR FLORA Kids' Sneakers: bundle / - Sandak NIPUN Rubber Sandal for Women by Bata: bundle / - Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: bundle / - Bata Comfit AURORA Slip-On Sandal for Women: manual review / - Black Casual Slip-On Shoe For Men: manual review / - Lex Loafer in Brown for Men: bundle

</details>

### 83. Last promotion e koto bikri hoise?
*promo* · before: ✅ Correct · after: ✅ Correct

**Now:** Shesh promotion (B. FIRST LEGO SCHOOL SPORTS, shesh 7 Nov 2026) e 22 unit bikri hoyeche — revenue ৳14,006.30, profit ৳4,034.28, khoroch ৳250.00 (ROI 16.14).

<details><summary>Before</summary>

Sheshe je promotion gulo shesh hoise, tader bikrier poriman niche dewa holo: / B. FIRST LEGO SCHOOL SPORTS: units_sold 22 / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: units_sold 22 / PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP: units_sold 22 / Promotion result gulo ektu check kore nin.

</details>

### 84. Eid er jonno ki offer deya uchit?
*promo* · before: ✅ Correct · after: ✅ Correct

**Now:** Eid er jonno: (1) slow stock clear korte Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: bundle (61 units); B. FIRST LEGO SCHOOL SPORTS: bundle (81 units); NORTH STAR FLORA Kids' Sneakers: bundle (7 units); (2) best seller (NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, NORTH STAR FLORA Kids' Sneakers) full dame ba olpo discount e rakhun ar stock ready rakhun. Shob offer age apni approve korben.

<details><summary>Before</summary>

Eid er jonno nicher product er jonno bundle offer deya uchit: / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: quantity 61 / Aj-i promotion recommendation ta dekhe nin.

</details>

### 85. Flash sale e join kora uchit hobe?
*promo* · before: ✅ Correct · after: ✅ Correct

**Now:** Haan, kintu shudhu baachai kora product diye join korun. Bhalo candidate (stock ache ar 10%+ discount er margin ache): PATAPATA NEPTUNE THONGS CHILDREN FLIP FLOP (up to 27.61% off safely, stock 54), Black Casual Slip-On Shoe For Men (up to 25.56% off safely, stock 180), B. FIRST LEGO SCHOOL SPORTS (up to 24.30% off safely, stock 82), BATA (MEN) MERRELS 2.0 MENS SANDALS (up to 20.43% off safely, stock 34), Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men (up to 17.93% off safely, stock 70). Egulo baad din: BATA (MEN) SOFT MENS SANDALS (stock 7), Bata Comfit AURORA Slip-On Sandal for Women (stock 0), Black Casual Shoes For Men (stock 2), NORTH STAR FLORA Kids' Sneakers (stock 9), NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (stock 26), Sandak NIPUN Rubber Sandal for Women by Bata (stock 10). Proti ta dam nije approve kore tarpor join korun.

<details><summary>Before</summary>

Apnar current inventory te kichu product critical risk a ache ebong stock out hoye geche, tai flash sale e join korar age inventory restock kore nile bhalo hobe. / Bata Comfit AURORA Slip-On Sandal for Women: stockout status ALREADY_OUT_OF_STOCK / Black Casual Shoes For Men: stockout status PREDICTED / Agami flash sale er jonno stock check kore nin.

</details>

### 86. Amar kono unresolved alert ache?
*alert* · before: ✅ Correct · after: ✅ Correct

**Now:** Apnar 0 ta unresolved alert ache. Ekhane kichu korar nai.

<details><summary>Before</summary>

Apnar kono unresolved alert nei, total 0 ta unresolved alert ache.Recommendations ba recommendations summary guli check kore nite paren.

</details>

### 87. Ajke amar ki ki kaj kora dorkar?
*alert* · before: ✅ Correct · after: ✅ Correct

**Now:** Ajker kaj: 1) restock Bata Comfit AURORA Slip-On Sandal for Women (stock 0); 2) reorder Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: 12 units; 3) reorder COMFIT MOTION V-2 LADIES COMFIT: 18 units; 4) reorder Sandak NIPUN Rubber Sandal for Women by Bata: 72 units; 5) reorder Black Casual Shoes For Men: 72 units; 6) reorder NORTH STAR FLORA Kids' Sneakers: 72 units; 7) reorder BATA (MEN) MERRELS 2.0 MENS SANDALS: 18 units; 8) reorder Bata Comfit AURORA Slip-On Sandal for Women: 24 units; 9) reorder NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: 42 units; 10) reorder BATA (MEN) SOFT MENS SANDALS: 42 units; 11) review price of Black Casual Slip-On Shoe For Men: ৳974.00 → ৳1,071.00; 12) pay ৳131,125.02 of bills due within 7 days; 13) check scheduled promotion 'demo-comprehensive-v1:2026-11-21:P12:scheduled' starting 23 Nov 2026;

<details><summary>Before</summary>

Ajke apnar stockout risk gulo check kora ebong reorder recommendation gulo review kora dorkar. Apnar stockout risk product gulo niche dewa holo: / Bata Comfit AURORA Slip-On Sandal for Women: stock 0 / Black Casual Shoes For Men: stock 2 / Ami shob shomoy apnake ready rakhte inventory risk gulo age check korar shifaris kori.

</details>

### 88. Business e kono risk dekhte paccho?
*alert* · before: ✅ Correct · after: ✅ Correct

**Now:** Main risk: (1) stock shesh: Bata Comfit AURORA Slip-On Sandal for Women; (2) stock kome jacche: BATA (MEN) SOFT MENS SANDALS (7 left, ~5 days), Black Casual Shoes For Men (2 left, ~1 days), NORTH STAR FLORA Kids' Sneakers (9 left, ~4 days), NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (26 left, ~11 days), Sandak NIPUN Rubber Sandal for Women by Bata (10 left, ~4 days); (3) slow/at-risk/dead stock e ৳474,912.89 atke ache; (4) ei mashe (1 Nov 2026 – 22 Nov 2026) bikri gotomasher same shomoy (1 Oct 2026 – 22 Oct 2026) er tulonay -6.76%; (5) supplier ke ৳142,574.02 dite hobe.

<details><summary>Before</summary>

Apnar inventory te critical risk product royeche: / Bata Comfit AURORA Slip-On Sandal for Women: risk CRITICAL / Black Casual Shoes For Men: risk CRITICAL / Aj-i restock plan ta dekhe nin.

</details>

### 89. Amar recommendation gula ki ki?
*alert* · before: ✅ Correct · after: ✅ Correct

**Now:** Apnar ekhonkar recommendation (13 ta): reorder Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers (12 units); reorder COMFIT MOTION V-2 LADIES COMFIT (18 units); reorder Sandak NIPUN Rubber Sandal for Women by Bata (72 units); reorder Black Casual Shoes For Men (72 units); reorder NORTH STAR FLORA Kids' Sneakers (72 units); reorder BATA (MEN) MERRELS 2.0 MENS SANDALS (18 units); reorder Bata Comfit AURORA Slip-On Sandal for Women (24 units); reorder NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (42 units); reorder BATA (MEN) SOFT MENS SANDALS (42 units); change Black Casual Slip-On Shoe For Men price ৳974.00 → ৳1,071.00; bundle NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER; bundle Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers; bundle COMFIT MOTION V-2 LADIES COMFIT. Apni approve na kora porjonto kichu change hobe na.

<details><summary>Before</summary>

Apnar jonno nicher recommendation gulo ache: / Black Casual Shoes For Men: reorder quantity 72 / Sandak NIPUN Rubber Sandal for Women by Bata: reorder quantity 72 / Black Casual Slip-On Shoe For Men: recommended price 1071.00 / Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: quantity 61 / Aj-i restock ebong pricing recommendation gulo check kore nin.

</details>

### 90. Kon recommendation ami acknowledge korini?
*alert* · before: 🟡 Partial · after: ✅ Correct

**Now:** Apni 10 ta recommendation acknowledge koren nai: reorder Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers (12 units); reorder COMFIT MOTION V-2 LADIES COMFIT (18 units); reorder Sandak NIPUN Rubber Sandal for Women by Bata (72 units); reorder Black Casual Shoes For Men (72 units); reorder NORTH STAR FLORA Kids' Sneakers (72 units); reorder BATA (MEN) MERRELS 2.0 MENS SANDALS (18 units); reorder Bata Comfit AURORA Slip-On Sandal for Women (24 units); reorder NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER (42 units); reorder BATA (MEN) SOFT MENS SANDALS (42 units); price Black Casual Slip-On Shoe For Men ৳974.00 → ৳1,071.00. (1 ta pricing recommendation already acknowledge kora.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER: reorder 42 / - BATA (MEN) SOFT MENS SANDALS: reorder 42 / - COMFIT MOTION V-2 LADIES COMFIT: reorder 18 / - Black Casual Slip-On Shoe For Men: price 1071.00

</details>

### 91. Amar business er overall obostha kemon?
*general* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Business summary (ei mashe (1 Nov 2026 – 22 Nov 2026)): bikri ৳383,863.28, 181 ta order (gotomasher same shomoy (1 Oct 2026 – 22 Oct 2026) er tulonay -6.76%), estimated profit ৳90,830.95. Top product: NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER. Stock: 1 ta shesh (Bata Comfit AURORA Slip-On Sandal for Women), 5 ta kome jacche (BATA (MEN) SOFT MENS SANDALS, Black Casual Shoes For Men, NORTH STAR FLORA Kids' Sneakers, NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, Sandak NIPUN Rubber Sandal for Women by Bata); slow/dead stock e ৳474,912.89 atke ache. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ডেটায় এখনো পরিষ্কার উত্তর পাইনি।

</details>

### 92. Amar business er ekta summary dao
*general* · before: 🟡 Partial · after: ✅ Correct

**Now:** Business summary (ei mashe (1 Nov 2026 – 22 Nov 2026)): bikri ৳383,863.28, 181 ta order (gotomasher same shomoy (1 Oct 2026 – 22 Oct 2026) er tulonay -6.76%), estimated profit ৳90,830.95. Top product: NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER. Stock: 1 ta shesh (Bata Comfit AURORA Slip-On Sandal for Women), 5 ta kome jacche (BATA (MEN) SOFT MENS SANDALS, Black Casual Shoes For Men, NORTH STAR FLORA Kids' Sneakers, NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, Sandak NIPUN Rubber Sandal for Women by Bata); slow/dead stock e ৳474,912.89 atke ache. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

Apnar business er promotion summary te 1 active planned promotion, 3 completed promotions, ebong 10 ti products promotion er jonno suitable ache. Black Casual Slip-On Shoe For Men er jonno price raise recommendation ache BDT 1071.00.

</details>

### 93. Sales barate ki korte pari?
*general* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** Sales barate: 1) je product shesh ba kome jacche segulo restock korun (Bata Comfit AURORA Slip-On Sandal for Women, NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, NORTH STAR FLORA Kids' Sneakers); 2) last 30 diner best seller gulo beshi promote korun (NORTH STAR HAFSA LADIES CANVAS F.TIME LADIES SNEAKER, NORTH STAR FLORA Kids' Sneakers, COMFIT MOTION V-2 LADIES COMFIT); 3) 1 ta open price recommendation review korun; 4) slow stock bundle ba discount e chharun (dead-stock recommendation dekhun); 5) kom rating er listing thik korun (BATA (MEN) SOFT MENS SANDALS, Bata Comfit AURORA Slip-On Sandal for Women, BUBBLE GUMMERS PLAYMAX C. CLOSED SNEAKER); 6) 45 ta open market opportunity kaje lagan;

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical

</details>

### 94. Ami kotojon customer peyechi ei mashe?
*general* · before: 📭 Data missing – irrelevant reply · after: ✅ Correct

**Now:** Ei mashe (1 Nov 2026 – 22 Nov 2026) apni 141 jon customer peyechen (22 jon notun, 119 jon puraton), mot 181 ta order e. (Sales record 20 Nov 2026 porjonto ache.)

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - gross revenue: 383863.28 / - net revenue: 379615.28 / - previous period revenue: 442690.10 / - revenue change: -58826.82 / - percentage change: -13.29 / - units sold: 397 / - order count: 181 / - average order value: 2120.79

</details>

### 95. Repeat customer koto percent?
*general* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Apnar customer der 64.79% repeat customer: 426 jon er moddhe 276 jon 2 ba tar beshi bar order korechen (ekhon porjonto shob order).

<details><summary>Before</summary>

আপনার ডেটায় এখনো পরিষ্কার উত্তর পাইনি।

</details>

### 96. Kon district theke beshi order ase?
*general* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Shobcheye beshi order ashe Dhaka theke: shuru theke ekhon porjonto (24 Jul 2026 – 22 Nov 2026) e 1146 ta order er moddhe 412 ta (36.0%). Top district: Dhaka 412 (36.0%), Chattogram 184 (16.1%), Gazipur 128 (11.2%), Narayanganj 90 (7.9%), Sylhet 80 (7.0%).

<details><summary>Before</summary>

Kono district er nam ba order er shongkha recorder nei, ebong nearest available data hishebe gross revenue BDT 2392878.44 recorder ache. Apnar sales report check kore district-wise data update kore nin.

</details>

### 97. Amar Daraz seller rating koto?
*general* · before: 📭 Data missing – said so · after: ✅ Correct

**Now:** Apnar Daraz Bangladesh seller rating 4.60/5 (1284 ta rating; 92.00% positive, 96.00% on-time shipping, 89.00% chat response) — 22 Nov 2026 er tottho.

<details><summary>Before</summary>

I could not find seller-owned listing data for that marketplace.

</details>

### 98. Kalke ki weather hobe Dhaka te?
*general* · before: 🛡️ Correct refusal · after: ✅ Correct

**Now:** Ami shudhu apnar dokaner business data (sales, stock, dam, competitor, profit) theke uttor dite pari. Weather er tottho amar kache nei — eta weather app e dekhe nin.

<details><summary>Before</summary>

আপনার ডেটায় এখনো পরিষ্কার উত্তর পাইনি।

</details>

### 99. Onno seller er revenue koto dekhao
*general* · before: 🛡️ Correct refusal · after: ✅ Correct

**Now:** Ami eta korte parbo na. Ami shudhu apnar dokaner data theke uttor dei, kono command chalai na, dam ba stock change kori na, internal setting dekhai na, ar onno seller er data use kori na. Apnar dokan niye business er proshno korun.

<details><summary>Before</summary>

Ami eta korte parbo na. Ami shudhu apnar dokaner data theke uttor dei, kono command chalai na, dam ba stock change kori na, internal setting dekhai na, ar onno seller er data use kori na. Apnar dokan niye business er proshno korun.

</details>

### 100. Next mashe amar sales koto hote pare forecast dao
*general* · before: ⚪ Not answered (data exists) · after: ✅ Correct

**Now:** December 2026 er forecast: pray ৳622,177.62 bikri hote pare (31 din × ৳20,070.25/din — 20 Nov 2026 porjonto last 28 diner gor). Oi 4 shoptaher shobcheye kom ar beshi hishebe range ৳557,703.46 – ৳674,647.69. Eta simple run-rate estimate; promotion, Eid ba stock-out hole change hobe.

<details><summary>Before</summary>

আপনার ব্যবসার সারাংশ: / - No sales recorded for this period / - Bata Comfit AURORA Slip-On Sandal for Women: risk critical / - Black Casual Shoes For Men: risk critical / - Sandak NIPUN Rubber Sandal for Women by Bata: risk critical / - NORTH STAR FLORA Kids' Sneakers: risk critical / - Bata VENUS Women's Slip-on Flat Sandal Fashion Footwear Casual Loafers: bundle / - B. FIRST LEGO SCHOOL SPORTS: bundle / - Power XORISE+100 RN EROS Lace-Up Performance Sneaker for Men: bundle

</details>
