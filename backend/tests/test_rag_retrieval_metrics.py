from app.services.rag_retrieval_metrics import ExpectedHit, hit_matches, recall_at_k, reciprocal_rank, top_group_share

SALES = {"source_type": "SALES_HISTORY", "product_sku": "SKU-1", "chunk_text": "Sales fell 12% in week 46"}
PRICE = {"source_type": "PRICE_HISTORY", "product_sku": "SKU-1", "chunk_text": "Price raised to BDT 950"}


def test_hit_matches_needs_type_sku_and_all_text():
    assert hit_matches(SALES, ExpectedHit("SALES_HISTORY", "SKU-1", ("sales fell",)))
    assert not hit_matches(SALES, ExpectedHit("SALES_HISTORY", "SKU-2"))
    assert not hit_matches(SALES, ExpectedHit("SALES_HISTORY", None, ("sales fell", "refund")))


def test_recall_and_rank():
    exp = [ExpectedHit("PRICE_HISTORY")]
    assert recall_at_k([SALES, PRICE], exp, 1) == 0.0
    assert recall_at_k([SALES, PRICE], exp, 2) == 1.0
    assert reciprocal_rank([SALES, PRICE], exp) == 0.5
    assert reciprocal_rank([], exp) == 0.0
    assert recall_at_k([SALES], [], 5) == 1.0


def test_top_group_share():
    assert top_group_share([SALES, SALES, PRICE, SALES], 4) == 0.75
    assert top_group_share([], 12) == 0.0
