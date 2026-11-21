from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import torch

from app.scraper import similarity
from app.scraper.exceptions import SimilarityUnavailableError
from app.scraper.parser import DarazParser

TITLE = "Samsung Galaxy S24 256GB"
DATA = Path(__file__).parent / "fixtures/daraz/product_pairs.json"


def score_vectors(scores):
    return torch.tensor([[1.0, 0.0], *[[s, (1 - s**2) ** 0.5] for s in scores]], dtype=torch.float64)


@pytest.mark.parametrize(("title", "seller_specs", "candidate_specs", "category"), [
    ("Samsung Galaxy S25 256GB", {}, {}, "smartphones"),
    ("Samsung Galaxy S24 Ultra 256GB", {}, {}, "smartphones"),
    ("স্যামসাং গ্যালাক্সি S24 ১২৮GB", {}, {}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"RAM": "8 GB"}, {"ram": "12 GB"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {}, {"storage": "128 GB"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"Model number": "SM-S921B"}, {"MPN": "SM-S926B"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"generation": "2nd Gen"}, {"generation": "3"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"Color": "blue"}, {"Colour": "red"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"screen size": '6.2"'}, {"screen size": "7 inches"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"dimensions": "7 x 14 x 1 cm"}, {"dimensions": "72 x 156 x 10 mm"}, "smartphones"),
    ("Samsung Galaxy S24 256GB", {"brand": "Samsung"}, {"Brand": "Apple"}, "smartphones"),
    ("Samsung Galaxy S24 256GB 2 pack", {}, {}, "smartphones"),
    ("Samsung Galaxy S24 256GB refurbished", {}, {}, "smartphones"),
    ("Samsung Galaxy S24 256GB replacement display", {}, {}, "smartphones"),
    ("Samsung Galaxy S24 256GB কভার", {}, {}, "smartphones"),
    ("Charger for Samsung Galaxy S24 256GB", {}, {}, "smartphones"),
])
def test_critical_conflicts_reject_before_embedding(monkeypatch, title, seller_specs, candidate_specs, category):
    embed = Mock(side_effect=AssertionError("hard conflict reached model"))
    monkeypatch.setattr(similarity, "_embed_texts", embed)
    result = similarity.filter_valid_competitors(
        TITLE, [{"product_title": title, "product_attributes": candidate_specs, "ranking_score": 1,
                 "product_description": "Identical description"}],
        threshold=0, seller_description="Identical description",
        seller_category=category, seller_specifications=seller_specs,
    )
    assert result == []
    embed.assert_not_called()


def test_verified_identity_and_checksums(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.2]))
    candidate = {"product_title": "Hobbit paperback", "product_attributes": {"ISBN-13": "9780261102217"}}
    matches = similarity.filter_similar_products(
        "The Hobbit paperback", [candidate], seller_specifications={"ISBN": "0-261-10221-4"},
    )
    assert matches[0]["exact_identity"]
    assert matches[0]["match_classification"] == "VERY_STRONG"

    candidate["product_attributes"] = {"ISBN-13": "9780261102210"}
    assert not similarity.filter_similar_products(
        "The Hobbit paperback", [candidate], seller_specifications={"ISBN": "9780261102210"},
    )
    candidate["product_attributes"] = {"ISBN-13": "9780547928227"}
    assert not similarity.filter_similar_products(
        "The Hobbit paperback", [candidate], seller_specifications={"ISBN": "9780261102217"},
    )


def test_valid_gtin_does_not_override_spec_conflict(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", Mock(side_effect=AssertionError))
    assert not similarity.filter_similar_products(
        TITLE, [{"product_title": TITLE, "product_attributes": {"GTIN": "036000291452", "RAM": "16 GB"}}],
        seller_specifications={"UPC": "036000291452", "RAM": "8 GB"},
    )


def test_same_brand_explicit_model_with_sparse_bilingual_title(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.3]))
    result = similarity.filter_similar_products(
        TITLE, [{"product_title": "স্যামসাং গ্যালাক্সি এস ফোন", "product_brand": "স্যামসাং",
                 "product_attributes": {"MPN": "SM-S921B"}}],
        seller_specifications={"model number": "SM S921B"},
    )
    assert result[0]["similarity_score"] == 1.0
    assert result[0]["exact_identity"]


def test_included_accessory_and_irrelevant_ram_do_not_force_rejection(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.99]))
    assert similarity.filter_similar_products(TITLE, [{"product_title": f"{TITLE} with charger"}])
    assert similarity.filter_similar_products(
        "Ceramic mug", [{"product_title": "Ceramic mug", "product_attributes": {"RAM": "16 GB"}}],
        seller_specifications={"RAM": "8 GB"}, seller_category="Drinkware",
    )

def test_operational_product_attributes_do_not_reject_footwear_match(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.95]))
    identity_specs = {"brand": "Bata", "style": "Soft sandal", "audience": "MEN", "product_type": "Soft Sandal"}
    operational_specs = {
        "image_url": "https://static.example/sandal.jpg", "pack_size": "6", "safety_stock": "6",
        "source_listing_id": "1575185161", "source_listing_url": "https://www.daraz.com.bd/products/-i1575185161.html",
        "source_price_observed_at": "2026-11-19T21:10:49.166147+00:00", "source_marketplace": "Daraz Bangladesh",
        "source_store": "Bata", "source_validation_status": "VERIFIED_PUBLIC_LISTING",
        "source_missing_fields": "material,color,available_sizes", "source_observed_price_bdt": "599.00",
        "minimum_order_quantity": "12", "maximum_stock": "90", "market_reference_only": "true",
        "quantity_reserved": "4", "demo_data_class": "SYNTHETIC_DEMO_BUSINESS_DATA",
        "quantity_incoming_unconfirmed": "0", "inventory_scenario": "slow_moving",
        "demo_demand_pattern": "low", "holding_cost_bdt_per_unit_per_day": "0.50",
    }
    candidate = {"product_title": "Bata Soft Mens Sandal", "product_brand": "Bata",
                 "product_attributes": {"Brand": "Bata", "Style": "Soft sandal"}}
    kwargs = {"seller_description": "Soft men's sandal listed by the Bata store on Daraz Bangladesh.",
              "seller_category": "Other"}
    baseline = similarity.filter_similar_products(
        "BATA (MEN) SOFT MENS SANDALS", [candidate], seller_specifications=identity_specs, **kwargs,
    )
    with_operational_metadata = similarity.filter_similar_products(
        "BATA (MEN) SOFT MENS SANDALS", [candidate],
        seller_specifications={**identity_specs, **operational_specs}, **kwargs,
    )
    assert with_operational_metadata
    assert with_operational_metadata[0]["similarity_score"] == baseline[0]["similarity_score"]

def test_pack_conflict_requires_comparable_evidence(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.95]))
    candidate = {"product_title": "Ceramic mug"}
    assert similarity.filter_similar_products(
        "Ceramic mug", [candidate], seller_specifications={"pack quantity": "6"},
    )
    assert not similarity.filter_similar_products(
        "Ceramic mug", [{"product_title": "Ceramic mug", "product_attributes": {"pack quantity": "2"}}],
        seller_specifications={"pack quantity": "6"},
    )


def test_popularity_is_pass_through_and_exploration_stays_out_of_verified_results(monkeypatch):
    monkeypatch.setattr(similarity, "_embed_texts", lambda _: score_vectors([0.6, 0.6]))
    monkeypatch.setattr(similarity, "_keyword_overlap_score", lambda *_: 0.5)
    monkeypatch.setattr(similarity, "_token_overlap_score", lambda *_: 0)
    items = [{"product_title": TITLE, "ranking_score": rank} for rank in (0, 1)]
    results = similarity.evaluate_competitor_matches(TITLE, items, threshold=0.65)
    assert results[0]["similarity_score"] == results[1]["similarity_score"]
    assert [row["ranking_score"] for row in results] == [0, 1]
    assert {row["match_classification"] for row in results} == {"POSSIBLE"}
    assert not similarity.filter_similar_products(TITLE, items, threshold=0.65)
    boundary = results[0]["similarity_score"]
    assert len(similarity.filter_similar_products(TITLE, items, threshold=boundary)) == 2
    assert not similarity.filter_similar_products(TITLE, items, threshold=boundary + 0.0001)


def test_shared_description_does_not_verify_unrelated_title(monkeypatch):
    embed = Mock(side_effect=[score_vectors([0.2]), score_vectors([1.0])])
    monkeypatch.setattr(similarity, "_embed_texts", embed)
    assert not similarity.filter_similar_products(
        "Wireless headphones", [{"product_title": "Wireless keyboard", "product_description": "Same description",
                                 "ranking_score": 1}],
        seller_description="Same description",
    )


def test_embedding_cache_bounded_and_owned(monkeypatch):
    cache = similarity._EMBED_CACHE
    cache.clear()
    model = Mock()
    model.encode.side_effect = lambda texts, **kwargs: torch.ones((len(texts), 3))
    monkeypatch.setattr(similarity, "_get_model", lambda: model)
    monkeypatch.setattr(similarity, "_EMBED_CACHE_MAX", 2)
    try:
        similarity._embed_texts(["a", "b", "c"])
        assert len(cache) == 2
        assert all(t.device.type == "cpu" and t._base is None for t in cache.values())
        similarity._embed_texts(["b", "c"])
        model.encode.assert_called_once()
    finally:
        cache.clear()


def test_model_fallback_uses_local_minilm_and_evaluation_mode(monkeypatch):
    import sentence_transformers

    model = Mock(device="cpu", parameters=Mock(return_value=[]))
    load = Mock(side_effect=[OSError("missing alternative"), model])
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", load)
    monkeypatch.setattr(similarity, "SIMILARITY_MODEL_NAME", "intfloat/multilingual-e5-base")
    monkeypatch.setattr(similarity, "SIMILARITY_DEVICE", "cpu")
    similarity._get_model.cache_clear()
    try:
        assert similarity._get_model() is model
        model.eval.assert_called_once()
        assert [call.args[0] for call in load.call_args_list] == [
            "intfloat/multilingual-e5-base", similarity.BASELINE_SIMILARITY_MODEL,
        ]
        assert all(call.kwargs == {"device": "cpu", "local_files_only": True} for call in load.call_args_list)
    finally:
        similarity._get_model.cache_clear()


def test_model_loading_errors_remain_visible(monkeypatch):
    monkeypatch.setattr(similarity, "_load_model", Mock(side_effect=OSError("fixture")))
    similarity._get_model.cache_clear()
    with pytest.raises(SimilarityUnavailableError):
        similarity.filter_similar_products(TITLE, [{"product_title": TITLE}])


def test_json_ld_identity_preserves_public_manufacturer_fields():
    row = DarazParser().extract_html(
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Phone","url":"/products/phone.html","gtin13":"9780261102217","mpn":"ABC-123"}'
        '</script>', None,
    )[0]
    assert row.specifications == {"gtin13": "9780261102217", "mpn": "ABC-123"}


def test_dataset_holdout_uses_distinct_product_groups():
    rows = json.loads(DATA.read_text())
    calibration = {row["group"] for row in rows if row["split"] == "calibration"}
    holdout = {row["group"] for row in rows if row["split"] == "holdout"}
    assert calibration and holdout and calibration.isdisjoint(holdout)
    assert all(row["rationale"] for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)
