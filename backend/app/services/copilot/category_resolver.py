from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductMarketplaceListing
from app.services.copilot.entity_resolver import EntityConfidence, EntityMatch, EntityResolution, contains_normalized_phrase, normalize_entity_text


CATEGORY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("electronics", "electronic", "ইলেকট্রনিক্স"),
    ("fashion", "clothing", "apparel", "পোশাক", "ফ্যাশন"),
    ("grocery", "groceries", "food", "মুদি", "খাদ্য"),
    ("beauty", "personal care", "সৌন্দর্য", "ব্যক্তিগত যত্ন"),
    ("home", "home living", "household", "ঘর", "গৃহস্থালি"),
    ("mobile accessories", "phone accessories", "মোবাইল এক্সেসরিজ", "মোবাইল আনুষঙ্গিক"),
)


@dataclass(frozen=True, slots=True)
class CategoryCandidate:
    canonical_value: str


class CategoryResolver:
    def __init__(self, *, db: Session | None = None, categories: list[str] | None = None) -> None:
        self._db = db
        self._categories = categories

    def resolve(self, *, seller_id: UUID, query_text: str) -> EntityResolution:
        candidates = self._list_categories(seller_id=seller_id)
        direct = [candidate for candidate in candidates if contains_normalized_phrase(query_text, candidate.canonical_value)]
        if direct:
            return _result(query_text, direct, "EXACT_CATEGORY", EntityConfidence.HIGH)

        normalized_query = normalize_entity_text(query_text)
        alias_matches: list[CategoryCandidate] = []
        for candidate in candidates:
            canonical = normalize_entity_text(candidate.canonical_value)
            for group in CATEGORY_ALIAS_GROUPS:
                normalized_group = {normalize_entity_text(item) for item in group}
                if canonical in normalized_group and any(contains_normalized_phrase(normalized_query, alias) for alias in normalized_group):
                    alias_matches.append(candidate)
                    break
        return _result(query_text, alias_matches, "CATEGORY_ALIAS", EntityConfidence.MEDIUM) if alias_matches else _empty(query_text)

    def has_explicit_mention(self, query_text: str) -> bool:
        normalized = normalize_entity_text(query_text)
        aliases = {normalize_entity_text(alias) for group in CATEGORY_ALIAS_GROUPS for alias in group}
        return "category" in normalized.split() or "ক্যাটাগরি" in normalized.split() or any(contains_normalized_phrase(normalized, alias) for alias in aliases)

    def _list_categories(self, *, seller_id: UUID) -> list[CategoryCandidate]:
        if self._categories is not None:
            values = self._categories
        elif self._db is None:
            values = []
        else:
            product_values = self._db.execute(select(Product.category).where(Product.seller_id == seller_id, Product.category.is_not(None)).distinct()).scalars().all()
            listing_values = self._db.execute(
                select(ProductMarketplaceListing.category_on_marketplace)
                .where(ProductMarketplaceListing.seller_id == seller_id, ProductMarketplaceListing.category_on_marketplace.is_not(None))
                .distinct()
            ).scalars().all()
            values = [*product_values, *listing_values]
        deduped = {normalize_entity_text(value): str(value) for value in values if normalize_entity_text(value)}
        return [CategoryCandidate(value) for _, value in sorted(deduped.items())]


def _result(query_text: str, candidates: list[CategoryCandidate], match_type: str, confidence: EntityConfidence) -> EntityResolution:
    matches = [EntityMatch(id=item.canonical_value, canonical_value=item.canonical_value, match_type=match_type, score=1.0) for item in candidates]
    if len(matches) > 1:
        names = ", ".join(item.canonical_value for item in matches[:5])
        return EntityResolution("CATEGORY", query_text, matches[:5], confidence=EntityConfidence.LOW, ambiguous=True, clarification_question=f"Which category do you mean: {names}?")
    return EntityResolution("CATEGORY", query_text, matches, selected_id=matches[0].id, confidence=confidence) if matches else _empty(query_text)


def _empty(query_text: str) -> EntityResolution:
    return EntityResolution(entity_type="CATEGORY", query_text=query_text)
