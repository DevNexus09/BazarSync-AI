from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
import re
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product


"""Lightweight deterministic intent hints for Copilot planning.

The dynamic question planner owns final routing. This classifier intentionally
keeps the safe keyword/regex behavior as a conservative signal source; UNKNOWN
does not mean the Copilot should stop looking for catalog, metric, entity, or
memory context.
"""


class CopilotIntent(str, Enum):
    RESTOCK_ADVICE = "RESTOCK_ADVICE"
    REVENUE_DIAGNOSIS = "REVENUE_DIAGNOSIS"
    COMPETITOR_THREAT_ANALYSIS = "COMPETITOR_THREAT_ANALYSIS"
    TODAY_ACTIONS = "TODAY_ACTIONS"
    PRICING_ADVICE = "PRICING_ADVICE"
    PROMOTION_ADVICE = "PROMOTION_ADVICE"
    DEAD_STOCK_RECOVERY = "DEAD_STOCK_RECOVERY"
    SEO_ADVICE = "SEO_ADVICE"
    BUSINESS_MEMORY_SEARCH = "BUSINESS_MEMORY_SEARCH"
    GENERAL_HELP = "GENERAL_HELP"
    ACTION_REQUEST_PRICE_CHANGE = "ACTION_REQUEST_PRICE_CHANGE"
    ACTION_REQUEST_PROMOTION = "ACTION_REQUEST_PROMOTION"
    ACTION_REQUEST_REORDER_PLAN = "ACTION_REQUEST_REORDER_PLAN"
    ACTION_REQUEST_SEO_FIX = "ACTION_REQUEST_SEO_FIX"
    ACTION_REQUEST_DEAD_STOCK_RECOVERY = "ACTION_REQUEST_DEAD_STOCK_RECOVERY"
    UNKNOWN = "UNKNOWN"


class CopilotIntentConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class CopilotProductMention:
    text: str
    product_id: UUID | None = None
    title: str | None = None
    matched_products: list[dict[str, str]] = field(default_factory=list)
    confidence: CopilotIntentConfidence = CopilotIntentConfidence.LOW

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "product_id": str(self.product_id) if self.product_id else None,
            "title": self.title,
            "matched_products": self.matched_products,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True, slots=True)
class CopilotDateRange:
    from_date: date
    to_date: date
    source_text: str

    def to_dict(self) -> dict:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "source_text": self.source_text,
        }


@dataclass(frozen=True, slots=True)
class CopilotIntentResult:
    intent: CopilotIntent
    confidence: CopilotIntentConfidence
    suggested_tools: list[str]
    requires_action_proposal: bool
    requires_confirmation: bool
    language: str
    product_mentions: list[CopilotProductMention]
    date_range: CopilotDateRange | None
    missing_clarification: str | None = None

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence.value,
            "suggested_tools": list(self.suggested_tools),
            "requires_action_proposal": self.requires_action_proposal,
            "requires_confirmation": self.requires_confirmation,
            "language": self.language,
            "product_mentions": [mention.to_dict() for mention in self.product_mentions],
            "date_range": self.date_range.to_dict() if self.date_range else None,
            "missing_clarification": self.missing_clarification,
        }


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    id: UUID
    title: str
    category: str | None = None
    searchable_text: str | None = None


class ProductMentionResolver(Protocol):
    def list_products(self, *, seller_id: UUID, limit: int = 200) -> list[ProductCandidate]: ...


class SqlAlchemyProductMentionResolver:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_products(self, *, seller_id: UUID, limit: int = 200) -> list[ProductCandidate]:
        rows = self._db.execute(
            select(Product)
            .where(Product.seller_id == seller_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
            .limit(limit)
        ).scalars().all()
        return [
            ProductCandidate(
                id=row.id,
                title=row.title,
                category=row.category,
                searchable_text=row.searchable_text,
            )
            for row in rows
        ]


RESTOCK_KEYWORDS = (
    "restock",
    "reorder",
    "stock up",
    "stockout",
    "stock out",
    "inventory",
    "পুনরায় স্টক",
    "রিস্টক",
    "স্টক",
    "মজুদ",
)
REVENUE_KEYWORDS = ("revenue", "sales down", "revenue down", "drop", "decline", "কমেছে", "রেভিনিউ", "বিক্রি")
COMPETITOR_KEYWORDS = ("competitor", "hurting me", "threat", "price dropped", "ranking", "প্রতিযোগী", "কম্পিটিটর")
TODAY_KEYWORDS = ("what should i do today", "today actions", "do today", "আজ কী", "আজ কি", "আজ")
PRICING_KEYWORDS = ("price", "pricing", "margin", "safe price", "দাম", "মূল্য", "মার্জিন")
PROMOTION_KEYWORDS = ("promotion", "campaign", "discount", "eid", "ঈদ", "প্রমোশন", "ক্যাম্পেইন", "ডিসকাউন্ট")
DEAD_STOCK_KEYWORDS = ("dead stock", "slow moving", "stale inventory", "locked capital", "অচল", "ডেড স্টক")
SEO_KEYWORDS = ("seo", "listing", "visibility", "rank", "keyword", "লিস্টিং", "ভিজিবিলিটি", "কিওয়ার্ড")
MEMORY_KEYWORDS = ("remember", "history", "last time", "previous", "memory", "আগে", "ইতিহাস")
GENERAL_HELP_KEYWORDS = ("help", "how can you", "what can you do", "সাহায্য")

PRICE_ACTION_RE = re.compile(r"\b(lower|raise|increase|decrease|change|set|update|apply)\b.*\b(price|pricing)\b|\b(price|pricing)\b.*\b(by|to)\b", re.IGNORECASE)
PROMOTION_ACTION_RE = re.compile(r"\b(generate|create|launch|start|make|set up)\b.*\b(promotion|campaign|discount|eid)\b", re.IGNORECASE)
REORDER_ACTION_RE = re.compile(r"\b(order|reorder|buy|purchase|place)\b.*\b(stock|inventory|units|reorder)\b", re.IGNORECASE)
SEO_ACTION_RE = re.compile(r"\b(improve|fix|update|rewrite|edit)\b.*\b(listing|title|description|seo|keyword)\b", re.IGNORECASE)
DEAD_STOCK_ACTION_RE = re.compile(r"\b(bundle|discount|flash sale|recover)\b.*\b(dead stock|slow moving|stale inventory|product)\b|\bdead stock\b.*\b(bundle|discount|recover)\b", re.IGNORECASE)

BANGLA_RANGE = re.compile(r"[\u0980-\u09FF]")
WORD_RE = re.compile(r"[a-z0-9\u0980-\u09FF]+", re.IGNORECASE)


INTENT_TOOLS: dict[CopilotIntent, list[str]] = {
    CopilotIntent.RESTOCK_ADVICE: ["get_restock_recommendations", "get_inventory_risks", "retrieve_business_memory"],
    CopilotIntent.REVENUE_DIAGNOSIS: [
        "explain_revenue_drop",
        "get_competitor_threats",
        "get_inventory_risks",
        "get_pricing_recommendations",
        "get_promotion_recommendations",
        "retrieve_business_memory",
    ],
    CopilotIntent.COMPETITOR_THREAT_ANALYSIS: ["get_competitor_threats", "get_pricing_recommendations", "retrieve_business_memory"],
    CopilotIntent.TODAY_ACTIONS: [
        "get_today_actions",
        "get_inventory_risks",
        "get_dead_stock_recovery",
        "get_pricing_recommendations",
        "get_promotion_recommendations",
    ],
    CopilotIntent.PRICING_ADVICE: ["get_pricing_recommendations", "retrieve_business_memory"],
    CopilotIntent.PROMOTION_ADVICE: ["get_promotion_recommendations", "retrieve_business_memory", "get_pricing_recommendations"],
    CopilotIntent.DEAD_STOCK_RECOVERY: ["get_dead_stock_recovery", "retrieve_business_memory"],
    CopilotIntent.SEO_ADVICE: ["get_seo_opportunities", "retrieve_business_memory"],
    CopilotIntent.BUSINESS_MEMORY_SEARCH: ["retrieve_business_memory"],
    CopilotIntent.GENERAL_HELP: [],
    CopilotIntent.ACTION_REQUEST_PRICE_CHANGE: ["get_pricing_recommendations", "simulate_price_change"],
    CopilotIntent.ACTION_REQUEST_PROMOTION: ["get_promotion_recommendations", "get_pricing_recommendations"],
    CopilotIntent.ACTION_REQUEST_REORDER_PLAN: ["get_restock_recommendations", "get_inventory_risks"],
    CopilotIntent.ACTION_REQUEST_SEO_FIX: ["get_seo_opportunities", "retrieve_business_memory"],
    CopilotIntent.ACTION_REQUEST_DEAD_STOCK_RECOVERY: ["get_dead_stock_recovery", "get_promotion_recommendations"],
    CopilotIntent.UNKNOWN: [],
}


class CopilotIntentClassifier:
    def __init__(
        self,
        *,
        product_resolver: ProductMentionResolver | None = None,
        db: Session | None = None,
        seller_timezone: str = "Asia/Dhaka",
        now: datetime | None = None,
    ) -> None:
        if product_resolver is None and db is not None:
            product_resolver = SqlAlchemyProductMentionResolver(db)
        self._product_resolver = product_resolver
        self._timezone = ZoneInfo(seller_timezone)
        self._now = now

    def classify(self, *, seller_id: UUID, question: str) -> CopilotIntentResult:
        normalized = _normalize(question)
        language = "bn" if BANGLA_RANGE.search(question or "") else "en"
        date_range = self._parse_date_range(normalized)
        intent, confidence = self._classify_intent(normalized)
        product_mentions, clarification = self._resolve_product_mentions(seller_id=seller_id, question=question)

        if clarification and confidence == CopilotIntentConfidence.HIGH:
            confidence = CopilotIntentConfidence.MEDIUM

        requires_action = intent in {
            CopilotIntent.ACTION_REQUEST_PRICE_CHANGE,
            CopilotIntent.ACTION_REQUEST_PROMOTION,
            CopilotIntent.ACTION_REQUEST_REORDER_PLAN,
            CopilotIntent.ACTION_REQUEST_SEO_FIX,
            CopilotIntent.ACTION_REQUEST_DEAD_STOCK_RECOVERY,
        }
        return CopilotIntentResult(
            intent=intent,
            confidence=confidence,
            suggested_tools=INTENT_TOOLS[intent],
            requires_action_proposal=requires_action,
            requires_confirmation=requires_action,
            language=language,
            product_mentions=product_mentions,
            date_range=date_range,
            missing_clarification=clarification,
        )

    def _classify_intent(self, normalized: str) -> tuple[CopilotIntent, CopilotIntentConfidence]:
        if not normalized:
            return CopilotIntent.UNKNOWN, CopilotIntentConfidence.LOW

        if PRICE_ACTION_RE.search(normalized) or _contains_any(normalized, ("lower price", "raise price", "দাম কম", "দাম বাড়")):
            return CopilotIntent.ACTION_REQUEST_PRICE_CHANGE, CopilotIntentConfidence.HIGH
        if PROMOTION_ACTION_RE.search(normalized) or _contains_any(normalized, ("generate eid promotion", "create promotion", "প্রমোশন তৈরি", "ক্যাম্পেইন তৈরি")):
            return CopilotIntent.ACTION_REQUEST_PROMOTION, CopilotIntentConfidence.HIGH
        if REORDER_ACTION_RE.search(normalized) or _contains_any(normalized, ("reorder plan", "order stock", "স্টক অর্ডার")):
            return CopilotIntent.ACTION_REQUEST_REORDER_PLAN, CopilotIntentConfidence.HIGH
        if SEO_ACTION_RE.search(normalized) or _contains_any(normalized, ("লিস্টিং ঠিক", "টাইটেল ঠিক", "seo ঠিক")):
            return CopilotIntent.ACTION_REQUEST_SEO_FIX, CopilotIntentConfidence.HIGH
        if DEAD_STOCK_ACTION_RE.search(normalized) or _contains_any(normalized, ("dead stock discount", "dead stock bundle", "ডেড স্টক ডিসকাউন্ট")):
            return CopilotIntent.ACTION_REQUEST_DEAD_STOCK_RECOVERY, CopilotIntentConfidence.HIGH

        scored: list[tuple[CopilotIntent, int]] = [
            (CopilotIntent.RESTOCK_ADVICE, _score(normalized, RESTOCK_KEYWORDS)),
            (CopilotIntent.REVENUE_DIAGNOSIS, _score(normalized, REVENUE_KEYWORDS)),
            (CopilotIntent.COMPETITOR_THREAT_ANALYSIS, _score(normalized, COMPETITOR_KEYWORDS)),
            (CopilotIntent.TODAY_ACTIONS, _score(normalized, TODAY_KEYWORDS)),
            (CopilotIntent.PRICING_ADVICE, _score(normalized, PRICING_KEYWORDS)),
            (CopilotIntent.PROMOTION_ADVICE, _score(normalized, PROMOTION_KEYWORDS)),
            (CopilotIntent.DEAD_STOCK_RECOVERY, _score(normalized, DEAD_STOCK_KEYWORDS)),
            (CopilotIntent.SEO_ADVICE, _score(normalized, SEO_KEYWORDS)),
            (CopilotIntent.BUSINESS_MEMORY_SEARCH, _score(normalized, MEMORY_KEYWORDS)),
            (CopilotIntent.GENERAL_HELP, _score(normalized, GENERAL_HELP_KEYWORDS)),
        ]
        intent, score = max(scored, key=lambda item: item[1])
        if score >= 2:
            return intent, CopilotIntentConfidence.HIGH
        if score == 1:
            return intent, CopilotIntentConfidence.MEDIUM
        return CopilotIntent.UNKNOWN, CopilotIntentConfidence.LOW

    def _parse_date_range(self, normalized: str) -> CopilotDateRange | None:
        today = self._today()
        if _contains_any(normalized, ("last week", "গত সপ্তাহ")):
            start = today.fromordinal(today.toordinal() - today.weekday() - 7)
            end = start.fromordinal(start.toordinal() + 6)
            return CopilotDateRange(start, end, "গত সপ্তাহ" if "গত সপ্তাহ" in normalized else "last week")
        if _contains_any(normalized, ("last month", "গত মাস")):
            first_this_month = today.replace(day=1)
            last_prev_month = first_this_month.fromordinal(first_this_month.toordinal() - 1)
            start = last_prev_month.replace(day=1)
            return CopilotDateRange(start, last_prev_month, "গত মাস" if "গত মাস" in normalized else "last month")
        if _contains_any(normalized, ("yesterday", "গতকাল", "কাল")):
            target = today.fromordinal(today.toordinal() - 1)
            source = "গতকাল" if "গতকাল" in normalized else "কাল" if "কাল" in normalized else "yesterday"
            return CopilotDateRange(target, target, source)
        if _contains_any(normalized, ("today", "আজ")):
            return CopilotDateRange(today, today, "আজ" if "আজ" in normalized else "today")
        return None

    def _resolve_product_mentions(self, *, seller_id: UUID, question: str) -> tuple[list[CopilotProductMention], str | None]:
        if self._product_resolver is None:
            return [], None
        products = self._product_resolver.list_products(seller_id=seller_id)
        if not products:
            return [], None

        normalized_question = _normalize(question)
        matches: list[tuple[ProductCandidate, int, str]] = []
        for product in products:
            score, text = _product_match_score(normalized_question, product)
            if score > 0:
                matches.append((product, score, text))
        if not matches:
            return [], None

        matches.sort(key=lambda item: (-item[1], item[0].title.lower()))
        top_score = matches[0][1]
        top_matches = [item for item in matches if item[1] == top_score]
        if len(top_matches) > 1:
            mention_text = top_matches[0][2]
            return [
                CopilotProductMention(
                    text=mention_text,
                    matched_products=[{"id": str(product.id), "title": product.title} for product, _, _ in top_matches[:5]],
                    confidence=CopilotIntentConfidence.LOW,
                )
            ], "Multiple seller-owned products match that mention. Please clarify which product you mean."

        product, score, text = top_matches[0]
        return [
            CopilotProductMention(
                text=text,
                product_id=product.id,
                title=product.title,
                matched_products=[{"id": str(product.id), "title": product.title}],
                confidence=CopilotIntentConfidence.HIGH if score >= 3 else CopilotIntentConfidence.MEDIUM,
            )
        ], None

    def _today(self) -> date:
        if self._now is not None:
            return self._now.astimezone(self._timezone).date() if self._now.tzinfo else self._now.date()
        return datetime.now(self._timezone).date()


def _normalize(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _score(value: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in value)


def _tokens(value: str) -> set[str]:
    return {match.group(0).casefold() for match in WORD_RE.finditer(value or "") if len(match.group(0)) > 1}


def _product_match_score(question: str, product: ProductCandidate) -> tuple[int, str]:
    title = _normalize(product.title)
    category = _normalize(product.category or "")
    searchable = _normalize(product.searchable_text or "")
    question_tokens = _tokens(question)
    title_tokens = _tokens(title)
    category_tokens = _tokens(category)

    if title and title in question:
        return 4, product.title
    if category and category in question:
        return 2, product.category or product.title
    token_overlap = question_tokens & title_tokens
    if len(token_overlap) >= max(1, min(2, len(title_tokens))):
        return 3 if len(token_overlap) > 1 else 2, " ".join(sorted(token_overlap))
    searchable_overlap = question_tokens & _tokens(searchable)
    if len(searchable_overlap) >= 2:
        return 1, " ".join(sorted(searchable_overlap))
    if category_tokens and question_tokens & category_tokens:
        return 1, product.category or product.title
    return 0, ""


def local_day_bounds(value: date, timezone_name: str = "Asia/Dhaka") -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    return (
        datetime.combine(value, time.min, tzinfo=timezone),
        datetime.combine(value, time.max, tzinfo=timezone),
    )
