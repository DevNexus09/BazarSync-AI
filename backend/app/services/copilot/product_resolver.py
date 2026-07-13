from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.product import Product
from app.services.copilot.entity_resolver import (
    EntityConfidence,
    EntityMatch,
    EntityResolution,
    ProductEntityCandidate,
    contains_normalized_phrase,
    entity_tokens,
    normalize_entity_text,
)


class ProductEntitySource(Protocol):
    def list_products(self, *, seller_id: UUID, limit: int = 1000) -> list[ProductEntityCandidate]: ...


class SqlAlchemyProductEntitySource:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_products(self, *, seller_id: UUID, limit: int = 1000) -> list[ProductEntityCandidate]:
        rows = self._db.execute(
            select(Product)
            .options(selectinload(Product.marketplace_listings))
            .where(Product.seller_id == seller_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
            .limit(limit)
        ).scalars().all()
        return [
            ProductEntityCandidate(
                id=row.id,
                title=row.title,
                category=row.category,
                searchable_text=row.searchable_text,
                sku=row.sku,
                marketplace_listing_ids=tuple(item.marketplace_listing_id for item in row.marketplace_listings if item.marketplace_listing_id),
                listing_titles=tuple(item.title_on_marketplace for item in row.marketplace_listings if item.title_on_marketplace),
                aliases=_product_aliases(row),
            )
            for row in rows
        ]

    def get_product(self, *, seller_id: UUID, product_id: UUID) -> ProductEntityCandidate | None:
        row = self._db.execute(
            select(Product)
            .options(selectinload(Product.marketplace_listings))
            .where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return ProductEntityCandidate(
            id=row.id,
            title=row.title,
            category=row.category,
            searchable_text=row.searchable_text,
            sku=row.sku,
            marketplace_listing_ids=tuple(item.marketplace_listing_id for item in row.marketplace_listings if item.marketplace_listing_id),
            listing_titles=tuple(item.title_on_marketplace for item in row.marketplace_listings if item.title_on_marketplace),
            aliases=_product_aliases(row),
        )


class ProductResolver:
    def __init__(self, *, source: ProductEntitySource | None = None) -> None:
        self._source = source

    def resolve(self, *, seller_id: UUID, query_text: str, product_id: UUID | None = None) -> EntityResolution:
        if self._source is None:
            return _empty(query_text)
        if product_id is not None:
            candidate = self._get_owned_product(seller_id=seller_id, product_id=product_id)
            if candidate is None:
                return _empty(query_text)
            return _selected(query_text, candidate, "PRODUCT_ID", EntityConfidence.HIGH, 1.0)

        products = self._source.list_products(seller_id=seller_id)
        if not products:
            return _empty(query_text)
        priority_matches = self._priority_matches(query_text=query_text, products=products)
        if not priority_matches:
            return _empty(query_text)
        priority, matches = priority_matches
        matches.sort(key=lambda item: (-item.score, item.canonical_value.casefold(), item.id))
        strongest = [item for item in matches if item.score == matches[0].score]
        if len(strongest) > 1:
            names = ", ".join(item.canonical_value for item in strongest[:5])
            return EntityResolution(
                entity_type="PRODUCT",
                query_text=query_text,
                matches=strongest[:5],
                confidence=EntityConfidence.LOW,
                ambiguous=True,
                clarification_question=f"Which product do you mean: {names}?",
            )
        confidence = EntityConfidence.HIGH if priority <= 5 else EntityConfidence.MEDIUM
        return EntityResolution(
            entity_type="PRODUCT",
            query_text=query_text,
            matches=matches[:5],
            selected_id=matches[0].id,
            confidence=confidence,
        )

    def _get_owned_product(self, *, seller_id: UUID, product_id: UUID) -> ProductEntityCandidate | None:
        source = self._source
        if source is None:
            return None
        getter = getattr(source, "get_product", None)
        if callable(getter):
            return getter(seller_id=seller_id, product_id=product_id)
        # Test and in-memory sources may only implement list_products; ownership is still checked against that list.
        products = source.list_products(seller_id=seller_id)
        return next((item for item in products if item.id == product_id), None)

    def _priority_matches(self, *, query_text: str, products: list[ProductEntityCandidate]) -> tuple[int, list[EntityMatch]] | None:
        normalized_query = normalize_entity_text(query_text)
        uuid_values = {match.group(0).lower() for match in re.finditer(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}\b", query_text)}
        strategies = (
            (1, "PRODUCT_ID", lambda product: str(product.id).lower() in uuid_values, 1.0),
            (2, "EXACT_SKU", lambda product: contains_normalized_phrase(normalized_query, product.sku), 0.99),
            (3, "EXACT_NAME", lambda product: contains_normalized_phrase(normalized_query, product.title), 0.98),
            (4, "LISTING_ID", lambda product: any(contains_normalized_phrase(normalized_query, value) for value in product.marketplace_listing_ids), 0.97),
            (5, "KNOWN_ALIAS", lambda product: any(contains_normalized_phrase(normalized_query, value) for value in (*product.aliases, *product.listing_titles)), 0.95),
        )
        for priority, match_type, predicate, score in strategies:
            matches = [_match(product, match_type, score) for product in products if predicate(product)]
            if matches:
                return priority, matches

        fuzzy = []
        query_tokens = entity_tokens(normalized_query)
        for product in products:
            title = normalize_entity_text(product.title)
            title_tokens = entity_tokens(title)
            shared_tokens = query_tokens & title_tokens
            overlap = len(shared_tokens) / max(1, len(title_tokens))
            sequence = SequenceMatcher(None, normalized_query, title).ratio()
            score = round(max(overlap, sequence * 0.75), 4)
            distinctive_token_match = any(len(token) >= 4 and token not in {"product", "item", "show", "which"} for token in shared_tokens)
            if distinctive_token_match or sequence >= 0.82:
                fuzzy.append(_match(product, "TOKEN_FUZZY", score))
        return (6, fuzzy) if fuzzy else None


def _product_aliases(product: Product) -> tuple[str, ...]:
    specifications = product.specifications if isinstance(product.specifications, dict) else {}
    aliases = specifications.get("aliases") or specifications.get("alias")
    if isinstance(aliases, str):
        return tuple(item.strip() for item in re.split(r"[,;|]", aliases) if item.strip())
    if isinstance(aliases, list):
        return tuple(str(item).strip() for item in aliases if str(item).strip())
    return ()


def _match(product: ProductEntityCandidate, match_type: str, score: float) -> EntityMatch:
    return EntityMatch(
        id=str(product.id),
        canonical_value=product.title,
        match_type=match_type,
        score=score,
        metadata={"sku": product.sku, "category": product.category},
    )


def _selected(query_text: str, product: ProductEntityCandidate, match_type: str, confidence: EntityConfidence, score: float) -> EntityResolution:
    match = _match(product, match_type, score)
    return EntityResolution(entity_type="PRODUCT", query_text=query_text, matches=[match], selected_id=match.id, confidence=confidence)


def _empty(query_text: str) -> EntityResolution:
    return EntityResolution(entity_type="PRODUCT", query_text=query_text)
