from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from app.scraper import daraz_scraper
from app.scraper.acquisition.http_client import DarazHttpClient
from app.scraper.constants import HttpxConfig
from app.scraper.daraz_scraper import DarazScraper
from app.scraper.parser import DarazParser
from app.scraper.schemas.scraped_product import DEFAULT_WEIGHTS, ScrapedProduct, assess_extraction
from app.scraper.utils import normalize_stock_status, parse_compact_number, parse_price

FIXTURES = Path(__file__).parent / "fixtures" / "daraz"
TITLE = "Apple iPad 11th Gen 128GB"
URL = "https://www.daraz.com.bd/products/ipad-i1.html"


def test_saved_ajax_fixture_preserves_fields_and_marks_partial():
    parser = DarazParser()
    rows = parser.extract_ajax(json.loads((FIXTURES / "ajax.json").read_text()), None)
    full, _, _, partial = rows
    assert (full.title, full.product_url, full.search_position) == (TITLE, URL, 1)
    assert (full.current_price, full.original_price, full.currency, full.discount_percentage) == (
        Decimal("1250.25"), Decimal("1500"), "BDT", 17,
    )
    assert (full.seller_name, full.rating, full.review_count, full.sold_count) == ("Trusted Store", 4.8, 1250, 1200)
    assert full.sold_label == "1.2k"
    assert full.stock_status == "IN_STOCK"
    assert full.image_url == "https://images.example.test/ipad.jpg"
    assert assess_extraction(full, DEFAULT_WEIGHTS).status == "SUCCESS"
    assert partial.current_price is partial.rating is partial.review_count is partial.sold_count is None
    quality = assess_extraction(partial, DEFAULT_WEIGHTS)
    assert quality.status == "PARTIAL"
    assert quality.missing_important == ("current_price", "seller_name", "stock_status")
    assert assess_extraction(None, DEFAULT_WEIGHTS).status == "FAILED"


def test_empty_is_distinct_from_malformed_and_all_rejected():
    parser = DarazParser()
    assert parser.extract_ajax(json.loads((FIXTURES / "empty.json").read_text()), None) == []
    assert parser.extract_ajax({"mods": {"listItems": [{"name": "no link"}]}}, None) is None
    assert parser.extract_ajax({"mods": {"listItems": None}}, None) is None


def test_stable_html_attributes_survive_tag_and_class_changes():
    row = DarazParser().extract_html((FIXTURES / "listings.html").read_text(), None)[0]
    assert (row.title, row.product_url, row.current_price, row.stock_status, row.seller_name) == (
        TITLE, URL, Decimal("1250.25"), "IN_STOCK", "Trusted Store",
    )
    assert (row.sold_count, row.review_count, row.image_url) == (1200, 1250, "https://images.example.test/ipad.jpg")


def test_structured_search_precedence_fills_missing_values_across_sources():
    row = DarazParser().extract_html((FIXTURES / "structured-search.html").read_text(), None)[0]
    assert (row.title, row.current_price, row.seller_name, row.sold_count, row.review_count) == (
        TITLE, Decimal("1250.25"), "Trusted Store", 0, 1250,
    )
    assert row.field_sources["current_price"] == "json_ld"
    assert row.field_sources["seller_name"] == "application_json"
    assert row.field_sources["review_count"] == "html"


def test_structured_detail_is_scoped_to_exact_listing_and_fills_html_gaps():
    parser = DarazParser()
    html = (FIXTURES / "detail.html").read_text()
    detail = parser.extract_detail(html, URL)
    assert (detail.current_price, detail.description, detail.brand, detail.category) == (
        Decimal("1251.00"), "Structured description", "Apple", "Tablets",
    )
    assert (detail.rating, detail.review_count, detail.specifications) == (
        4.5, 50, {"Storage": "128 GB", "Colour": "Blue"},
    )
    different_variant = parser.extract_detail(html, f"{URL}?sku=other")
    assert different_variant.current_price is None
    assert different_variant.description == "HTML description"


@pytest.mark.parametrize(("value", "expected"), [
    ("৳1,250", "1250"), ("Tk 1,250", "1250"), ("1,250.05 BDT", "1250.05"),
    ("৳১২,৩৪,৫৬৭.৮৯", "1234567.89"), ("1,234,567", "1234567"), ("0", "0"),
    ("USD 1250", None), ("1,25", None), ("100-120", None), ("", None), ("−5", None),
])
def test_decimal_bdt_normalization(value, expected):
    assert parse_price(value) == (Decimal(expected) if expected is not None else None)


@pytest.mark.parametrize(("text", "status"), [
    ("In stock", "IN_STOCK"), ("  Only 2 left in stock ", "IN_STOCK"),
    ("Sold out", "OUT_OF_STOCK"), ("Not available", "OUT_OF_STOCK"),
    ("may become available", "UNKNOWN"), ("stock unknown", "UNKNOWN"), (None, "UNKNOWN"),
])
def test_stock_validation_avoids_unsupported_guesses(text, status):
    assert normalize_stock_status(text) == status


def test_weights_are_configurable_and_zero_is_present(monkeypatch):
    monkeypatch.setenv("SCRAPER_EXTRACTION_WEIGHTS", '{"current_price": 3, "rating": 1}')
    parser = DarazParser()
    row = ScrapedProduct(title=TITLE, product_url=URL, search_position=1, current_price=Decimal("0"))
    assert assess_extraction(row, parser.weights).score == 0.75
    assert "current_price" not in assess_extraction(row, parser.weights).missing_important
    assert parse_compact_number("1,250") == 1250
    with pytest.raises(ValidationError):
        ScrapedProduct(title=TITLE, product_url=URL, search_position=1, current_price=Decimal("0.005"))
    with pytest.raises(ValueError, match="weights"):
        DarazParser({"current_price": -1})


def test_httpx_and_playwright_ajax_produce_identical_normalized_products():
    body = (FIXTURES / "ajax.json").read_bytes()

    @asynccontextmanager
    async def request_context(**kwargs):
        response = SimpleNamespace(status=200, headers={}, text=AsyncMock(return_value=body.decode()))
        yield SimpleNamespace(get=AsyncMock(return_value=response))

    async def run():
        redis = SimpleNamespace(eval=AsyncMock(return_value=(2, 0)), zrem=AsyncMock())
        playwright = DarazScraper(SimpleNamespace(request_context=request_context), redis)
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": "application/json"}),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            httpx_scraper = DarazScraper(Mock(), redis, http=DarazHttpClient(client, HttpxConfig()))
            httpx_rows, httpx_method = await httpx_scraper._search(TITLE)
            playwright_rows, playwright_method = await playwright._search(TITLE)
        assert (httpx_method, playwright_method) == ("httpx", "playwright_api")
        assert httpx_rows == playwright_rows

    asyncio.run(run())


def test_enrichment_spends_slots_on_relevant_listings_and_records_provenance(monkeypatch, caplog):
    scraper = DarazScraper(Mock(), Mock())
    monkeypatch.setattr(daraz_scraper, "DEFAULT_MAX_RESULTS", 2)
    monkeypatch.setattr(scraper, "_fetch_ajax_payload", AsyncMock(return_value=json.loads((FIXTURES / "ajax.json").read_text())))
    html = (FIXTURES / "detail.html").read_text()
    details = AsyncMock(side_effect=lambda url, **_: html if url == URL else None)
    monkeypatch.setattr(scraper, "_fetch_html", details)
    with caplog.at_level("INFO"):
        response = asyncio.run(scraper.scrape(TITLE))
    assert {call.args[0] for call in details.await_args_list} == {URL, "https://www.daraz.com.bd/products/partial-i4.html"}
    assert response.total_results == 2
    item = next(row for row in response.products if row.daraz_product_url == URL)
    assert item.product_price == Decimal("1250.25")
    assert item.product_description == "Structured description"
    assert item.provenance.price_observed_at == item.provenance.search_observed_at
    assert item.provenance.detail_observed_at >= item.provenance.search_observed_at
    assert item.provenance.field_sources["description"] == "json_ld"
    assert "provenance" not in item.model_dump()
    assert item.model_dump(mode="json")["product_price"] == 1250.25
    assert "daraz_parser_version=2.1" in caplog.text
    assert "relevance_filtered=2" in caplog.text


def test_static_search_structured_html_precedes_rendered_browser():
    async def run():
        async def handler(request):
            if request.url.params.get("ajax") == "true":
                return httpx.Response(200, json={})
            return httpx.Response(
                200, text=(FIXTURES / "structured-search.html").read_text(),
                headers={"content-type": "text/html"},
            )

        redis = SimpleNamespace(eval=AsyncMock(return_value=(2, 0)), zrem=AsyncMock())
        manager = Mock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = DarazScraper(manager, redis, http=DarazHttpClient(client, HttpxConfig()))
            scraper._fetch_ajax_payload = AsyncMock(return_value=None)
            result, method = await scraper._search(TITLE)
        assert method == "httpx"
        assert result[0].current_price == Decimal("1250.25")
        manager.page.assert_not_called()

    asyncio.run(run())


def test_static_detail_keeps_exact_price_when_rendered_page_fills_metadata():
    async def run():
        payload = (
            '<script type="application/ld+json">'
            '{"@type":"Product","url":"/products/ipad-i1.html","offers":{"price":0,"priceCurrency":"BDT"}}'
            '</script>'
        )
        transport = httpx.MockTransport(lambda _: httpx.Response(
            200, text=payload, headers={"content-type": "text/html"},
        ))
        redis = SimpleNamespace(eval=AsyncMock(return_value=(2, 0)), zrem=AsyncMock())
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = DarazScraper(Mock(), redis, http=DarazHttpClient(client, HttpxConfig()))
            scraper._fetch_html = AsyncMock(return_value='<section class="product-description">Rendered</section>')
            details = await scraper._fetch_details(URL)
        assert details.method == "chromium"
        assert details.fields.description == "Rendered"
        assert details.fields.current_price == Decimal("0")
        assert details.fields.field_sources["current_price"] == "json_ld"
        assert details.price_observed_at <= details.observed_at

    asyncio.run(run())
