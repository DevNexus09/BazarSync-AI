from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import unicodedata
from typing import Any, Protocol
from uuid import UUID


class EntityConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class EntityMatch:
    id: str
    canonical_value: str
    match_type: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_value": self.canonical_value,
            "match_type": self.match_type,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class EntityResolution:
    entity_type: str
    query_text: str
    matches: list[EntityMatch] = field(default_factory=list)
    selected_id: str | None = None
    confidence: EntityConfidence = EntityConfidence.NONE
    ambiguous: bool = False
    clarification_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "query_text": self.query_text,
            "matches": [match.to_dict() for match in self.matches],
            "selected_id": self.selected_id,
            "confidence": self.confidence.value,
            "ambiguous": self.ambiguous,
            "clarification_question": self.clarification_question,
        }


@dataclass(frozen=True, slots=True)
class ProductEntityCandidate:
    id: UUID
    title: str
    category: str | None = None
    searchable_text: str | None = None
    sku: str | None = None
    marketplace_listing_ids: tuple[str, ...] = ()
    listing_titles: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedProductEntity:
    text: str
    product_id: UUID | None = None
    title: str | None = None
    matched_products: list[dict[str, str]] = field(default_factory=list)
    confidence: str = "LOW"

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "product_id": str(self.product_id) if self.product_id else None,
            "title": self.title,
            "matched_products": self.matched_products,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class EntityResolutionResult:
    products: list[ResolvedProductEntity]
    categories: list[str]
    marketplaces: list[str]
    competitors: list[str]
    clarification_question: str | None = None
    product_resolution: EntityResolution | None = None
    category_resolution: EntityResolution | None = None
    marketplace_resolution: EntityResolution | None = None
    competitor_resolution: EntityResolution | None = None
    missing_data: list[str] = field(default_factory=list)
    explicit_entity_types: frozenset[str] = frozenset()
    inherited_competitor_ids: tuple[str, ...] = ()

    @property
    def competitor_ids(self) -> list[str]:
        resolution = self.competitor_resolution
        return [resolution.selected_id] if resolution and resolution.selected_id else list(self.inherited_competitor_ids)


class ProductEntitySource(Protocol):
    def list_products(self, *, seller_id: UUID, limit: int = 1000) -> list[ProductEntityCandidate]: ...


BANGLA_DIGIT_TRANSLATION = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
WORD_RE = re.compile(r"[a-z0-9\u0980-\u09FF]+", re.IGNORECASE)


def normalize_entity_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").translate(BANGLA_DIGIT_TRANSLATION).casefold()
    characters = [character if character.isalnum() or "\u0980" <= character <= "\u09ff" else " " for character in normalized]
    return " ".join("".join(characters).split())


def entity_tokens(value: str | None) -> set[str]:
    return {match.group(0).casefold() for match in WORD_RE.finditer(normalize_entity_text(value)) if len(match.group(0)) > 1}


def contains_normalized_phrase(question: str, phrase: str | None) -> bool:
    normalized_phrase = normalize_entity_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalize_entity_text(question)} "


class CopilotEntityResolver:
    def __init__(
        self,
        *,
        product_source: ProductEntitySource | None = None,
        product_resolver: Any | None = None,
        category_resolver: Any | None = None,
        marketplace_resolver: Any | None = None,
        competitor_resolver: Any | None = None,
        db: Any | None = None,
    ) -> None:
        # Local imports keep the shared result schema independent from SQLAlchemy.
        from app.services.copilot.category_resolver import CategoryResolver
        from app.services.copilot.competitor_resolver import CompetitorResolver
        from app.services.copilot.marketplace_resolver import MarketplaceResolver
        from app.services.copilot.product_resolver import ProductResolver, SqlAlchemyProductEntitySource

        if product_source is None and db is not None:
            product_source = SqlAlchemyProductEntitySource(db)
        self._product_resolver = product_resolver or ProductResolver(source=product_source)
        self._category_resolver = category_resolver or CategoryResolver(db=db)
        self._marketplace_resolver = marketplace_resolver or MarketplaceResolver(db=db)
        self._competitor_resolver = competitor_resolver or CompetitorResolver(db=db)

    def resolve(self, *, seller_id: UUID, question: str, product_id: UUID | None = None) -> EntityResolutionResult:
        product_resolution = self._product_resolver.resolve(seller_id=seller_id, query_text=question, product_id=product_id)
        category_resolution = self._category_resolver.resolve(seller_id=seller_id, query_text=question)
        marketplace_resolution = self._marketplace_resolver.resolve(seller_id=seller_id, query_text=question)
        competitor_resolution = self._competitor_resolver.resolve(seller_id=seller_id, query_text=question)

        products = _legacy_products(product_resolution)
        categories = _selected_canonical_values(category_resolution)
        marketplaces = _selected_canonical_values(marketplace_resolution)
        competitors = _selected_canonical_values(competitor_resolution)
        resolutions = (product_resolution, category_resolution, marketplace_resolution, competitor_resolution)
        clarification = next((item.clarification_question for item in resolutions if item.clarification_question), None)
        missing_data: list[str] = []
        if self._marketplace_resolver.has_explicit_mention(question) and marketplace_resolution.confidence == EntityConfidence.NONE:
            missing_data.append("MISSING_MARKETPLACE_DATA")
            clarification = clarification or "I could not find seller-owned listing data for that marketplace."

        explicit_types = {
            entity_type
            for entity_type, resolver in (
                ("product", product_resolution),
                ("category", category_resolution),
                ("marketplace", marketplace_resolution),
                ("competitor", competitor_resolution),
            )
            if resolver.matches or resolver.ambiguous
        }
        if product_id is not None:
            explicit_types.add("product")
        if self._category_resolver.has_explicit_mention(question):
            explicit_types.add("category")
        if self._marketplace_resolver.has_explicit_mention(question):
            explicit_types.add("marketplace")
        if self._competitor_resolver.has_explicit_mention(question):
            explicit_types.add("competitor")

        return EntityResolutionResult(
            products=products,
            categories=categories,
            marketplaces=marketplaces,
            competitors=competitors,
            clarification_question=clarification,
            product_resolution=product_resolution,
            category_resolution=category_resolution,
            marketplace_resolution=marketplace_resolution,
            competitor_resolution=competitor_resolution,
            missing_data=missing_data,
            explicit_entity_types=frozenset(explicit_types),
        )


def _legacy_products(resolution: EntityResolution) -> list[ResolvedProductEntity]:
    if resolution.selected_id:
        selected = next((item for item in resolution.matches if item.id == resolution.selected_id), resolution.matches[0])
        return [
            ResolvedProductEntity(
                text=selected.canonical_value,
                product_id=UUID(selected.id),
                title=selected.canonical_value,
                matched_products=[{"id": selected.id, "title": selected.canonical_value}],
                confidence=resolution.confidence.value,
            )
        ]
    if resolution.ambiguous:
        return [
            ResolvedProductEntity(
                text=resolution.query_text,
                matched_products=[{"id": item.id, "title": item.canonical_value} for item in resolution.matches[:5]],
                confidence=EntityConfidence.LOW.value,
            )
        ]
    return []


def _selected_canonical_values(resolution: EntityResolution) -> list[str]:
    if not resolution.selected_id:
        return []
    selected = next((item for item in resolution.matches if item.id == resolution.selected_id), None)
    return [selected.canonical_value] if selected else []


# Backward-compatible private aliases used by older tests and integrations.
_normalize = normalize_entity_text
_tokens = entity_tokens
