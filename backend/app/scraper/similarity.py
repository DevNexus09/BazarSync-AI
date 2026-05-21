from __future__ import annotations

import logging
import re
import unicodedata
from collections import OrderedDict
from functools import lru_cache
from typing import Any

import torch
from sentence_transformers import SentenceTransformer, util

from app.scraper.constants import SIMILARITY_BATCH_SIZE, SIMILARITY_MODEL_NAME, SIMILARITY_THRESHOLD
from app.scraper.exceptions import SimilarityError

logger = logging.getLogger(__name__)

# -----------------------------
# Configuration
# -----------------------------

ACCESSORY_KEYWORDS = [
    "cover",
    "case",
    "keyboard",
    "charger",
    "adapter",
    "stylus",
    "pen",
    "sleeve",
    "pouch",
    "cable",
    "protector",
    "tempered glass",
    "stand",
    "holder",
    "skin",
    "back cover",
    "flip cover",
    "screen guard",
    "screen protector",
    "glass protector",
    "folio",
    "smart cover",
    "dock",
    "mount",
    "battery",
    "power bank",
    "earbud",
    "earbuds",
    "headphone",
    "headphones",
    "earphone",
    "replacement",
    "spare",
    "part",
]

VARIANT_TOKENS = {
    "pro",
    "max",
    "ultra",
    "mini",
    "plus",
    "air",
    "lite",
    "fe",
    "se",
}

MARKETPLACE_NOISE = [
    "official",
    "genuine",
    "original",
    "authentic",
    "free",
    "shipping",
    "delivery",
    "offer",
    "discount",
    "sale",
    "promo",
    "deal",
    "bundle",
    "daraz",
    "bangladesh",
    "bd",
    "warranty",
    "guarantee",
    "latest",
    "new",
    "best",
    "top",
    "hot",
]

GENERIC_STOPWORDS = {
    "with",
    "and",
    "for",
    "the",
    "a",
    "an",
    "by",
    "of",
    "from",
    "new",
    "latest",
    "best",
    "top",
    "premium",
    "cozy",
}

ATTRIBUTE_KEY_ALIASES = {
    "ram": {"ram", "memory"},
    "storage": {"storage", "rom", "ssd", "hdd", "capacity"},
    "color": {"color", "colour"},
    "size": {"size"},
    "material": {"material", "fabric"},
    "dimensions": {"dimension", "dimensions", "size"},
    "weight": {"weight"},
    "processor": {"processor", "cpu", "chip"},
    "model": {"model", "model number", "model_no"},
    "generation": {"generation", "gen", "version"},
    "volume": {"volume"},
    "skin_type": {"skin type", "skin"},
}

BRAND_ALIASES = {
    "apple": "apple",
    "ipad": "apple",
    "iphone": "apple",
    "macbook": "apple",
    "samsung": "samsung",
    "galaxy": "samsung",
    "xiaomi": "xiaomi",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "mi": "xiaomi",
    "realme": "realme",
    "oppo": "oppo",
    "vivo": "vivo",
    "oneplus": "oneplus",
    "huawei": "huawei",
    "honor": "honor",
    "infinix": "infinix",
    "tecno": "tecno",
    "itel": "itel",
    "nokia": "nokia",
    "google": "google",
    "pixel": "google",
    "lenovo": "lenovo",
    "dell": "dell",
    "hp": "hp",
    "asus": "asus",
    "acer": "acer",
    "msi": "msi",
}

FAMILY_KEYWORDS = {
    "ipad",
    "iphone",
    "macbook",
    "galaxy",
    "redmi",
    "note",
    "poco",
    "pixel",
    "realme",
    "oppo",
    "vivo",
    "oneplus",
    "infinix",
    "tecno",
    "itel",
    "nokia",
}

CATEGORY_KEYWORDS = {
    "tablet": {"tablet", "ipad", "tab"},
    "phone": {"phone", "iphone", "galaxy", "redmi", "poco", "pixel"},
    "laptop": {"laptop", "macbook"},
}

BASE_THRESHOLD = SIMILARITY_THRESHOLD

TITLE_WEIGHT = 0.30
DESCRIPTION_WEIGHT = 0.25
ATTRIBUTE_WEIGHT = 0.25
KEYWORD_WEIGHT = 0.10
RANKING_WEIGHT = 0.10

# Embedding cache to avoid repeated encoding across scrapes.
_EMBED_CACHE: OrderedDict[str, torch.Tensor] = OrderedDict()
_EMBED_CACHE_MAX = 2000


# -----------------------------
# Normalization & preprocessing
# -----------------------------

_ACCESSORY_PATTERN = re.compile(
    r"|".join(
        [
            r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
            for keyword in ACCESSORY_KEYWORDS
        ]
    ),
    re.IGNORECASE,
)

_NOISE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in MARKETPLACE_NOISE) + r")\b",
    re.IGNORECASE,
)

_GEN_PATTERN = re.compile(r"\b(\d+)(st|nd|rd|th)?\s*gen\b|\bgen\s*(\d+)\b")
_STORAGE_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(tb|gb|g)\b")
_RAM_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*gb\s*ram\b")
_DIMENSION_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(cm|mm|inch|in)\b")


def normalize_title(title: str) -> str:
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKC", title)
    normalized = normalized.lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[\u200b-\u200f]", "", normalized)
    normalized = re.sub(r"[®™©]", "", normalized)
    normalized = re.sub(r"[^\w\s\.]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    normalized = normalized.replace("i pad", "ipad")
    normalized = normalized.replace("i phone", "iphone")
    normalized = normalized.replace("mac book", "macbook")

    normalized = _GEN_PATTERN.sub(
        lambda match: f"gen{match.group(1) or match.group(3)}", normalized
    )
    normalized = _RAM_PATTERN.sub(
        lambda match: f"ram{match.group(1)}gb", normalized
    )

    def _storage_replacer(match: re.Match[str]) -> str:
        value = float(match.group(1))
        unit = match.group(2)
        gb_value = int(value * 1024) if unit == "tb" else int(value)
        return f"{gb_value}gb"

    normalized = _STORAGE_PATTERN.sub(_storage_replacer, normalized)
    normalized = _NOISE_PATTERN.sub(" ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_description(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[\u200b-\u200f]", "", normalized)
    normalized = re.sub(r"[®™©]", "", normalized)
    normalized = re.sub(r"[^\w\s\.]", " ", normalized)
    normalized = _NOISE_PATTERN.sub(" ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_attributes(attributes: dict[str, str] | None) -> dict[str, str]:
    if not attributes:
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in attributes.items():
        key = normalize_description(str(raw_key))
        value = normalize_description(str(raw_value))
        if not key or not value:
            continue
        canonical_key = _map_attribute_key(key)
        normalized_value = _normalize_attribute_value(canonical_key, value)
        normalized[canonical_key] = normalized_value
    return normalized


def _map_attribute_key(key: str) -> str:
    for canonical, aliases in ATTRIBUTE_KEY_ALIASES.items():
        if key in aliases:
            return canonical
    return key


def _normalize_attribute_value(key: str, value: str) -> str:
    if key in {"ram", "storage"}:
        storage_match = _STORAGE_PATTERN.search(value)
        if storage_match:
            amount = float(storage_match.group(1))
            unit = storage_match.group(2)
            gb_value = int(amount * 1024) if unit == "tb" else int(amount)
            return f"{gb_value}gb"
    if key == "dimensions":
        parts = _DIMENSION_PATTERN.findall(value)
        if parts:
            return "x".join([f"{part[0]}{part[1]}" for part in parts])
    return value


def build_searchable_text(
    title: str,
    description: str,
    category: str | None,
    attributes: dict[str, str] | None,
) -> str:
    attributes_text = " ".join(
        f"{key} {value}".strip()
        for key, value in (attributes or {}).items()
        if key and value
    )
    combined = " ".join(
        part
        for part in (title, description, category or "", attributes_text)
        if part
    )
    return normalize_description(combined)

def _truncate_text(text: str, max_words: int = 200) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _build_description_text(
    title: str,
    description: str | None,
    category: str | None,
    attributes: dict[str, str] | None,
) -> str:
    normalized_description = normalize_description(description or "")
    if len(normalized_description.split()) < 8:
        return build_searchable_text(title, normalized_description, category, attributes)
    return normalized_description


def is_accessory_product(title: str, description: str | None = None) -> bool:
    combined = " ".join([title or "", description or ""]).strip()
    normalized = normalize_title(combined)
    return bool(_ACCESSORY_PATTERN.search(normalized))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)


def _important_tokens(text: str) -> set[str]:
    tokens = _tokenize(text)
    return {
        token
        for token in tokens
        if token not in GENERIC_STOPWORDS and len(token) > 1
    }


def extract_key_entities(
    title: str,
    description: str | None = None,
    specifications: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_title = normalize_title(title)
    normalized_description = normalize_description(description or "")
    normalized_attributes = normalize_attributes(specifications)
    searchable_text = build_searchable_text(
        normalized_title, normalized_description, None, normalized_attributes
    )
    tokens = _tokenize(searchable_text)
    title_tokens = _important_tokens(normalized_title)

    brand = None
    for token in tokens:
        if token in BRAND_ALIASES:
            brand = BRAND_ALIASES[token]
            break

    family_tokens = [token for token in tokens if token in FAMILY_KEYWORDS]

    generation = None
    gen_match = re.search(r"\bgen(\d+)\b", searchable_text)
    if gen_match:
        generation = gen_match.group(1)

    storage_gb = None
    storage_match = re.search(r"\b(\d+)gb\b", searchable_text)
    if storage_match:
        storage_gb = storage_match.group(1)

    ram_gb = None
    ram_match = re.search(r"\bram(\d+)gb\b", searchable_text)
    if ram_match:
        ram_gb = ram_match.group(1)

    model_tokens = []
    for token in tokens:
        if token in FAMILY_KEYWORDS or token in BRAND_ALIASES:
            continue
        if token.startswith("gen") or token.startswith("ram"):
            continue
        if re.match(r"^\d+gb$", token):
            continue
        if re.match(r"^[a-z]{1,4}\d{1,4}[a-z]{0,2}$", token):
            model_tokens.append(token)

    variant_tokens = {token for token in tokens if token in VARIANT_TOKENS}

    return {
        "normalized_title": normalized_title,
        "normalized_description": normalized_description,
        "normalized_attributes": normalized_attributes,
        "brand": brand,
        "family_tokens": set(family_tokens),
        "generation": generation,
        "storage_gb": storage_gb,
        "ram_gb": ram_gb,
        "model_tokens": set(model_tokens),
        "variant_tokens": variant_tokens,
        "important_tokens": _important_tokens(searchable_text),
        "title_tokens": title_tokens,
    }


def _infer_category(text: str) -> str | None:
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category
    return None


def _token_overlap_score(seller_tokens: set[str], competitor_tokens: set[str]) -> float:
    if not seller_tokens or not competitor_tokens:
        return 0.0
    intersection = seller_tokens & competitor_tokens
    union = seller_tokens | competitor_tokens
    return len(intersection) / len(union)


def _keyword_overlap_score(
    seller_entities: dict[str, Any], competitor_entities: dict[str, Any]
) -> float:
    weight_map = {
        "brand": 0.3,
        "family": 0.25,
        "model": 0.2,
        "generation": 0.1,
        "storage": 0.1,
        "ram": 0.05,
    }

    score = 0.0
    total_weight = sum(weight_map.values())

    if seller_entities["brand"] and competitor_entities["brand"]:
        if seller_entities["brand"] == competitor_entities["brand"]:
            score += weight_map["brand"]

    if seller_entities["family_tokens"]:
        if seller_entities["family_tokens"] & competitor_entities["family_tokens"]:
            score += weight_map["family"]

    if seller_entities["model_tokens"]:
        if seller_entities["model_tokens"] & competitor_entities["model_tokens"]:
            score += weight_map["model"]

    if seller_entities["generation"] and competitor_entities["generation"]:
        if seller_entities["generation"] == competitor_entities["generation"]:
            score += weight_map["generation"]

    if seller_entities["storage_gb"] and competitor_entities["storage_gb"]:
        if seller_entities["storage_gb"] == competitor_entities["storage_gb"]:
            score += weight_map["storage"]

    if seller_entities["ram_gb"] and competitor_entities["ram_gb"]:
        if seller_entities["ram_gb"] == competitor_entities["ram_gb"]:
            score += weight_map["ram"]

    entity_score = score / total_weight if total_weight else 0.0

    seller_title_tokens = seller_entities.get("title_tokens", set())
    competitor_title_tokens = competitor_entities.get("title_tokens", set())
    token_score = _token_overlap_score(seller_title_tokens, competitor_title_tokens)

    if seller_title_tokens and seller_title_tokens.issubset(competitor_title_tokens):
        token_score = max(token_score, 0.9)

    return max(entity_score, token_score)


def _attribute_similarity(
    seller_attributes: dict[str, str],
    competitor_attributes: dict[str, str],
) -> tuple[float, list[str]]:
    if not seller_attributes or not competitor_attributes:
        return 0.0, []

    matched_keys: list[str] = []
    total = 0
    matched = 0
    for key, value in seller_attributes.items():
        if key not in competitor_attributes:
            continue
        total += 1
        competitor_value = competitor_attributes[key]
        if value == competitor_value:
            matched += 1
            matched_keys.append(key)
        elif value in competitor_value or competitor_value in value:
            matched += 0.5
            matched_keys.append(key)

    if total == 0:
        return 0.0, []

    return min(1.0, matched / total), matched_keys


def _passes_required_overlap(
    seller_entities: dict[str, Any], competitor_entities: dict[str, Any]
) -> bool:
    if seller_entities["brand"] and competitor_entities["brand"]:
        if seller_entities["brand"] != competitor_entities["brand"]:
            return False

    seller_family = seller_entities["family_tokens"]
    competitor_family = competitor_entities["family_tokens"]
    if seller_family and not (seller_family & competitor_family):
        seller_category = _infer_category(seller_entities["normalized_title"])
        competitor_category = _infer_category(competitor_entities["normalized_title"])
        brand_match = (
            seller_entities["brand"]
            and competitor_entities["brand"]
            and seller_entities["brand"] == competitor_entities["brand"]
        )
        category_match = (
            seller_category and competitor_category and seller_category == competitor_category
        )
        if not (brand_match and category_match):
            return False

    if seller_entities["model_tokens"]:
        if not (seller_entities["model_tokens"] & competitor_entities["model_tokens"]):
            if not (seller_family and (seller_family & competitor_family)):
                return False

    seller_variants = seller_entities.get("variant_tokens", set())
    competitor_variants = competitor_entities.get("variant_tokens", set())
    if seller_variants or competitor_variants:
        if not seller_variants or not competitor_variants:
            return False
        if not (seller_variants & competitor_variants):
            return False

    return True


def _adjust_threshold(
    base_threshold: float,
    keyword_score: float,
    attribute_score: float,
    title_similarity: float,
    seller_entities: dict[str, Any],
    competitor_entities: dict[str, Any],
) -> float:
    adjustment = 0.0
    if keyword_score < 0.2:
        adjustment += 0.1
    if keyword_score >= 0.8:
        adjustment -= 0.1

    if attribute_score >= 0.7:
        adjustment -= 0.05

    if title_similarity >= 0.8:
        adjustment -= 0.05

    if seller_entities["model_tokens"] and not (
        seller_entities["model_tokens"] & competitor_entities["model_tokens"]
    ):
        adjustment += 0.1

    return max(0.5, min(0.95, base_threshold + adjustment))


# -----------------------------
# Embedding utilities
# -----------------------------


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    try:
        return SentenceTransformer(SIMILARITY_MODEL_NAME)
    except Exception as exc:
        logger.exception("Failed to load similarity model %s.", SIMILARITY_MODEL_NAME)
        raise SimilarityError("Failed to load similarity model.") from exc


def _cache_embedding(text: str, embedding: torch.Tensor) -> None:
    if text in _EMBED_CACHE:
        _EMBED_CACHE.move_to_end(text)
        return
    _EMBED_CACHE[text] = embedding
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)


def _embed_texts(texts: list[str]) -> torch.Tensor:
    if not texts:
        raise SimilarityError("No texts provided for embedding.")

    model = _get_model()
    unique_texts = list(dict.fromkeys(texts))
    cached_embeddings: list[torch.Tensor | None] = [
        _EMBED_CACHE.get(text) for text in unique_texts
    ]
    to_encode = [
        text for text, cached in zip(unique_texts, cached_embeddings) if cached is None
    ]
    local_embeddings: dict[str, torch.Tensor] = {
        text: cached
        for text, cached in zip(unique_texts, cached_embeddings)
        if cached is not None
    }

    if to_encode:
        try:
            with torch.inference_mode():
                new_embeddings = model.encode(
                    to_encode,
                    batch_size=SIMILARITY_BATCH_SIZE,
                    convert_to_tensor=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
        except Exception as exc:
            logger.exception("Failed to encode similarity texts.")
            raise SimilarityError("Failed to encode texts for similarity.") from exc

        for text, embedding in zip(to_encode, new_embeddings):
            local_embeddings[text] = embedding
            _cache_embedding(text, embedding)

    resolved_embeddings = torch.stack([local_embeddings[text] for text in texts])
    return resolved_embeddings


# -----------------------------
# Public API
# -----------------------------


def compute_similarity(a: str, b: str) -> float:
    normalized_a = normalize_title(a)
    normalized_b = normalize_title(b)
    if not normalized_a or not normalized_b:
        return 0.0
    try:
        embeddings = _embed_texts([normalized_a, normalized_b])
        score = float(util.cos_sim(embeddings[0], embeddings[1]).item())
        return max(0.0, min(1.0, score))
    except SimilarityError as exc:
        logger.warning("Similarity computation failed: %s", exc)
        return 0.0


def filter_valid_competitors(
    seller_title: str,
    competitors: list[dict[str, Any]],
    threshold: float = BASE_THRESHOLD,
    seller_description: str | None = None,
    seller_category: str | None = None,
    seller_specifications: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    return filter_similar_products(
        seller_title,
        competitors,
        threshold=threshold,
        seller_description=seller_description,
        seller_category=seller_category,
        seller_specifications=seller_specifications,
    )


def filter_similar_products(
    seller_title: str,
    competitors: list[dict[str, Any]],
    threshold: float = BASE_THRESHOLD,
    seller_description: str | None = None,
    seller_category: str | None = None,
    seller_specifications: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Multi-stage competitor matching pipeline:
    1) Preprocessing
    2) Accessory filtering
    3) Category validation
    4) Attribute extraction
    5) Semantic similarity
    6) Ranking score combination
    7) Confidence scoring
    """
    if not seller_title:
        return []

    seller_entities = extract_key_entities(
        seller_title,
        description=seller_description,
        specifications=seller_specifications,
    )
    seller_is_accessory = is_accessory_product(seller_title, seller_description)

    candidates: list[dict[str, Any]] = []
    candidate_metadata: list[dict[str, Any]] = []
    title_texts: list[str] = [_truncate_text(seller_entities["normalized_title"])]
    seller_desc_text = _build_description_text(
        seller_entities["normalized_title"],
        seller_description,
        seller_category,
        seller_specifications,
    )
    description_texts: list[str] = [seller_desc_text]

    for competitor in competitors or []:
        if not isinstance(competitor, dict):
            continue
        raw_title = (
            competitor.get("product_title")
            or competitor.get("competitor_title")
            or competitor.get("title")
            or ""
        )
        raw_description = competitor.get("product_description") or competitor.get(
            "competitor_description"
        )
        raw_category = competitor.get("product_category") or competitor.get(
            "competitor_category"
        )
        raw_attributes = competitor.get("product_attributes") or competitor.get(
            "competitor_attributes"
        )

        if not raw_title:
            continue

        if not seller_is_accessory and is_accessory_product(raw_title, raw_description):
            continue

        competitor_entities = extract_key_entities(
            raw_title, description=raw_description, specifications=raw_attributes
        )

        if not _passes_required_overlap(seller_entities, competitor_entities):
            continue

        keyword_score = _keyword_overlap_score(seller_entities, competitor_entities)
        attribute_score, matched_attributes = _attribute_similarity(
            seller_entities["normalized_attributes"],
            competitor_entities["normalized_attributes"],
        )
        category_match = None
        if seller_category and raw_category:
            category_match = seller_category.lower() == str(raw_category).lower()

        candidates.append(competitor)
        candidate_metadata.append(
            {
                "entities": competitor_entities,
                "keyword_score": keyword_score,
                "attribute_score": attribute_score,
                "matched_attributes": matched_attributes,
                "category_match": category_match,
                "description_text": _build_description_text(
                    competitor_entities["normalized_title"],
                    raw_description,
                    raw_category,
                    raw_attributes,
                ),
            }
        )

        title_texts.append(_truncate_text(competitor_entities["normalized_title"]))
        description_texts.append(candidate_metadata[-1]["description_text"])

    if not candidates:
        return []

    try:
        title_embeddings = _embed_texts(title_texts)
        seller_title_embedding = title_embeddings[0]
        competitor_title_embeddings = title_embeddings[1:]
        title_similarities = util.cos_sim(
            competitor_title_embeddings, seller_title_embedding
        ).squeeze(1)

        if seller_desc_text:
            description_embeddings = _embed_texts(
                [_truncate_text(text) for text in description_texts]
            )
            seller_desc_embedding = description_embeddings[0]
            competitor_desc_embeddings = description_embeddings[1:]
            description_similarities = util.cos_sim(
                competitor_desc_embeddings, seller_desc_embedding
            ).squeeze(1)
        else:
            description_similarities = torch.zeros(len(candidates))
    except SimilarityError as exc:
        logger.warning("Similarity filtering failed: %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for competitor, title_score_tensor, desc_score_tensor, metadata in zip(
        candidates, title_similarities, description_similarities, candidate_metadata
    ):
        title_similarity = max(0.0, min(1.0, float(title_score_tensor.item())))
        description_similarity = max(0.0, min(1.0, float(desc_score_tensor.item())))
        desc_token_score = _token_overlap_score(
            _important_tokens(seller_desc_text),
            _important_tokens(metadata["description_text"]),
        )
        description_similarity = max(description_similarity, desc_token_score)
        keyword_score = metadata["keyword_score"]
        attribute_score = metadata["attribute_score"]
        ranking_score = float(competitor.get("ranking_score") or 0.0)
        category_match = metadata["category_match"]

        title_weight = TITLE_WEIGHT
        description_weight = DESCRIPTION_WEIGHT
        attribute_weight = ATTRIBUTE_WEIGHT
        keyword_weight = KEYWORD_WEIGHT
        ranking_weight = RANKING_WEIGHT

        if not seller_desc_text or not metadata["description_text"]:
            title_weight += description_weight
            description_weight = 0.0

        if not seller_entities["normalized_attributes"] or not metadata["entities"]["normalized_attributes"]:
            title_weight += attribute_weight * 0.6
            keyword_weight += attribute_weight * 0.4
            attribute_weight = 0.0

        final_score = (
            title_similarity * title_weight
            + description_similarity * description_weight
            + attribute_score * attribute_weight
            + keyword_score * keyword_weight
            + ranking_score * ranking_weight
        )

        if category_match is False:
            final_score *= 0.85
        final_score = max(0.0, min(1.0, final_score))

        adjusted_threshold = _adjust_threshold(
            threshold,
            keyword_score,
            attribute_score,
            title_similarity,
            seller_entities,
            metadata["entities"],
        )

        if final_score >= adjusted_threshold:
            results.append(
                {
                    **competitor,
                    "similarity_score": final_score,
                    "title_similarity": title_similarity,
                    "description_similarity": description_similarity,
                    "attribute_similarity": attribute_score,
                    "keyword_score": keyword_score,
                    "ranking_score": ranking_score,
                    "match_confidence": final_score,
                    "category_match": category_match,
                    "matched_attributes": metadata["matched_attributes"],
                }
            )

    return results


# -----------------------------
# Example usage
# -----------------------------
#
# seller = "Apple iPad 11th Gen WiFi 128GB"
# seller_description = "11th Gen iPad with 128GB storage, WiFi, Silver."
# seller_specs = {"storage": "128GB", "color": "Silver", "ram": "4GB"}
# candidates = [
#     {"product_title": "iPad 11th Gen Silicone Cover"},
#     {"product_title": "Apple iPad 11th Gen WiFi 128GB", "product_attributes": {"storage": "128GB"}},
#     {"product_title": "iPad 10th Gen 64GB"},
# ]
# matches = filter_similar_products(
#     seller,
#     candidates,
#     threshold=0.65,
#     seller_description=seller_description,
#     seller_specifications=seller_specs,
# )
