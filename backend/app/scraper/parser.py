from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import urldefrag, urlsplit

from bs4 import BeautifulSoup, Tag
from pydantic import TypeAdapter

from app.scraper import selectors
from app.scraper.schemas import CompetitorProduct
from app.scraper.schemas.scraped_product import (
    DEFAULT_WEIGHTS,
    PARSER_VERSION,
    ExtractionSource,
    ProductFields,
    ScrapedProduct,
    validate_weights,
)
from app.scraper.utils import (
    is_daraz_product_url,
    normalize_sold_count,
    normalize_stock_status,
    normalize_text,
    parse_compact_number,
    parse_discount_percentage,
    parse_price,
    parse_rating,
    to_absolute_url,
)

logger = logging.getLogger(__name__)


class DarazParser:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        if weights is None:
            configured = os.getenv("SCRAPER_EXTRACTION_WEIGHTS")
            weights = (
                TypeAdapter(dict[str, float]).validate_json(configured)
                if configured is not None else DEFAULT_WEIGHTS
            )
        self.weights = validate_weights(weights).copy()
        self.raw_listing_count: int | None = None

    def parse_products(self, html: str, max_results: int | None) -> list[dict[str, Any]]:
        return [to_competitor(row).model_dump() for row in self.extract_html(html, max_results) or []]

    def parse_products_from_json(
        self, payload: dict[str, Any], max_results: int | None,
    ) -> list[dict[str, Any]] | None:
        rows = self.extract_ajax(payload, max_results)
        return None if rows is None else [to_competitor(row).model_dump() for row in rows]

    def extract_ajax(
        self, payload: dict[str, Any], max_results: int | None, *, source: ExtractionSource = "ajax",
    ) -> list[ScrapedProduct] | None:
        mods = payload.get("mods")
        items = mods.get("listItems") if isinstance(mods, dict) else None
        if payload.get("success") is False or not isinstance(items, list):
            return None
        if source == "ajax":
            self.raw_listing_count = len(items)
        results = []
        for position, item in enumerate(items[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            product = self._listing(item.get("name"), item.get("itemUrl"), position, _ajax_fields(item, source), source)
            if product is not None:
                results.append(product)
        return results if results or not items or max_results == 0 else None

    def extract_html(self, html: str, max_results: int | None) -> list[ScrapedProduct] | None:
        soup = BeautifulSoup(html, "lxml")
        structured = []
        for document in _documents(soup, selectors.JSON_LD_SELECTOR):
            for item in _json_ld_products(document, search=True):
                row = self._listing(
                    item.get("name"), _structured_url(item), len(structured) + 1,
                    _structured_fields(item), "json_ld",
                )
                if row is not None:
                    structured.append(row)
        embedded = []
        for document in _documents(soup, selectors.APPLICATION_JSON_SELECTOR):
            if isinstance(document, dict) and (rows := self.extract_ajax(document, None, source="application_json")):
                embedded.extend(rows)
        cards = self._select_cards(soup)
        self.raw_listing_count = len(cards) if not structured and not embedded else None
        visible = [
            row for position, card in enumerate(cards, start=1)
            if (row := self._parse_card(card, position)) is not None
        ]
        # Keep the highest-priority listing order and fill gaps by URL only.
        if not structured and not embedded:
            return visible[:max_results] if visible or max_results == 0 else None
        listings: dict[str, ScrapedProduct] = {}
        for rows in (structured, embedded, visible):
            for row in rows:
                key = _listing_key(row.product_url)
                prior = listings.get(key)
                listings[key] = fill_product(prior, row) if prior else row
        return [
            row.model_copy(update={"search_position": position})
            for position, row in enumerate(list(listings.values())[:max_results], start=1)
        ]

    def _listing(
        self, title: Any, url: Any, position: int, fields: ProductFields, source: ExtractionSource,
    ) -> ScrapedProduct | None:
        title = normalize_text(title)[:255]
        url = to_absolute_url(normalize_text(url))
        if not title or not is_daraz_product_url(url):
            logger.info(
                "daraz_extraction_rejected daraz_parser_version=%s source=%s position=%s status=FAILED missing=%s",
                PARSER_VERSION, source, position, "title" if not title else "product_url",
            )
            return None
        return ScrapedProduct(
            **fields.model_dump(), field_sources={**fields.field_sources, "title": source, "product_url": source},
            title=title, product_url=url, search_position=position,
        )

    def _select_cards(self, soup: BeautifulSoup) -> list[Tag]:
        for selector in selectors.PRODUCT_CARD_SELECTORS:
            if cards := soup.select(selector):
                return cards
        return []

    def _parse_card(self, card: Tag, position: int) -> ScrapedProduct | None:
        # Resolve a product link first so a store/promotion anchor cannot supply its title.
        for selector in selectors.PRODUCT_LINK_SELECTORS:
            for link in card.select(selector):
                url = _attr(link, "href")
                if is_daraz_product_url(to_absolute_url(url)):
                    title = _attr(link, "title") or link.get_text(" ", strip=True)
                    if not title:
                        title = _attr(link.select_one("img"), "alt")
                    if not title:
                        for group in selectors.PRODUCT_TITLE_SELECTORS:
                            title = next((
                                node.get_text(" ", strip=True)
                                for node in card.select(group)
                                if _listing_key(to_absolute_url(_attr(node, "href"))) == _listing_key(to_absolute_url(url))
                                and node.get_text(" ", strip=True)
                            ), "")
                            if title:
                                break
                    image = _select_first(card, selectors.IMAGE_SELECTORS)
                    fields = {
                        key: _select_text(card, group, validate=_NUMERIC_CARD_FIELDS.get(key))
                        for key, group in selectors.CARD_FIELD_SELECTORS.items()
                    }
                    fields["image_url"] = _attr(image, "data-src") or _attr(image, "src")
                    return self._listing(title, url, position, _normalize(fields, "html"), "html")
        return self._listing(None, None, position, ProductFields(), "html")

    def parse_product_detail(self, html: str) -> dict[str, Any]:
        fields = self.extract_detail(html, "")
        return {
            "product_description": fields.description or "",
            "product_category": fields.category or "",
            "product_brand": fields.brand or "",
            "product_attributes": fields.specifications,
        }

    def extract_detail(self, html: str, url: str) -> ProductFields:
        soup = BeautifulSoup(html, "lxml")
        fields = ProductFields()
        for document in _documents(soup, selectors.JSON_LD_SELECTOR):
            for item in _json_ld_products(document, search=False):
                candidate_url = to_absolute_url(normalize_text(_structured_url(item)))
                if candidate_url and _listing_key(candidate_url) == _listing_key(url):
                    fields = fill_product(fields, _structured_fields(item))
                elif (
                    not candidate_url and isinstance(document, dict) and item is document
                ):
                    # A top-level Product may omit its URL. Limit it to nonfinancial metadata.
                    metadata = _structured_fields(item, include_offer=False)
                    fields = fill_product(fields, metadata)
        for document in _documents(soup, selectors.APPLICATION_JSON_SELECTOR):
            if isinstance(document, dict) and (rows := self.extract_ajax(document, None, source="application_json")):
                for row in rows:
                    if _listing_key(row.product_url) == _listing_key(url):
                        fields = fill_product(fields, row)
        return fill_product(fields, self._html_detail(soup))

    @staticmethod
    def _html_detail(soup: BeautifulSoup) -> ProductFields:
        specifications = {}
        for selector in selectors.DETAIL_SPEC_SECTION_SELECTORS:
            for section in soup.select(selector):
                for row in section.select(",".join(selectors.DETAIL_SPEC_ROW_SELECTORS)):
                    key = _select_text(row, selectors.DETAIL_SPEC_KEY_SELECTORS)
                    value = _select_text(row, selectors.DETAIL_SPEC_VALUE_SELECTORS)
                    if not key or not value:
                        key, _, value = normalize_text(row.get_text(" ", strip=True)).partition(":")
                    if key.strip() and value.strip():
                        specifications.setdefault(key.strip(), value.strip())
            if specifications:
                break
        breadcrumbs = []
        for selector in selectors.DETAIL_BREADCRUMB_SELECTORS:
            breadcrumbs = [text for node in soup.select(selector) if (text := node.get_text(" ", strip=True))]
            if breadcrumbs:
                break
        folded_specs = {key.casefold(): value for key, value in specifications.items()}
        return _normalize({
            "description": _select_text(soup, selectors.DETAIL_DESCRIPTION_SELECTORS),
            "specifications": specifications,
            "brand": _select_text(soup, selectors.DETAIL_BRAND_SELECTORS) or folded_specs.get("brand"),
            "category": (breadcrumbs[-2] if len(breadcrumbs) > 1 else next(iter(breadcrumbs), None))
            or folded_specs.get("category"),
        }, "html")


def _ajax_fields(item: dict[str, Any], source: ExtractionSource) -> ProductFields:
    stock = item.get("inStock")
    return _normalize({
        "current_price": item.get("price"), "current_price_display": item.get("priceShow"),
        "original_price": item.get("originalPrice"), "original_price_display": item.get("originalPriceShow"),
        "currency": item.get("currency"), "discount_percentage": item.get("discount"),
        "seller_name": item.get("sellerName"), "rating": item.get("ratingScore"), "review_count": item.get("review"),
        "sold_label": item.get("itemSoldCntShow"), "sold_label_display": item.get("soldCount"),
        "stock_text": "in_stock" if stock is True else "out_of_stock" if stock is False else item.get("stockStatus"),
        "image_url": item.get("image"), "description": item.get("description"),
        "brand": item.get("brand"), "category": item.get("category"), "specifications": item.get("specifications"),
    }, source)


def _normalize(raw: dict[str, Any], source: ExtractionSource) -> ProductFields:
    currency = normalize_text(raw.get("currency")).upper()
    valid_currency = not currency or currency in {"BDT", "TK", "৳"}
    sold = normalize_sold_count(_scalar(raw.get("sold_label")))
    if sold is None:
        sold = normalize_sold_count(_scalar(raw.get("sold_label_display")))
    prices = {}
    for field in ("current_price", "original_price"):
        price = parse_price(_scalar(raw.get(field))) if valid_currency else None
        if price is None and valid_currency:
            price = parse_price(_scalar(raw.get(f"{field}_display")))
        prices[field] = price
    if any(value is not None for value in prices.values()):
        currency = "BDT"
    else:
        currency = "BDT" if currency and valid_currency else None
    stock_text = normalize_text(raw.get("stock_text"))
    stock_status = normalize_stock_status(stock_text)
    image_url = to_absolute_url(normalize_text(raw.get("image_url")))
    if image_url:
        parsed = urlsplit(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            image_url = ""
    specs = raw.get("specifications")
    data = {
        **prices,
        "currency": currency,
        "discount_percentage": parse_discount_percentage(_scalar(raw.get("discount_percentage"))),
        "seller_name": normalize_text(raw.get("seller_name"))[:255] or None,
        "rating": parse_rating(_scalar(raw.get("rating"))),
        "review_count": parse_compact_number(_scalar(raw.get("review_count"))),
        "sold_count": parse_compact_number(sold),
        "sold_label": sold[:50] if sold is not None else None,
        "stock_status": stock_status,
        "stock_text": stock_text[:50] or None,
        "image_url": image_url or None,
        "brand": normalize_text(raw.get("brand"))[:120] or None,
        "category": normalize_text(raw.get("category"))[:120] or None,
        "description": normalize_text(raw.get("description")) or None,
        "specifications": {
            key: value for k, v in specs.items()
            if (key := normalize_text(k)) and (value := normalize_text(_scalar(v)))
        } if isinstance(specs, dict) else {},
    }
    for key in ("current_price", "original_price", "rating", "review_count", "discount_percentage"):
        if data[key] is None and _scalar(raw.get(key)):
            logger.debug("daraz_field_unavailable daraz_parser_version=%s source=%s field=%s", PARSER_VERSION, source, key)
    return ProductFields(**data, field_sources={
        key: source for key, value in data.items() if value is not None and value != "UNKNOWN" and value != {}
    })


def _documents(soup: BeautifulSoup, selector: str) -> Iterator[Any]:
    for script in soup.select(selector):
        try:
            yield json.loads(script.string or "", parse_float=Decimal)
        except (ValueError, RecursionError):
            logger.debug("daraz_structured_data_invalid daraz_parser_version=%s", PARSER_VERSION)


def _json_ld_products(value: Any, *, search: bool, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth >= 12:
        return
    if isinstance(value, list):
        for item in value:
            yield from _json_ld_products(item, search=search, depth=depth + 1)
    if isinstance(value, dict):
        types = value.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(kind in {"Product", "https://schema.org/Product"} for kind in types if isinstance(kind, str)):
            yield value
        for key in ("@graph", "mainEntity", "itemListElement", "item") if search else ("@graph", "mainEntity"):
            if key in value:
                yield from _json_ld_products(value[key], search=search, depth=depth + 1)


def _structured_url(item: dict[str, Any]) -> Any:
    offer = item.get("offers")
    return item.get("url") or (offer.get("url") if isinstance(offer, dict) else None)


def _structured_fields(item: dict[str, Any], *, include_offer: bool = True) -> ProductFields:
    offer = item.get("offers") if include_offer else None
    offer = offer if isinstance(offer, dict) and offer.get("@type") not in ("AggregateOffer", "https://schema.org/AggregateOffer") else {}
    offer_url = normalize_text(offer.get("url"))
    product_url = normalize_text(item.get("url"))
    if offer_url and product_url and _listing_key(to_absolute_url(offer_url)) != _listing_key(to_absolute_url(product_url)):
        offer = {}
    aggregate = item.get("aggregateRating") if include_offer else None
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    brand = item.get("brand")
    seller = offer.get("seller")
    image = item.get("image")
    if isinstance(image, list):
        image = next((value for value in image if isinstance(value, str)), None)
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    availability = {
        "InStock": "in_stock", "OutOfStock": "out_of_stock", "SoldOut": "out_of_stock",
        "LimitedAvailability": "low stock",
    }.get(normalize_text(offer.get("availability")).rsplit("/", 1)[-1])
    specs = item.get("additionalProperty")
    identifiers = {
        key: item[key] for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "ean", "upc", "isbn", "mpn", "model")
        if isinstance(item.get(key), (str, int)) and not isinstance(item[key], bool)
    }
    attributes = {
        prop["name"]: prop.get("value") for prop in specs
        if isinstance(prop, dict) and isinstance(prop.get("name"), str)
    } if isinstance(specs, list) else {}
    return _normalize({
        "current_price": offer.get("price"), "currency": offer.get("priceCurrency"),
        "stock_text": availability,
        "seller_name": seller.get("name") if isinstance(seller, dict) else seller,
        "rating": aggregate.get("ratingValue"), "review_count": aggregate.get("reviewCount"),
        "image_url": image, "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "category": item.get("category"), "description": item.get("description"),
        "specifications": {**identifiers, **attributes} if include_offer else attributes,
    }, "json_ld")


def fill_product[T: ProductFields](primary: T, fallback: ProductFields) -> T:
    updates = {}
    for key in ProductFields.model_fields:
        if key == "field_sources":
            continue
        current, value = getattr(primary, key), getattr(fallback, key)
        if key == "specifications":
            merged = {name.casefold(): (name, val) for name, val in value.items()}
            merged.update({name.casefold(): (name, val) for name, val in current.items()})
            if merged:
                updates[key] = dict(merged.values())
        elif current in (None, "UNKNOWN") and value not in (None, "UNKNOWN"):
            updates[key] = value
    if primary.stock_status == "UNKNOWN" and fallback.stock_status != "UNKNOWN":
        updates["stock_text"] = fallback.stock_text
    updates["field_sources"] = {
        **primary.field_sources,
        **{key: fallback.field_sources[key] for key in updates if key in fallback.field_sources
           and (key != "specifications" or not primary.specifications)},
    }
    return primary.model_copy(update=updates)


def to_competitor(product: ScrapedProduct, **metadata: Any) -> CompetitorProduct:
    stock = product.stock_text or ""
    if product.stock_status != "UNKNOWN":
        stock = stock or product.stock_status.lower()
    return CompetitorProduct(
        product_title=product.title, daraz_product_url=product.product_url, search_position=product.search_position,
        product_price=product.current_price, original_price=product.original_price,
        discount_percentage=product.discount_percentage, store_name=product.seller_name or "",
        rating=product.rating, rating_count=product.review_count, sold_count=product.sold_label,
        stock_status=stock, product_image_url=product.image_url or "", product_brand=product.brand or "",
        product_category=product.category or "", product_description=product.description or "",
        product_attributes=product.specifications, **metadata,
    )


def _listing_key(url: str) -> str:
    return urldefrag(url).url


def _scalar(value: Any) -> str | None:
    if isinstance(value, Decimal):
        if not value.is_finite() or not -20 <= value.adjusted() <= 20:
            return None
        return format(value, "f")
    return str(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def _select_first(root: Tag, group: list[str]) -> Tag | None:
    return next((node for selector in group if (node := root.select_one(selector)) is not None), None)


_NUMERIC_CARD_FIELDS = {
    "current_price": parse_price,
    "original_price": parse_price,
    "discount_percentage": parse_discount_percentage,
    "rating": parse_rating,
    "review_count": parse_compact_number,
    "sold_label": normalize_sold_count,
}


def _select_text(
    root: Tag, group: list[str], *, validate: Callable[[str], object] | None = None,
) -> str:
    for selector in group:
        for node in root.select(selector):
            if text := normalize_text(node.get_text(" ", strip=True)):
                if validate is None or validate(text) is not None:
                    return text
    return ""


def _attr(node: Tag | None, name: str) -> str:
    return normalize_text(node.get(name)) if node is not None else ""
