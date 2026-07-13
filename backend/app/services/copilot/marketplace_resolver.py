from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import ProductMarketplaceListing
from app.services.copilot.entity_resolver import EntityConfidence, EntityMatch, EntityResolution, contains_normalized_phrase, normalize_entity_text


MARKETPLACE_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("daraz", "daraz bangladesh", "দারাজ"),
    ("shopify", "শপিফাই"),
    ("facebook marketplace", "facebook shop", "ফেসবুক মার্কেটপ্লেস"),
    ("amazon", "অ্যামাজন"),
)


@dataclass(frozen=True, slots=True)
class MarketplaceCandidate:
    canonical_value: str


class MarketplaceResolver:
    def __init__(self, *, db: Session | None = None, marketplaces: list[str] | None = None) -> None:
        self._db = db
        self._marketplaces = marketplaces

    def resolve(self, *, seller_id: UUID, query_text: str) -> EntityResolution:
        candidates = self._list_marketplaces(seller_id=seller_id)
        matches = []
        for candidate in candidates:
            canonical = normalize_entity_text(candidate.canonical_value)
            aliases = _aliases_for_canonical(canonical)
            if contains_normalized_phrase(query_text, canonical) or any(contains_normalized_phrase(query_text, alias) for alias in aliases):
                matches.append(candidate)
        entity_matches = [EntityMatch(id=item.canonical_value, canonical_value=item.canonical_value, match_type="REGISTERED_MARKETPLACE", score=1.0) for item in matches]
        if len(entity_matches) > 1:
            names = ", ".join(item.canonical_value for item in entity_matches[:5])
            return EntityResolution("MARKETPLACE", query_text, entity_matches[:5], confidence=EntityConfidence.LOW, ambiguous=True, clarification_question=f"Which marketplace do you mean: {names}?")
        if entity_matches:
            return EntityResolution("MARKETPLACE", query_text, entity_matches, selected_id=entity_matches[0].id, confidence=EntityConfidence.HIGH)
        return EntityResolution(entity_type="MARKETPLACE", query_text=query_text)

    def has_explicit_mention(self, query_text: str) -> bool:
        normalized = normalize_entity_text(query_text)
        return any(contains_normalized_phrase(normalized, alias) for group in MARKETPLACE_ALIAS_GROUPS for alias in group)

    def _list_marketplaces(self, *, seller_id: UUID) -> list[MarketplaceCandidate]:
        if self._marketplaces is not None:
            values = self._marketplaces
        elif self._db is None:
            values = []
        else:
            values = self._db.execute(
                select(ProductMarketplaceListing.marketplace)
                .where(ProductMarketplaceListing.seller_id == seller_id)
                .distinct()
                .order_by(ProductMarketplaceListing.marketplace)
            ).scalars().all()
        deduped = {normalize_entity_text(value): str(value) for value in values if normalize_entity_text(value)}
        return [MarketplaceCandidate(value) for _, value in sorted(deduped.items())]


def _aliases_for_canonical(canonical: str) -> set[str]:
    aliases = {canonical}
    for group in MARKETPLACE_ALIAS_GROUPS:
        normalized_group = {normalize_entity_text(item) for item in group}
        if canonical in normalized_group or any(item in canonical or canonical in item for item in normalized_group):
            aliases.update(normalized_group)
    return aliases
