"""Evaluate one locally staged model on the shared, manually labelled Daraz fixtures."""
from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

import torch

from app.scraper import similarity

DATASET = Path(__file__).resolve().parents[1] / "tests/fixtures/daraz/product_pairs.json"


def metrics(rows, threshold):
    counts = dict(tp=0, fp=0, tn=0, fn=0)
    errors = []
    for pair, result in rows:
        predicted = bool(result and result["title_gate"] and result["similarity_score"] >= threshold)
        expected = pair["expected_match"]
        counts["tp" if predicted and expected else "fp" if predicted else "fn" if expected else "tn"] += 1
        if predicted != expected:
            errors.append(pair["id"])
    tp, fp, tn, fn = (counts[k] for k in ("tp", "fp", "tn", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        **counts, "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0,
        "errors": errors,
    }


def run(model_name: str):
    torch.set_num_threads(4)
    similarity.SIMILARITY_MODEL_NAME = model_name
    similarity.SIMILARITY_DEVICE = "cpu"
    # Evaluation must measure the requested model even if runtime would fall back.
    start = time.perf_counter()
    model = similarity._load_model(model_name, "cpu")
    load_ms = (time.perf_counter() - start) * 1000
    similarity._get_model = lambda: model
    similarity._embed_texts(["product matching warm up"])
    pairs = json.loads(DATASET.read_text())
    splits = {"calibration": [], "holdout": []}
    times = []
    inference_times = []
    for pair in pairs:
        similarity._EMBED_CACHE.clear()
        start = time.perf_counter()
        result = similarity.evaluate_competitor_matches(
            pair["seller_title"], [{
                "product_title": pair["candidate_title"],
                "product_category": pair.get("category"),
                "product_description": pair.get("candidate_description"),
                "product_attributes": pair.get("candidate_specs"),
            }],
            seller_category=pair.get("category"),
            seller_description=pair.get("seller_description"),
            seller_specifications=pair.get("seller_specs"),
        )
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        if result:
            inference_times.append(elapsed)
        splits[pair["split"]].append((pair, result[0] if result else None))

    options = [(n / 100, metrics(splits["calibration"], n / 100)) for n in range(50, 96)]
    # Favor F1, then lower false positives, then the smallest move from the default.
    chosen, calibration = max(
        options, key=lambda option: (option[1]["f1"], -option[1]["fp"], -abs(option[0] - similarity.BASE_THRESHOLD)),
    )
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    return {
        "model": model_name, "device": "cpu", "threads": torch.get_num_threads(),
        "load_ms": round(load_ms, 2), "mean_pair_ms": round(statistics.mean(times), 2),
        "mean_compatible_pair_ms": round(statistics.mean(inference_times), 2),
        "peak_process_rss_mib": round(rss_bytes / 2**20, 1),
        "model_parameter_mib": round(sum(p.numel() * p.element_size() for p in model.parameters()) / 2**20, 1),
        "calibrated_threshold": chosen, "calibration": calibration,
        "holdout_calibrated": metrics(splits["holdout"], chosen),
        "holdout_at_default": metrics(splits["holdout"], similarity.BASE_THRESHOLD),
        "calibration_at_default": metrics(splits["calibration"], similarity.BASE_THRESHOLD),
        "calibration_scores": {p["id"]: round(r["similarity_score"], 4) if r else None for p, r in splits["calibration"]},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=[
        "sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-m3", "intfloat/multilingual-e5-base",
    ])
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    print(json.dumps(run(args.model), indent=2))
