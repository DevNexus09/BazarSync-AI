# Task 5 · Internal recommendation candidates

Use `to_recommendation_candidate` on a result from the existing dynamic pricing, reorder planning or dead-stock recovery service. Pass the seller and product IDs from the verified caller scope. The adapter checks both IDs before projecting the record into the Pydantic schema. It accepts results from the build and persistence paths and performs no database, marketplace or RAG writes. [Adapter](../../backend/app/services/recommendation_candidate_adapter.py) · [Schema](../../backend/app/schemas/recommendation_candidate.py)

```python
candidate = to_recommendation_candidate(
    specialized_result, seller_id=verified_seller_id, product_id=product_id
)
```

## Fields and units

A candidate has an ID, seller and product IDs, a source engine, a primary action, typed proposal parameters, and evidence. The specialized record ID serves as the candidate ID when available. Each projection of an unsaved result gets an in-memory UUID. Evidence contains the optional record ID, typed upstream record references when available, and a detached copy of the engine's evidence snapshot. The source calculation version and generation time are required. Reorder carries its business date. Pricing and recovery carry expiry when available.

| Engine | Primary action and parameters | Evidence |
| --- | --- | --- |
| Dynamic pricing | `LOWER` or `RAISE` carries the exact proposed price and current price. `HOLD` carries the current price and leaves the target empty. | Pricing analytics, optional elasticity estimate and the evaluated prices in the engine snapshot. |
| Reorder | `REORDER` requires a positive whole-unit quantity. `HOLD` carries zero for a calculated no-order outcome and null when the engine lacks demand evidence. The suggested deadline is optional. | Inventory, sales velocity and stockout references where present, and the engine's inventory and demand snapshot. |
| Dead-stock recovery | `HOLD` carries the existing specialized recovery action and alternatives. Discount and flash sale use a promotional price, discount rate, and unit cap. Flash sale also specifies duration in days. Bundles carry a unit cap. Listing improvements and manual review retain their specialized action labels. | Assessment reference, candidate ranking evidence and rejected alternatives. |

Monetary values are finite `Decimal` amounts with up to two decimal places. BDT is the supported currency for the current Daraz Bangladesh guard paths. Optional pricing deltas are the source engine's incremental revenue and profit estimates, in BDT for its forecast horizon. Either may be null and a supplied zero remains zero. Only an eligible directional pricing proposal exposes these deltas. Confidence is the source engine's optional score on a 0–100 scale. Common risk and urgency metrics await evidence and units shared across engines.

## Candidate evaluation status

| Status | Meaning |
| --- | --- |
| `generated` | A proposal has been constructed and awaits evaluation. |
| `eligible` | An open engine result has the evidence required by the adapter and can enter later selection. |
| `rejected` | Recorded guard evidence blocks the proposal or differs from the proposed price or action, or the source record has left the open workflow. Rejection reasons are required. |
| `selected` | A later selection step has chosen an eligible candidate. The adapter stops at eligibility. |
| `insufficient_evidence` | The source reports insufficient data, or the adapter lacks the recorded price check or expected units it needs. |

For open price-bearing outputs the adapter reads the existing MarginGuard verdict and checks its evaluated price against the exact source price. For recovery this comes from the leading specialized proposal's guard evidence. Eligibility describes the source snapshot. A future selector must check expiry and current inputs before using it for a new decision.

Task 5 adds the internal conversion boundary. The existing generic action enum, engine calculations, persistence tables, migrations, API payloads, Celery tasks and frontend consumers continue using their existing contracts.
