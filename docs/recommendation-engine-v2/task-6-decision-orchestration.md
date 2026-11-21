# Task 6 · Multi-engine recommendation decisions

The generic recommendation worker builds one validated context for the verified seller and product. It shares fresh, matched competitor observations, measured net sales through the last completed seller business day, inventory and reservations, lead time, current price and cost, and the applicable Daraz Bangladesh pricing policy and fees. The context also records available elasticity and dead-stock assessment references, calculation versions, and evidence gaps. [Decision context](../../backend/app/schemas/recommendation_decision.py) · [Orchestrator](../../backend/app/services/decision_orchestrator.py)

## Engine evaluation

| Engine | Inputs and checks |
| --- | --- |
| Reorder | Uses the dedicated stockout and reorder builders with scoped demand and fresh inventory. A reorder requires an explicit supplier lead time and an engine-supported quantity and deadline. Unconfirmed incoming stock is excluded. Reorder can qualify without competitor or fee data. |
| Dynamic pricing | Uses the dedicated scenario builder with fresh, verified competitor prices, sellable inventory, scoped sales, applicable fees, and a sufficiently recent historical elasticity estimate with a positive baseline. Directional prices require positive estimated profit impact. A lower price is ineligible when predicted stockout falls within lead time. The stored elasticity provider is replaceable without changing selection. |
| Dead-stock recovery | Uses the existing recovery builder with a recent assessment, relevant listing evidence, and scoped companions. A stock-consuming action requires an assessment tied to the current inventory snapshot and a quantity within sellable units. A promotion uses MarginGuard for its exact promotional price. |

Each engine is evaluated on its own inputs. Builders produce transient outputs for the Task 5 adapter. Their scored alternatives and guard evidence remain available within the normalized candidates. Missing inputs are recorded for the affected engine. Product restrictions that require manual review also block automatic recommendations to change the base price or replenish stock.

## Selection and persistence

1. A supported reorder takes priority. If several qualify, the earlier deadline wins.
2. A supported base-price change takes priority over recovery. Among comparable price candidates, higher estimated profit impact wins, followed by stable engine and action ordering.
3. An eligible recovery action can be the primary advice under generic `HOLD`. When there is no supported action, the decision stays `HOLD` with evidence and reason codes.
4. A reorder keeps the base price steady and can carry listing advice. It excludes unconditional price changes and stock-consuming recovery actions. A directional price change excludes a simultaneous promotional price. A raise also excludes stock-consuming recovery proposals. Opposite base-price directions cannot both be selected.

The service refreshes the scoped product under the existing persistence lock, checks relevant inventory and candidate freshness, and reruns MarginGuard on exact prices under the current terms. It invalidates affected proposals when the inputs or pricing terms change and selects again from the remaining candidates. The worker saves one generic recommendation and its existing seller-scoped RAG outbox entry through the fenced job transaction. [Selection rules](../../backend/app/services/recommendation_selection.py) · [Persistence path](../../backend/app/services/recommendation_service.py)

The `decision_orchestration` section of `recommendation_context` contains validated inputs, engine results, rejection reasons, the primary candidate ID, supporting candidate IDs, and scoped supporting advice. Competitor provenance remains in the existing `competitor_evidence` section. Signed profit and revenue deltas remain internal to candidate evidence. Public confidence is a rule-based label capped at medium. The API and recommendation event keep their existing response structures, and recommendations advise only.

## Runtime modes

| Settings | Behavior |
| --- | --- |
| Both flags off | Existing generic decision path. |
| `RECOMMENDATION_ORCHESTRATION_SHADOW_ENABLED=true` only | After a legacy result is saved, the worker evaluates the new decision in a savepoint and logs the two action labels. The legacy response is returned and shadow failures are logged. |
| `RECOMMENDATION_ORCHESTRATION_ENABLED=true` | The new decision supplies the seller-visible recommendation. The API uses durable jobs and recovery scheduling even when the standalone jobs flag is off. Existing legacy Celery messages keep their original path. |

Both flags default to false. Active mode uses the existing job tables and Beat recovery task, so deploy it with the corresponding migrations and consistent API, worker and Beat settings. API preflight verifies product ownership and pins the completed scrape ID when available. The worker collects and validates the business evidence once for evaluation.
