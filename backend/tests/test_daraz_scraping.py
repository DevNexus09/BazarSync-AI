from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
import torch
from celery.exceptions import Ignore, Reject, Retry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1 import scraper as scraper_api
from app.core.celery_app import celery_app
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent, CompetitorEventType, CompetitorEventSeverity
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.price_history import PriceHistory
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.scraper import similarity
from app.scraper.constants import MARKETPLACE_NAME
from app.scraper.daraz_scraper import DarazScraper, _retry_after_seconds
from app.scraper.exceptions import (
    PageLoadError,
    ParseError,
    PermanentAccessError,
    RateLimitError,
    RequestTimeoutError,
    SimilarityError,
    SimilarityUnavailableError,
)
from app.scraper.parser import DarazParser
from app.scraper.schemas import CompetitorProduct, ScrapeResponse
from app.scraper.schemas.scraped_product import ObservationProvenance
from app.scraper.services import competitor_service as acquisition_service
from app.services import scrape_service
from app.tasks import scraper_tasks
from app.services.scrape_scheduling import RefreshPolicy, plan_refreshes

TITLE = "Apple iPad 11th Gen WiFi 128GB"
URL = "https://www.daraz.com.bd/products/ipad-i1.html"


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(scraper_api.router, prefix="/api/v1")
    return app


def test_retired_endpoint_is_inert_and_manual_run_requires_auth(app):
    with TestClient(app) as client:
        retired = client.post("/api/v1/scraper/daraz", json={"product_title": TITLE, "seller_id": str(uuid4())})
        assert retired.status_code == 410
        assert "/api/v1/scraper/run/{product_id}" in retired.json()["detail"]
        assert client.post(f"/api/v1/scraper/run/{uuid4()}").status_code == 401
    assert app.openapi()["paths"]["/api/v1/scraper/daraz"]["post"]["deprecated"] is True


@pytest.mark.parametrize("match_count", [0, 1, 6, 12])
def test_only_candidates_meeting_threshold_are_verified(monkeypatch, match_count):
    # With equal title and detail evidence, 0.549 falls just below the score floor.
    scores = [0.95] * match_count + [0.549]

    def embed(texts):
        assert len(texts) == len(scores) + 1  # Accessory never reaches the model.
        return torch.tensor([[1, 0], *[[s, (1 - s**2) ** 0.5] for s in scores]])

    monkeypatch.setattr(similarity, "_embed_texts", embed)
    # Isolate semantic scores from exact description token overlap.
    monkeypatch.setattr(similarity, "_token_overlap_score", lambda *_: 0.0)
    monkeypatch.setattr(similarity, "_keyword_overlap_score", lambda *_: 1.0)
    rows = [{"product_title": TITLE, "listing": i} for i in range(len(scores))]
    rows.append({"product_title": f"{TITLE} Tempered Glass Screen Protector", "listing": "accessory"})
    results = similarity.filter_similar_products(
        TITLE, rows, seller_description="Original tablet includes a protective case.", threshold=0.65,
    )
    assert [result["listing"] for result in results] == list(range(match_count))


@pytest.mark.parametrize(
    "title",
    ["Apple iPad 10th Gen WiFi 128GB", "Apple iPad 11th Gen WiFi 64GB", "Samsung Galaxy S25 128GB"],
)
def test_explicit_product_conflicts_are_rejected_before_embedding(monkeypatch, title):
    embed = Mock(side_effect=AssertionError("conflicting listing reached the model"))
    monkeypatch.setattr(similarity, "_embed_texts", embed)
    assert similarity.filter_similar_products(TITLE, [{"product_title": title}]) == []
    embed.assert_not_called()


def test_different_models_in_same_family_are_rejected_before_embedding(monkeypatch):
    embed = Mock(side_effect=AssertionError("conflicting model reached the embedding model"))
    monkeypatch.setattr(similarity, "_embed_texts", embed)
    assert similarity.filter_similar_products(
        "Samsung Galaxy S24 128GB", [{"product_title": "Samsung Galaxy S25 128GB"}],
    ) == []
    embed.assert_not_called()


def test_no_matching_candidates_does_not_require_the_model(monkeypatch):
    embed = Mock(side_effect=AssertionError("embedding should not run"))
    monkeypatch.setattr(similarity, "_embed_texts", embed)
    assert similarity.filter_similar_products(TITLE, []) == []
    assert similarity.filter_similar_products(TITLE, [{"product_title": f"{TITLE} case"}]) == []
    embed.assert_not_called()


def test_model_loading_and_encoding_failures_are_distinct(monkeypatch):
    import sentence_transformers

    error = OSError("private model path")
    similarity._get_model.cache_clear()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", Mock(side_effect=error))
    with pytest.raises(SimilarityUnavailableError) as exc:
        similarity.filter_similar_products(TITLE, [{"product_title": TITLE}])
    assert exc.value.__cause__ is error

    monkeypatch.setattr(similarity, "_get_model", lambda: Mock(encode=Mock(side_effect=error)))
    with pytest.raises(SimilarityError) as exc:
        similarity.filter_similar_products(TITLE, [{"product_title": TITLE}])
    assert type(exc.value) is SimilarityError
    assert exc.value.__cause__ is error


@pytest.mark.parametrize("value", [None, "", "N/A", "12-20", "-12", "12 USD", "NaN", "999999999999"])
def test_invalid_or_missing_listing_values_are_unknown(value):
    item = DarazParser().parse_products_from_json(
        {"mods": {"listItems": [{"name": TITLE, "itemUrl": URL, "price": value, "ratingScore": value,
                                 "review": value, "soldCount": value}]}},
        max_results=None,
    )[0]
    listing = CompetitorProduct.model_validate(item)
    assert (listing.product_price, listing.rating, listing.rating_count, listing.sold_count) == (None,) * 4


def test_explicit_zero_survives_both_parsers_and_ranking():
    parser = DarazParser()
    zero = parser.parse_products_from_json(
        {"mods": {"listItems": [{"name": TITLE, "itemUrl": URL, "price": 0, "priceShow": "৳100",
                                 "ratingScore": 0, "review": 0, "itemSoldCntShow": 0, "soldCount": 900,
                                 "originalPrice": 100, "discount": 0}]}},
        max_results=None,
    )[0]
    normalized = parser.extract_ajax(
        {"mods": {"listItems": [{"name": TITLE, "itemUrl": URL, "price": 0, "originalPrice": 100, "discount": 0}]}},
        max_results=None,
    )[0]
    assert DarazScraper(Mock(), Mock())._rank_products([normalized])[0][0].discount_percentage == 0
    card = parser.parse_products(
        f'<div data-qa-locator="product-item"><a href="{URL}" title="{TITLE}"></a>'
        '<span class="price">৳0.00</span><span class="rating--pwPrV">0</span>'
        '<span class="rating__review">(0)</span><span class="sold-count">0 sold</span></div>',
        max_results=None,
    )[0]
    for item in [zero, card]:
        assert (item["product_price"], item["rating"], item["rating_count"], item["sold_count"]) == (0, 0, 0, "0")


def test_valid_display_values_can_recover_malformed_primary_values():
    item = DarazParser().parse_products_from_json(
        {"mods": {"listItems": [{
            "name": TITLE, "itemUrl": URL, "price": "invalid", "priceShow": "৳1,250.00",
            "originalPrice": "invalid", "originalPriceShow": "৳1,500",
            "itemSoldCntShow": "invalid", "soldCount": 0,
        }]}},
        max_results=None,
    )[0]
    assert (item["product_price"], item["original_price"], item["sold_count"]) == (1250, 1500, "0")


def test_html_fallback_requires_recognizable_results(monkeypatch):
    scraper = DarazScraper(Mock(), Mock())
    ajax = AsyncMock(side_effect=[{"mods": {"listItems": []}}, {"mods": {}}, {"mods": {}}])
    html = AsyncMock(side_effect=[
        f'<div data-qa-locator="product-item"><a href="{URL}" title="{TITLE}"></a></div>',
        "<html>unexpected response</html>",
    ])
    monkeypatch.setattr(scraper, "_fetch_ajax_payload", ajax)
    monkeypatch.setattr(scraper, "_fetch_search_html", html)
    monkeypatch.setattr(scraper, "_fetch_details", AsyncMock(return_value=None))
    assert asyncio.run(scraper.scrape(TITLE)).total_results == 0
    html.assert_not_called()
    assert asyncio.run(scraper.scrape(TITLE)).total_results == 1
    with pytest.raises(ParseError):
        asyncio.run(scraper.scrape(TITLE))


def _mock_request_redis(*states):
    admission = iter(states or [(2, 0)])

    async def evaluate(script, key_count, *args):
        return next(admission) if key_count == 3 else None

    return SimpleNamespace(eval=AsyncMock(side_effect=evaluate), zrem=AsyncMock())


@pytest.mark.parametrize(
    "status,headers,expected",
    [
        (403, {}, PermanentAccessError),
        (429, {"retry-after": "120"}, RateLimitError),
        (503, {"retry-after": "90"}, PageLoadError),
        (408, {}, RequestTimeoutError),
    ],
)
def test_access_and_transient_errors_do_not_fall_back_or_retry_in_acquisition(monkeypatch, status, headers, expected):
    request = AsyncMock(return_value=SimpleNamespace(status=status, headers=headers))

    @asynccontextmanager
    async def request_context(**kwargs):
        yield SimpleNamespace(get=request)

    redis = _mock_request_redis()
    scraper = DarazScraper(SimpleNamespace(request_context=request_context), redis)
    fallback = AsyncMock()
    monkeypatch.setattr(scraper, "_fetch_search_html", fallback)
    with pytest.raises(expected) as raised:
        asyncio.run(scraper.scrape(TITLE))
    request.assert_awaited_once()
    fallback.assert_not_awaited()
    if "retry-after" in headers:
        assert raised.value.retry_after == int(headers["retry-after"])
        assert any(call.args[-1] == raised.value.retry_after for call in redis.eval.await_args_list)


def test_browser_fallback_does_not_follow_redirects():
    page = Mock()
    route = Mock()
    route.request = SimpleNamespace(
        is_navigation_request=lambda: True, frame=page.main_frame, url="https://www.daraz.com.bd/catalog/",
    )
    route.fetch = AsyncMock(return_value=SimpleNamespace(
        status=302, headers={"location": "/customer/login"}, dispose=AsyncMock(),
    ))
    route.abort = AsyncMock()
    route.fulfill = AsyncMock()

    async def goto(*args, **kwargs):
        await page.route.await_args.args[1](route)
        raise PlaywrightTimeoutError("browser navigation aborted")

    page.route = AsyncMock()
    page.close = AsyncMock()
    page.goto = AsyncMock(side_effect=goto)

    @asynccontextmanager
    async def browser_page(**kwargs):
        yield page

    scraper = DarazScraper(SimpleNamespace(page=browser_page), _mock_request_redis())
    with pytest.raises(PermanentAccessError):
        asyncio.run(scraper._fetch_search_html("https://www.daraz.com.bd/catalog/"))
    assert route.fetch.await_args.kwargs["max_redirects"] == 0
    route.abort.assert_awaited_once()
    route.fulfill.assert_not_awaited()
    page.close.assert_awaited_once()


def test_ajax_challenge_does_not_start_browser_fallback(monkeypatch):
    response = SimpleNamespace(
        status=200, headers={}, json=AsyncMock(side_effect=ValueError),
        text=AsyncMock(return_value="<html><title>Verify you are human</title></html>"),
    )

    @asynccontextmanager
    async def request_context(**kwargs):
        yield SimpleNamespace(get=AsyncMock(return_value=response))

    scraper = DarazScraper(
        SimpleNamespace(request_context=request_context), _mock_request_redis(),
    )
    fallback = AsyncMock()
    monkeypatch.setattr(scraper, "_fetch_search_html", fallback)
    with pytest.raises(PermanentAccessError):
        asyncio.run(scraper.scrape(TITLE))
    fallback.assert_not_awaited()


def test_timeout_is_chained_and_shared_cooldown_prevents_network_calls():
    timeout = PlaywrightTimeoutError("fixture")
    request = AsyncMock(side_effect=timeout)

    @asynccontextmanager
    async def request_context(**kwargs):
        yield SimpleNamespace(get=request)

    redis = _mock_request_redis((2, 0), (0, 1001))
    scraper = DarazScraper(SimpleNamespace(request_context=request_context), redis)
    with pytest.raises(RequestTimeoutError) as raised:
        asyncio.run(scraper.scrape(TITLE))
    assert raised.value.__cause__ is timeout
    with pytest.raises(RateLimitError) as raised:
        asyncio.run(scraper.scrape(TITLE))
    assert raised.value.retry_after == 2
    request.assert_awaited_once()
    assert _retry_after_seconds("Thu, 01 Jan 1970 00:00:00 GMT") == 0
    assert _retry_after_seconds("invalid") == 0


def test_acquisition_requires_explicit_authorization(monkeypatch):
    browser = Mock()
    monkeypatch.setattr(acquisition_service.settings, "daraz_scraping_authorized", False)
    monkeypatch.setattr(acquisition_service, "BrowserManager", browser)
    with pytest.raises(PermanentAccessError):
        asyncio.run(acquisition_service.scrape_daraz_competitors(product_title=TITLE))
    browser.assert_not_called()


@pytest.fixture
def postgres_engine():
    url = os.environ.get("BAZARSYNC_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set BAZARSYNC_TEST_POSTGRES_URL for disposable PostgreSQL checks")
    admin = create_engine(url)
    schema = f"daraz_test_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        tables = [
            Seller.__table__, Product.__table__, ScrapeRun.__table__, Competitor.__table__,
            PriceHistory.__table__, CompetitorSnapshot.__table__, CompetitorEvent.__table__,
        ]
        Product.metadata.create_all(engine, tables=tables)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def db(postgres_engine, monkeypatch):
    factory = sessionmaker(postgres_engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(scraper_tasks, "SessionLocal", factory)
    monkeypatch.setattr(scraper_tasks, "engine", postgres_engine)
    monkeypatch.setattr(scraper_tasks.settings, "daraz_scraping_authorized", True)
    return factory


def _seller_product(db, status=ProductStatus.ACTIVE):
    with db.begin() as session:
        seller = Seller(email=f"{uuid4()}@example.test", password_hash="fixture")
        session.add(seller)
        session.flush()
        product = Product(
            seller_id=seller.id, title=TITLE, cost_price=10, selling_price=50, stock_quantity=1,
            supplier_lead_time=1, minimum_margin=10, status=status,
        )
        session.add(product)
        session.flush()
    return seller, product


def _enqueue(db, seller, product, **kwargs):
    with db() as session:
        return scrape_service.ScrapeService(session).enqueue_scrape(
            seller_id=seller.id, product_id=product.id, **kwargs,
        )[0]


def _worker(run, *, retries=0):
    task = scraper_tasks.run_manual_scrape_task
    task.push_request(id=run.celery_task_id, retries=retries)
    try:
        return task.run(str(run.product_id), str(run.seller_id), str(run.id))
    finally:
        task.pop_request()


def _status(db, run):
    with db() as session:
        return session.get(ScrapeRun, run.id)


def _search(*rows):
    return ScrapeResponse(
        query=TITLE, marketplace=MARKETPLACE_NAME, scraped_at=datetime.now(timezone.utc),
        total_results=len(rows), products=list(rows),
    )


def test_concurrent_admission_uses_same_run_and_terminal_runs_allow_refresh(db, monkeypatch):
    seller, product = _seller_product(db)
    publishing = threading.Event()
    release_publish = threading.Event()
    second_started = threading.Event()

    def publish(*args, **kwargs):
        publishing.set()
        assert release_publish.wait(timeout=5)

    send = Mock(side_effect=publish)
    monkeypatch.setattr(celery_app, "send_task", send)

    def submit_second():
        second_started.set()
        return _enqueue(db, seller, product, threshold=0.85)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(_enqueue, db, seller, product, threshold=0.72)
        try:
            assert publishing.wait(timeout=5)
            second = pool.submit(submit_second)
            assert second_started.wait(timeout=5)
        finally:
            release_publish.set()
        run = first.result(timeout=5)
        reused = second.result(timeout=5)

    assert (run.id, run.celery_task_id) == (reused.id, reused.celery_task_id)
    assert scrape_service.ScrapeService.run_threshold(reused) == 0.72
    send.assert_called_once()

    with db() as session:
        scrape_service.ScrapeService(session).mark_run_failed(run.id, "SCRAPE_FAILED")
    assert _enqueue(db, seller, product).id != run.id
    assert send.call_count == 2


def test_worker_can_receive_delivery_before_admission_commits(db, monkeypatch):
    seller, product = _seller_product(db)
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", AsyncMock(return_value=_search()))
    started = threading.Event()
    futures = []
    with ThreadPoolExecutor(1) as pool:
        def publish(name, *, args, task_id=None, **kwargs):
            if name == "scraper.run_manual_scrape":
                delivery = SimpleNamespace(
                    product_id=args[0], seller_id=args[1], id=args[2], celery_task_id=task_id,
                )

                def start_delivery():
                    started.set()
                    return _worker(delivery)

                futures.append(pool.submit(start_delivery))
                assert started.wait(timeout=5)

        monkeypatch.setattr(celery_app, "send_task", publish)
        run = _enqueue(db, seller, product)
        assert futures[0].result(timeout=5)["scrape_run_id"] == str(run.id)
    assert _status(db, run).status == "COMPLETED"


def test_api_contract_ownership_and_broker_failure(db, app, monkeypatch):
    seller, product = _seller_product(db)
    other, other_product = _seller_product(db)
    current_seller = [seller]

    def get_test_db():
        with db() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_seller] = lambda: current_seller[0]
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    with TestClient(app) as client:
        assert client.post(f"/api/v1/scraper/run/{other_product.id}").status_code == 403
        assert client.post(f"/api/v1/scraper/run/{product.id}?threshold=2").status_code == 422
        response = client.post(f"/api/v1/scraper/run/{product.id}?threshold=0.8", json={"seller_id": str(other.id)})
        assert response.status_code == 202
        payload = response.json()
        assert set(payload) == {"success", "task_id", "scrape_run_id", "product_id", "product_title", "threshold", "status"}
        assert send.call_args.kwargs["args"][1] == str(seller.id)
        endpoint = f"/api/v1/scraper/runs/{payload['scrape_run_id']}"
        current_seller[0] = other
        assert client.get(endpoint).status_code == 404
        current_seller[0] = seller
        assert client.get(endpoint).json()["status"] == "PENDING"

        send.side_effect = OperationalError("redis://secret")
        current_seller[0] = other
        failure = client.post(f"/api/v1/scraper/run/{other_product.id}")
        assert failure.status_code == 503
        assert "secret" not in failure.text
        with db() as session:
            run = session.scalar(select(ScrapeRun).where(ScrapeRun.product_id == other_product.id))
            assert (run.status, run.failure_code) == ("FAILED", "SCRAPE_ENQUEUE_FAILED")
            assert run.finished_at is not None
            assert run.started_at is None


@pytest.mark.parametrize(
    "error,code",
    [
        (SimilarityUnavailableError("private model path"), "SIMILARITY_UNAVAILABLE"),
        (RuntimeError("private encoding error"), "SIMILARITY_FAILED"),
    ],
)
def test_similarity_failures_are_terminal_and_do_not_dispatch_phase5(db, monkeypatch, error, code):
    seller, product = _seller_product(db)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", AsyncMock(return_value=_search()))
    monkeypatch.setattr(scrape_service, "filter_similar_products", Mock(side_effect=error))
    run = _enqueue(db, seller, product)
    with pytest.raises(scrape_service.ScrapePipelineError):
        _worker(run)
    failed = _status(db, run)
    assert (failed.status, failed.failure_code, failed.successful_matches) == ("FAILED", code, None)
    assert "private" not in failed.error_message
    send.assert_called_once()  # Admission only.


def test_zero_matches_complete_and_dispatch_phase5_without_rows(db, monkeypatch):
    seller, product = _seller_product(db)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", AsyncMock(return_value=_search()))
    run = _enqueue(db, seller, product)
    result = _worker(run)
    completed = _status(db, run)
    assert result["matched_results"] == 0
    assert (completed.status, completed.total_results, completed.successful_matches, completed.snapshot_count) == ("COMPLETED", 0, 0, 0)
    assert send.call_args.args == ("phase5.run_analysis_workflow",)


def test_transient_retry_backoff_respects_retry_after_and_exhaustion(db, monkeypatch):
    seller, product = _seller_product(db)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    error = RateLimitError("fixture", 90)
    acquire = AsyncMock(side_effect=error)
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", acquire)
    backoff = Mock(side_effect=[0, 2, 4])
    monkeypatch.setattr(scraper_tasks, "get_exponential_backoff_interval", backoff)
    retry = Mock(side_effect=Retry)
    monkeypatch.setattr(scraper_tasks.run_manual_scrape_task, "retry", retry)
    run = _enqueue(db, seller, product)
    for attempt in range(3):
        with pytest.raises(Retry):
            _worker(run, retries=attempt)
        assert retry.call_args.kwargs["countdown"] == 90
        assert retry.call_args.kwargs["exc"].__cause__ is error
        assert backoff.call_args.kwargs == {"factor": 1, "retries": attempt, "maximum": 300, "full_jitter": True}
        assert _status(db, run).status == "RUNNING"

    with pytest.raises(scrape_service.ScrapePipelineError) as raised:
        _worker(run, retries=3)
    assert raised.value.__cause__ is error
    assert acquire.await_count == 4
    assert retry.call_count == 3
    assert (_status(db, run).status, _status(db, run).failure_code) == ("FAILED", "MARKETPLACE_RATE_LIMITED")
    send.assert_called_once()


def test_retry_success_reuses_original_run_and_dispatches_analysis(db, monkeypatch):
    seller, product = _seller_product(db)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    acquire = AsyncMock(side_effect=[RequestTimeoutError("fixture"), _search()])
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", acquire)
    retry = Mock(side_effect=Retry)
    monkeypatch.setattr(scraper_tasks.run_manual_scrape_task, "retry", retry)
    monkeypatch.setattr(scraper_tasks, "get_exponential_backoff_interval", Mock(return_value=1))

    run = _enqueue(db, seller, product)
    with pytest.raises(Retry):
        _worker(run)
    assert retry.call_args.kwargs["countdown"] == 1
    assert _enqueue(db, seller, product).id == run.id
    assert _worker(run, retries=1)["scrape_run_id"] == str(run.id)
    assert _status(db, run).status == "COMPLETED"
    assert send.call_args.args == ("phase5.run_analysis_workflow",)


def test_phase5_broker_retry_does_not_repeat_completed_acquisition(db, monkeypatch):
    seller, product = _seller_product(db)
    send = Mock(side_effect=[None, OperationalError("fixture"), None])
    monkeypatch.setattr(celery_app, "send_task", send)
    acquire = AsyncMock(return_value=_search())
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", acquire)
    monkeypatch.setattr(scraper_tasks.run_manual_scrape_task, "retry", Mock(side_effect=Retry))

    run = _enqueue(db, seller, product)
    with pytest.raises(Retry):
        _worker(run)
    assert _status(db, run).status == "COMPLETED"
    _worker(run, retries=1)
    acquire.assert_awaited_once()
    assert [call.args[0] for call in send.call_args_list] == [
        "scraper.run_manual_scrape", "phase5.run_analysis_workflow", "phase5.run_analysis_workflow",
    ]


def test_retry_publish_failure_becomes_terminal(db, monkeypatch):
    seller, product = _seller_product(db)
    monkeypatch.setattr(celery_app, "send_task", Mock())
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", AsyncMock(side_effect=PageLoadError("fixture")))
    monkeypatch.setattr(scraper_tasks.run_manual_scrape_task, "retry", Mock(side_effect=Reject("broker down")))
    run = _enqueue(db, seller, product)
    with pytest.raises(Reject):
        _worker(run)
    assert (_status(db, run).status, _status(db, run).failure_code) == ("FAILED", "SCRAPE_RETRY_ENQUEUE_FAILED")


def test_duplicate_worker_delivery_does_not_acquire_twice(db, monkeypatch):
    seller, product = _seller_product(db)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    entered = threading.Event()
    release = threading.Event()

    async def search(**kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return _search()

    acquire = AsyncMock(side_effect=search)
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", acquire)
    run = _enqueue(db, seller, product)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(_worker, run)
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(Ignore, match="already in progress"):
                pool.submit(_worker, run).result(timeout=5)
        finally:
            release.set()
        first.result(timeout=5)
    _worker(run)  # A completed redelivery can dispatch Phase 5 again.
    acquire.assert_awaited_once()
    assert _status(db, run).status == "COMPLETED"


def test_periodic_selects_active_rechecks_eligibility_and_deduplicates(db, monkeypatch):
    active_seller, active_product = _seller_product(db)
    _, inactive = _seller_product(db, ProductStatus.INACTIVE)
    _, archived = _seller_product(db, ProductStatus.ARCHIVED)
    _, draft = _seller_product(db, ProductStatus.DRAFT)
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    first_key = str(uuid4())
    scraper_tasks._schedule_eligible_products(first_key)
    selected = {UUID(call.kwargs["args"][0]) for call in send.call_args_list}
    assert active_product.id in selected
    assert selected.isdisjoint({inactive.id, archived.id, draft.id})
    assert scraper_tasks._schedule_eligible_products(str(uuid4())) == {"scheduled": 0}
    with db.begin() as session:
        session.get(Product, active_product.id).status = ProductStatus.INACTIVE
    with db() as session:
        run = session.scalar(select(ScrapeRun).where(
            ScrapeRun.product_id == active_product.id, ScrapeRun.seller_id == active_seller.id,
        ))
    acquire = AsyncMock()
    monkeypatch.setattr(scrape_service, "scrape_daraz_competitors", acquire)
    with pytest.raises(Ignore):
        _worker(run)
    acquire.assert_not_called()
    assert (_status(db, run).status, _status(db, run).failure_code) == ("FAILED", "PRODUCT_INELIGIBLE")
    with db.begin() as session:
        session.get(Product, active_product.id).status = ProductStatus.ACTIVE
    send.reset_mock()
    scraper_tasks._schedule_eligible_products(first_key)
    assert all(call.kwargs["args"][0] != str(active_product.id) for call in send.call_args_list)


def test_partial_extraction_preserves_competitor_but_never_fabricates_observations(db, monkeypatch):
    seller, product = _seller_product(db)
    monkeypatch.setattr(celery_app, "send_task", Mock())
    priced = CompetitorProduct(
        product_title=TITLE, daraz_product_url=URL, search_position=1,
        product_price=250.0, rating=4.5, rating_count=10, sold_count="12", stock_status="in_stock",
        store_name="Verified Store", product_description="Verified description", product_attributes={"Material": "Metal"},
        provenance=ObservationProvenance(
            search_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    incomplete = CompetitorProduct(
        product_title=TITLE, daraz_product_url=URL, search_position=1,
        stock_status="availability uncertain", product_attributes={"Color": "Blue"},
    )
    zero = priced.model_copy(update={"product_price": Decimal("0"), "rating": 0, "rating_count": 0, "sold_count": "0", "provenance": None})
    monkeypatch.setattr(
        scrape_service, "scrape_daraz_competitors",
        AsyncMock(side_effect=[_search(priced, priced), _search(incomplete), _search(zero)]),
    )
    monkeypatch.setattr(scrape_service, "filter_similar_products", lambda **kwargs: kwargs["competitors"])
    first = _enqueue(db, seller, product)
    assert _worker(first)["matched_results"] == 1
    second = _enqueue(db, seller, product)
    _worker(second)
    with db() as session:
        competitor = session.scalar(select(Competitor).where(Competitor.product_id == product.id))
        assert (competitor.competitor_price, competitor.competitor_rating, competitor.competitor_sold) == (250, 4.5, "12")
        assert competitor.competitor_store == "Verified Store"
        assert competitor.competitor_description == "Verified description"
        assert competitor.stock_status == "in_stock"
        assert competitor.competitor_attributes == {"Material": "Metal", "Color": "Blue"}
        observed = session.scalar(select(PriceHistory).where(PriceHistory.competitor_id == competitor.id))
        assert observed.observed_at == priced.provenance.price_observed_at
        latest = session.scalar(select(CompetitorSnapshot).where(CompetitorSnapshot.scrape_run_id == second.id))
        assert (latest.price, latest.rating, latest.review_count, latest.stock_status) == (None, None, None, "UNKNOWN")
        assert session.scalar(select(func.count()).select_from(PriceHistory).where(PriceHistory.competitor_id == competitor.id)) == 1
    third = _enqueue(db, seller, product)
    _worker(third)
    with db() as session:
        competitor = session.scalar(select(Competitor).where(Competitor.product_id == product.id))
        assert (competitor.competitor_price, competitor.competitor_rating, competitor.competitor_sold) == (0, 0, "0")
        latest = session.scalar(select(CompetitorSnapshot).where(CompetitorSnapshot.scrape_run_id == third.id))
        assert (latest.price, latest.rating, latest.review_count) == (0, 0, 0)
        history = session.scalars(select(PriceHistory.observed_price).where(
            PriceHistory.competitor_id == competitor.id,
        ).order_by(PriceHistory.observed_at)).all()
        assert history == [Decimal("250.00"), Decimal("0.00")]


def test_adaptive_scheduler_uses_scoped_history_and_workload(db, monkeypatch):
    now = datetime.now(timezone.utc)
    seller, stale = _seller_product(db)
    _, fresh = _seller_product(db)
    _, failed = _seller_product(db)
    _, stable = _seller_product(db)
    _, volatile = _seller_product(db)
    _, busy = _seller_product(db)
    _, inactive = _seller_product(db, ProductStatus.INACTIVE)

    def add_run(session, product, hours, status):
        when = now - timedelta(hours=hours)
        run = ScrapeRun(
            seller_id=product.seller_id, product_id=product.id, marketplace=MARKETPLACE_NAME,
            run_key=str(uuid4()), status=status, created_at=when,
            finished_at=when if status != "PENDING" else None,
            celery_task_id=str(uuid4()) if status == "PENDING" else None,
        )
        session.add(run)
        session.flush()
        return run

    def add_competitor(session, product, run):
        competitor = Competitor(product_id=product.id, scrape_run_id=run.id, competitor_title="fixture", marketplace=MARKETPLACE_NAME)
        session.add(competitor)
        session.flush()
        return competitor

    with db.begin() as session:
        add_run(session, fresh, 2, "COMPLETED")
        add_run(session, failed, 1, "FAILED")
        add_run(session, failed, 2, "FAILED")
        add_run(session, busy, 1, "PENDING")
        add_run(session, inactive, 40, "COMPLETED")
        for hours in (7, 18, 24, 30):
            run = add_run(session, stable, hours, "COMPLETED")
            competitor = add_competitor(session, stable, run)
            session.add(CompetitorSnapshot(
                product_id=stable.id, competitor_id=competitor.id, scrape_run_id=run.id,
                price=250, currency="BDT", stock_status="IN_STOCK", captured_at=run.finished_at,
                external_listing_id="stable", content_hash=str(uuid4()),
            ))
        for hours in (4, 12, 24):
            run = add_run(session, volatile, hours, "COMPLETED")
            competitor = add_competitor(session, volatile, run)
            session.add(CompetitorEvent(
                seller_id=volatile.seller_id, product_id=volatile.id, competitor_id=competitor.id,
                scrape_run_id=run.id, event_type=CompetitorEventType.PRICE_DROP,
                severity=CompetitorEventSeverity.LOW, detected_at=run.finished_at, dedupe_key=str(uuid4()),
            ))
        # Historical garbage with a different seller must never affect this product's priority.
        session.add(ScrapeRun(
            seller_id=seller.id, product_id=fresh.id, marketplace=MARKETPLACE_NAME, run_key="foreign",
            status="FAILED", created_at=now, finished_at=now,
        ))
    with db() as session:
        assert [c.product_id for c in plan_refreshes(session, RefreshPolicy(max_in_flight=2), now)] == [stale.id]
        assert [c.product_id for c in plan_refreshes(session, RefreshPolicy(), now)] == [stale.id, volatile.id]
    monkeypatch.setenv("SCRAPER_ADAPTIVE_ENABLED", "true")
    monkeypatch.setenv("SCRAPER_REFRESH_POLICY", '{"max_in_flight": 2}')
    send = Mock()
    monkeypatch.setattr(celery_app, "send_task", send)
    assert scraper_tasks._schedule_eligible_products("adaptive-fixture") == {"scheduled": 1}
    assert scraper_tasks._schedule_eligible_products("adaptive-overlap") == {"scheduled": 0}
    assert send.call_args.kwargs["args"][0] == str(stale.id)
