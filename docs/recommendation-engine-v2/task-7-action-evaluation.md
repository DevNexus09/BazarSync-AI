# Task 7 · Risk-aware action evaluation

The action evaluator runs inside the Task 6 orchestrator. It reads the normalized candidate, the seller-scoped decision context, and the exact MarginGuard verdict when a price is involved. The final decision uses the same policy as the initial evaluation. When Task 6 refreshes product, inventory, or pricing evidence before persistence, the evaluator reevaluates the remaining candidates. [Evaluator](../../backend/app/services/action_evaluation_service.py) · [Selection](../../backend/app/services/recommendation_selection.py)

## Hard constraints

- Directional prices require verified sellable inventory, the scoped current offer and cost, applicable fees, fresh matched competitor prices, and a supported historical demand-response scenario with positive projected profit impact. Promotional pricing uses its scoped recovery assessment and inventory instead of a competitor-price claim.
- Every proposed price must have a matching MarginGuard result, stay at or above the safe floor, fit the persisted price range, and pass the marketplace increment and effective seller pricing limits. The verdict provides deterministic per-unit contribution. Projected business profit remains a separate model output.
- Reorders require a verified inventory snapshot, positive supported demand, supplier lead time, a deadline within the configured planning horizon, and a positive whole-unit quantity. The evaluator checks both the seller's minimum order quantity and pack size from the dedicated engine's evidence. A stock-consuming recovery proposal must fit the available quantity and have a current assessment.
- A provided adverse-outcome probability above the configured limit blocks selection. A failed hard check yields a null score regardless of urgency. Missing data and failed constraints are recorded separately within the report.

Unavailable baseline demand and unknown unit contribution now leave the corresponding specialized pricing forecasts null. An observed zero baseline can still yield a zero estimate.

## Scoring and selection

Each scored factor is normalized to `[0, 1]`. The score is the weighted mean of applicable, available factors. The audit retains the raw value, unit, provenance, weight, and normalized value. The policy records these relative weights.

| Dimension | Weight | Normalization |
| --- | ---: | --- |
| Evidence quality | 0.35 | Pricing uses the fraction of scraped observations with validated prices. Reorder uses full qualified coverage or the fraction of the sales window with recorded sales days. Recovery uses a verified assessment. |
| Urgency | 0.30 | Reorder uses proximity to the engine deadline relative to the planning horizon. Recovery uses the assessment's rule-based risk points divided by 100. A base-price change carries no urgency score. |
| Benefit | 0.20 | Pricing divides supported projected profit delta by the configured BDT reference and caps the result at one. Reorder divides the unrounded stock gap by target stock. Recovery carries no inferred benefit amount. |
| Operational feasibility | 0.15 | Eligible proposals receive one point. Recovery that needs manual companion selection, campaign setup, or manual review receives half a point. |
| Forecast uncertainty | 0.15 | The score is one minus the larger of the available relative interval spread and adverse-outcome probability, clamped to the normalized range. Relative spread is interval width divided by twice the absolute central estimate. A zero central estimate leaves relative spread unavailable. |

Observed inventory and market inputs are measured. Reorder quantities, stock gaps, rule-based urgency, and guard economics are deterministic estimates. The historical elasticity scenario supplies modeled profit deltas. Where evidence is insufficient, including for procurement profit or recovery lift, the financial outcome is unsupported. The existing engine confidence is retained as an unweighted rule score. Current pricing bounds are labeled sensitivity bands with unknown coverage. The internal contract also accepts a future prediction interval or a probability for a named adverse outcome with its source, version, and horizon.

Candidates below the minimum score cannot lead or support the decision. A qualifying reorder due today or earlier takes precedence, then candidates rank by score. Exact ties use action category, deadline, stable source and action labels, parameters, and finally candidate UUID for otherwise identical proposals. A supporting candidate must be compatible with every selected action. If no actionable candidate qualifies, the generic action is `HOLD` with reason codes.

## Configuration and stored evidence

| Setting | Default | Purpose |
| --- | --- | --- |
| `RECOMMENDATION_ACTION_EVALUATION_ENABLED` | `false` | Opt in within Task 6 active or shadow mode. |
| `RECOMMENDATION_ACTION_MIN_SCORE` | `0.50` | Minimum normalized preference score. |
| `RECOMMENDATION_ACTION_PROFIT_REFERENCE_BDT` | `1000` | Projected profit delta that earns the full monetary benefit factor for the source scenario. |
| `RECOMMENDATION_ACTION_MAX_ADVERSE_RISK` | `0.60` | Maximum supplied adverse-outcome probability. |

The existing inventory freshness and reorder horizon settings feed the evaluator. Active mode saves `risk-aware-v1` and the actual policy values in `recommendation_context.decision_orchestration.action_evaluation_policy`. Each normalized candidate carries its evaluation report beside the candidate and final guard evidence. The primary and supporting IDs reference the selected proposals. Shadow mode keeps its diagnostic logging behavior and the legacy response. Current HTTP and event payloads use the existing schemas.
