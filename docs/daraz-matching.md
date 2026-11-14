# Daraz competitor matching

## Previous formula

The existing verifier used normalized titles and descriptions, lexical entity overlap and matching attributes, followed by cosine similarity from all-MiniLM-L6-v2. It scored 30% title, 25% description, 25% attributes, 10% keywords and 10% marketplace ranking. If description text was absent, its weight moved to title. If either side lacked attributes, 60% of the attribute weight moved to title and 40% to keywords. Description similarity was the greater of cosine similarity and description token overlap. A category label mismatch multiplied the result by 0.85.

The effective threshold applied adjustments for low and high keyword overlap, strong attributes, strong title similarity, and absent matching model tokens. The requested threshold remained the floor, with a minimum floor of 0.50. Accessory, brand, title identifier, family, and variant checks ran before embedding. The process cached up to 2,000 embeddings and loaded the configured model on demand.

## Current verification

1. Compare explicit listing identity before using embeddings. Checksummed GTIN, EAN, UPC and ISBN values are read from labelled fields and normalized across equivalent encodings. Brand plus an explicit matching manufacturer model or product identifier can also establish exact identity. Seller SKUs and marketplace listing IDs are scoped to their own records. Critical conflicts take precedence over exact identity evidence.
2. Reject clear accessory or replacement-part mismatches, conflicting product families and editions, a refurbished candidate for an unspecified-condition seller product, and bundle or pack-size mismatches. A charger included with a phone does not by itself make the listing a charger. Compare structured RAM and storage for computer and phone categories, generation, capacity, screen size, dimensions and recognized explicit colors when comparable observations exist. Missing specifications are allowed. The rules are limited to recognized categories, units and labels.
3. Score the remaining candidates using title cosine, description and specification evidence, normalized attribute agreement and lexical overlap. The weights are 30, 25, 25 and 10, normalized by their sum of 90. When there are no shared attribute keys, transfer 15 points to title and 10 to lexical evidence. Description evidence takes the greater of cosine and token overlap. A minimum title score is required unless exact identity was established. A conflict-free exact identifier match receives a rule score of 1.0.
4. Apply the effective verification threshold, which is the greater of the requested value and the configured verification floor. Only strong and very strong matches enter the existing competitor service. Possible and unverified results stay within the diagnostic evaluation function. A raw score is a heuristic and has no probability interpretation. Marketplace ranking is passed through separately. The scraper still uses popularity for preliminary candidate ordering and shortlist selection.

The existing public matcher arguments and score fields remain available. Public JSON and database schemas are unchanged. JSON-LD identifiers are carried through the existing specifications field. Final verification uses fresh extraction data. No additional database table is used.

| Configuration | Default |
| --- | --- |
| `SIMILARITY_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` |
| `SIMILARITY_DEVICE` | `cpu`. Also supports available accelerators and `auto`. |
| `SIMILARITY_BATCH_SIZE` | 32, bounded to 1–64 |
| `SIMILARITY_THRESHOLD` | 0.65 |
| `SIMILARITY_VERIFICATION_FLOOR` | 0.50 |
| `SIMILARITY_MIN_TITLE_EVIDENCE` | 0.55 |
| `SIMILARITY_POSSIBLE_THRESHOLD` | 0.50 |
| `SIMILARITY_VERY_STRONG_THRESHOLD` | 0.88 |
| `SIMILARITY_DIMENSIONS_TOLERANCE` | 0.03 relative difference for screen size and dimensions |

Stage the model in the worker's Hugging Face cache or provide a local model path before deployment. Workers load local files only. They log an accelerator-to-CPU or configured-model-to-MiniLM fallback when needed. If the models cannot load, or inference fails, the scrape still reports the corresponding similarity failure. The worker logs model memory, load time, and inference timing, and bounds the embedding cache to 2,000 CPU vectors.

## Evaluation procedure

The dataset contains 42 synthetic, manually labelled pairs with rationales. Calibration uses 23 pairs. The remaining 19 use distinct product families and include sparse and bilingual listings. Each alternative uses the same pairs and rules. A calibration sweep from 0.50 to 0.95 prioritizes F1, then fewer false positives and then proximity to the default. This sample is too small to claim population-level calibration. The 0.50 and 0.88 exploratory and very-strong boundaries are policy bands.

Run each model in a fresh process after staging its files. For example, from `backend/`:

```sh
SIMILARITY_THRESHOLD=0.65 PYTHONPATH=. venv/bin/python scripts/evaluate_daraz_matching.py sentence-transformers/all-MiniLM-L6-v2
SIMILARITY_THRESHOLD=0.65 PYTHONPATH=. venv/bin/python scripts/evaluate_daraz_matching.py BAAI/bge-m3
SIMILARITY_THRESHOLD=0.65 PYTHONPATH=. venv/bin/python scripts/evaluate_daraz_matching.py intfloat/multilingual-e5-base
```

Each process uses four CPU threads, warms the model, and clears the embedding cache before each pair. The compatible-pair mean includes preprocessing and inference for pairs that pass identity checks. Peak RSS includes Python, PyTorch and model memory. The E5 evaluation uses its symmetric matching prefix. [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) · [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3) · [Multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-base)

### Measured results

Apple M2 CPU, four threads. The first four rows use a 0.65 threshold. The legacy row uses the repository's earlier MiniLM scoring formula with result filling disabled to isolate the verifier.

| Matcher and threshold | Precision | Recall | F1 | False positive rate | False negative rate | Mean compatible pair | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy MiniLM, 0.65 | 44.4% | 44.4% | 0.444 | 45.5% | 55.6% | — | — |
| Current MiniLM, 0.65 | 100% | 88.9% | 0.941 | 0% | 11.1% | 8.35 ms | 527.2 MiB |
| BGE-M3, 0.65 | 88.9% | 88.9% | 0.889 | 9.1% | 11.1% | 129.01 ms | 2,097.7 MiB |
| Multilingual E5, 0.65 | 88.9% | 88.9% | 0.889 | 9.1% | 11.1% | 37.19 ms | 1,263.3 MiB |

The calibration sweep chose 0.51 for MiniLM, 0.50 for BGE-M3 and 0.58 for E5. Their holdout F1 scores at those thresholds were 0.889, 0.947 and 0.889, respectively. BGE-M3 at 0.50 recovered one extra true match and introduced one false match compared with MiniLM at 0.65. MiniLM remains the default at 0.65. Its holdout miss was a Bangla-only bottle title paired with an English equivalent. The calibration split still contains a same-brand shampoo formulation false positive at that threshold.
