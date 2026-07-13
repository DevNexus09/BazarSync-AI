from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.product import Product
from app.services.copilot.entity_resolver import EntityConfidence, EntityMatch, EntityResolution, contains_normalized_phrase, entity_tokens, normalize_entity_text


@dataclass(frozen=True, slots=True)
class CompetitorCandidate:
    id: UUID
    name: str
    store_name: str | None
    product_id: UUID
    product_title: str
    product_url: str | None
    marketplace: str | None


class CompetitorResolver:
    def __init__(self, *, db: Session | None = None, competitors: list[CompetitorCandidate] | None = None) -> None:
        self._db = db
        self._competitors = competitors

    def resolve(self, *, seller_id: UUID, query_text: str) -> EntityResolution:
        candidates = self._list_competitors(seller_id=seller_id)
        if not candidates:
            return _empty(query_text)
        strategies = (
            ("COMPETITOR_ID", lambda item: contains_normalized_phrase(query_text, str(item.id)), 1.0),
            ("EXACT_NAME", lambda item: contains_normalized_phrase(query_text, item.name) or contains_normalized_phrase(query_text, item.store_name), 0.99),
            ("LISTING_DOMAIN", lambda item: _url_matches(query_text, item.product_url), 0.97),
            ("ASSOCIATED_PRODUCT", lambda item: contains_normalized_phrase(query_text, item.product_title), 0.90),
        )
        for match_type, predicate, score in strategies:
            matches = [_match(item, match_type, score) for item in candidates if predicate(item)]
            if matches:
                return _select_or_ambiguous(query_text, matches, EntityConfidence.HIGH)

        query_tokens = entity_tokens(query_text)
        fuzzy = []
        for candidate in candidates:
            candidate_text = " ".join(filter(None, (candidate.name, candidate.store_name)))
            overlap = len(query_tokens & entity_tokens(candidate_text)) / max(1, len(entity_tokens(candidate_text)))
            sequence = SequenceMatcher(None, normalize_entity_text(query_text), normalize_entity_text(candidate_text)).ratio()
            score = round(max(overlap, sequence * 0.75), 4)
            if overlap >= 0.5 or sequence >= 0.72:
                fuzzy.append(_match(candidate, "FUZZY_NAME", score))
        return _select_or_ambiguous(query_text, fuzzy, EntityConfidence.MEDIUM) if fuzzy else _empty(query_text)

    def has_explicit_mention(self, query_text: str) -> bool:
        normalized = normalize_entity_text(query_text)
        return any(token in normalized.split() for token in ("competitor", "competitors", "প্রতিযোগী"))

    def _list_competitors(self, *, seller_id: UUID) -> list[CompetitorCandidate]:
        if self._competitors is not None:
            return list(self._competitors)
        if self._db is None:
            return []
        rows = self._db.execute(
            select(Competitor, Product.title)
            .join(Product, Product.id == Competitor.product_id)
            .where(Product.seller_id == seller_id)
            .order_by(Competitor.created_at.desc(), Competitor.id.desc())
            .limit(2000)
        ).all()
        return [
            CompetitorCandidate(
                id=competitor.id,
                name=competitor.competitor_title,
                store_name=competitor.competitor_store,
                product_id=competitor.product_id,
                product_title=product_title,
                product_url=competitor.product_url,
                marketplace=competitor.marketplace,
            )
            for competitor, product_title in rows
        ]


def _url_matches(query_text: str, product_url: str | None) -> bool:
    if not product_url:
        return False
    domain = (urlparse(product_url).hostname or "").removeprefix("www.")
    return contains_normalized_phrase(query_text, product_url) or contains_normalized_phrase(query_text, domain)


def _match(candidate: CompetitorCandidate, match_type: str, score: float) -> EntityMatch:
    return EntityMatch(
        id=str(candidate.id),
        canonical_value=candidate.store_name or candidate.name,
        match_type=match_type,
        score=score,
        metadata={
            "competitor_title": candidate.name,
            "product_id": str(candidate.product_id),
            "product_title": candidate.product_title,
            "marketplace": candidate.marketplace,
        },
    )


def _select_or_ambiguous(query_text: str, matches: list[EntityMatch], confidence: EntityConfidence) -> EntityResolution:
    matches.sort(key=lambda item: (-item.score, item.canonical_value.casefold(), item.id))
    strongest = [item for item in matches if item.score == matches[0].score]
    if len(strongest) > 1:
        names = ", ".join(item.canonical_value for item in strongest[:5])
        return EntityResolution("COMPETITOR", query_text, strongest[:5], confidence=EntityConfidence.LOW, ambiguous=True, clarification_question=f"Which competitor do you mean: {names}?")
    return EntityResolution("COMPETITOR", query_text, matches[:5], selected_id=matches[0].id, confidence=confidence)


def _empty(query_text: str) -> EntityResolution:
    return EntityResolution(entity_type="COMPETITOR", query_text=query_text)
