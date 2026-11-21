from __future__ import annotations

import logging
import math
import re
import time
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch
    from sentence_transformers import SentenceTransformer

from app.scraper.constants import (
    SIMILARITY_BATCH_SIZE,
    SIMILARITY_DEVICE,
    SIMILARITY_MODEL_NAME,
    SIMILARITY_THRESHOLD,
    SIMILARITY_POSSIBLE_THRESHOLD,
    SIMILARITY_VERY_STRONG_THRESHOLD,
    SIMILARITY_VERIFICATION_FLOOR,
    SIMILARITY_DIMENSIONS_TOLERANCE,
    SIMILARITY_MIN_TITLE_EVIDENCE,
    BASELINE_SIMILARITY_MODEL,
)
from app.scraper.exceptions import SimilarityError, SimilarityUnavailableError
from app.scraper.product_identity import compare_identities, identity_from_listing, normalize_identity_text

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

# Product.specifications also stores operational planning inputs and source
# provenance. Those values describe the seller's record, not the marketplace
# product identity, and must not dilute or contradict matching evidence.
NON_MATCHING_SPECIFICATION_KEYS = {
    "case size", "confirmed incoming quantity", "holding cost bdt per unit per day", "image url",
    "incoming quantity", "market reference only", "maximum stock", "minimum order quantity", "moq",
    "pack size", "purchase order quantity", "quantity incoming unconfirmed", "quantity reserved",
    "reorder budget bdt", "review period days",
    "safety buffer days", "safety stock", "storage capacity units", "supplier lead time",
}
NON_MATCHING_SPECIFICATION_PREFIXES = ("demo ", "inventory ", "source ")

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
    "dove": "dove",
    "sony": "sony",
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
    "laptop": {"laptop", "macbook", "thinkpad", "notebook"},
}

BASE_THRESHOLD = SIMILARITY_THRESHOLD

TITLE_WEIGHT = 0.30
DESCRIPTION_WEIGHT = 0.25
ATTRIBUTE_WEIGHT = 0.25
KEYWORD_WEIGHT = 0.10

# Embedding cache to avoid repeated encoding across scrapes.
_EMBED_CACHE: OrderedDict[tuple[int, str], torch.Tensor] = OrderedDict()
_EMBED_CACHE_MAX = 2000
_EMBED_LOCK = RLock()


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
    normalized = normalize_identity_text(title)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[\u200b-\u200f]", "", normalized)
    normalized = re.sub(r"[®™©]", "", normalized)
    normalized = "".join(char if char.isalnum() or char.isspace() or char == "." or unicodedata.category(char).startswith("M") else " " for char in normalized)
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
    normalized = "".join(char if char.isalnum() or char.isspace() or char == "." or unicodedata.category(char).startswith("M") else " " for char in normalized)
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

def matching_specifications(specifications: dict[str, str] | None) -> dict[str, str]:
    """Return only seller fields that can describe marketplace product identity."""
    if not specifications:
        return {}
    return {
        key: value for key, value in specifications.items()
        if (normalized_key := normalize_description(str(key)))
        and normalized_key not in NON_MATCHING_SPECIFICATION_KEYS
        and not normalized_key.startswith(NON_MATCHING_SPECIFICATION_PREFIXES)
    }


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
    return build_searchable_text("", normalized_description, category, attributes)


def _identity_title(title: str) -> str:
    # Included accessories must not supply the primary product's identity.
    return re.split(r"\bwith\b", title, maxsplit=1, flags=re.I)[0]


def is_accessory_product(title: str, description: str | None = None) -> bool:
    combined = " ".join([title or "", description or ""]).strip()
    normalized = normalize_title(_identity_title(combined))
    return bool(_ACCESSORY_PATTERN.search(normalized))


def _tokenize(text: str) -> list[str]:
    return [word.strip(".") for word in text.split() if word.strip(".")]


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
        if re.fullmatch(r"[a-z]{1,5}\d{1,6}[a-z0-9]{0,5}", token):
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
    words = set(_tokenize(text))
    for category, keywords in CATEGORY_KEYWORDS.items():
        if words & keywords:
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

    if total == 0:
        return 0.0, []

    return min(1.0, matched / total), matched_keys


def _has_title_conflict(seller_entities: dict[str, Any], competitor_entities: dict[str, Any]) -> bool:
    # Explicit identifiers in listing titles take precedence over semantic resemblance.
    seller_title_tokens = seller_entities["title_tokens"]
    competitor_title_tokens = competitor_entities["title_tokens"]
    patterns = [r"gen\d+"]
    if _infer_category(seller_entities["normalized_title"]) or _infer_category(competitor_entities["normalized_title"]):
        patterns.extend((r"\d+gb", r"ram\d+gb"))
    for pattern in patterns:
        seller_values = {token for token in seller_title_tokens if re.fullmatch(pattern, token)}
        competitor_values = {token for token in competitor_title_tokens if re.fullmatch(pattern, token)}
        if seller_values and competitor_values and seller_values.isdisjoint(competitor_values):
            return True
    seller_models = seller_title_tokens & seller_entities["model_tokens"]
    competitor_models = competitor_title_tokens & competitor_entities["model_tokens"]
    if seller_models and competitor_models and seller_models.isdisjoint(competitor_models):
        return True

    return False


def is_obviously_unrelated(seller_title: str, candidate_title: str) -> bool:
    if not is_accessory_product(seller_title) and is_accessory_product(candidate_title):
        return True
    seller = extract_key_entities(_identity_title(seller_title))
    candidate = extract_key_entities(_identity_title(candidate_title))
    if seller["brand"] and candidate["brand"] and seller["brand"] != candidate["brand"]:
        return True
    return _has_title_conflict(seller, candidate) or _variant_conflict(seller, candidate)


def _variant_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for pattern in (r"\biphone (\d+)\b", r"\b(?:galaxy )?(s\d+|a\d+)\b", r"\b(?:redmi )?note (\d+)\b", r"\bpixel (\d+)\b"):
        first = re.search(pattern, left["normalized_title"])
        second = re.search(pattern, right["normalized_title"])
        if first and second and first[1] != second[1]:
            return True
    left_variants = left["title_tokens"] & VARIANT_TOKENS
    right_variants = right["title_tokens"] & VARIANT_TOKENS
    return bool(left["family_tokens"] & right["family_tokens"] and left_variants != right_variants)


def _brand_identity(explicit: str | None, inferred: str | None) -> str | None:
    if not explicit:
        return inferred
    return BRAND_ALIASES.get(explicit, explicit.removesuffix(" inc.").removesuffix(" electronics"))


# -----------------------------
# Embedding utilities
# -----------------------------


def _load_model(name: str, device: str) -> SentenceTransformer:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(name, device=device, local_files_only=True)
    model.eval()
    model._bazarsync_model_name = name
    return model


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    start = time.monotonic()
    try:
        import torch

        device = SIMILARITY_DEVICE.strip().lower()
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        target = torch.device(device)
        if (target.type == "cuda" and (
            not torch.cuda.is_available() or (target.index is not None and target.index >= torch.cuda.device_count())
        )) or (target.type == "mps" and not torch.backends.mps.is_available()):
            logger.warning("similarity_device_unavailable requested=%s fallback=cpu", device)
            device = "cpu"
        try:
            model = _load_model(SIMILARITY_MODEL_NAME, device)
        except Exception:
            if device == "cpu":
                raise
            logger.warning("similarity_device_load_failed device=%s fallback=cpu", device, exc_info=True)
            model = _load_model(SIMILARITY_MODEL_NAME, "cpu")
    except Exception as exc:
        if SIMILARITY_MODEL_NAME == BASELINE_SIMILARITY_MODEL:
            raise SimilarityUnavailableError("Failed to load similarity model from local files.") from exc
        logger.warning("similarity_model_unavailable model=%s fallback=%s", SIMILARITY_MODEL_NAME, BASELINE_SIMILARITY_MODEL, exc_info=True)
        try:
            model = _load_model(BASELINE_SIMILARITY_MODEL, "cpu")
        except Exception as fallback_error:
            raise SimilarityUnavailableError("Configured and baseline similarity models are unavailable.") from fallback_error

    logger.info(
        "similarity_model_loaded model=%s device=%s load_ms=%.1f parameter_bytes=%s",
        model._bazarsync_model_name, model.device, (time.monotonic() - start) * 1000,
        sum(parameter.numel() * parameter.element_size() for parameter in model.parameters()),
    )
    return model


def _cache_embedding(text: tuple[int, str], embedding: torch.Tensor) -> None:
    if text in _EMBED_CACHE:
        _EMBED_CACHE.move_to_end(text)
        return
    _EMBED_CACHE[text] = embedding
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)


def _embed_texts(texts: list[str]) -> torch.Tensor:
    if not texts:
        raise SimilarityError("No texts provided for embedding.")

    with _EMBED_LOCK:
        return _embed_texts_locked(texts)


def _embed_texts_locked(texts: list[str]) -> torch.Tensor:
    model = _get_model()
    import torch

    model_name = getattr(model, "_bazarsync_model_name", SIMILARITY_MODEL_NAME)
    prefix = "query: " if str(model_name).startswith("intfloat/multilingual-e5") else ""
    texts = [prefix + text for text in texts]
    unique_texts = list(dict.fromkeys(texts))
    cached_embeddings: list[torch.Tensor | None] = [
        _EMBED_CACHE.get((id(model), text)) for text in unique_texts
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
        start = time.monotonic()
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

        if new_embeddings.ndim != 2 or len(new_embeddings) != len(to_encode):
            raise SimilarityError("Similarity model returned an invalid embedding shape.")
        if not torch.isfinite(new_embeddings).all() or (new_embeddings.norm(dim=1) == 0).any():
            raise SimilarityError("Similarity model returned an invalid embedding.")

        for text, embedding in zip(to_encode, new_embeddings):
            embedding = embedding.detach().to("cpu", copy=True)
            local_embeddings[text] = embedding
            _cache_embedding((id(model), text), embedding)
        logger.debug(
            "similarity_inference texts=%s elapsed_ms=%.1f cached_embeddings=%s",
            len(to_encode), (time.monotonic() - start) * 1000, len(_EMBED_CACHE),
        )

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
        from sentence_transformers import util

        return _bounded_score(float(util.cos_sim(embeddings[0], embeddings[1]).item()))
    except SimilarityError:
        raise
    except Exception as exc:
        raise SimilarityError("Failed to compute similarity.") from exc


def _bounded_score(score: float) -> float:
    if not math.isfinite(score):
        raise SimilarityError("Similarity model returned a non-finite score.")
    return max(0.0, min(1.0, score))


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
    return [
        record for record in evaluate_competitor_matches(
            seller_title, competitors, threshold, seller_description, seller_category, seller_specifications,
        )
        if record["match_classification"] in {"VERY_STRONG", "STRONG"}
    ]


@dataclass(frozen=True)
class _MatchCandidate:
    listing: dict[str, Any]
    exact_identity: bool
    keyword: float
    has_comparable_attributes: bool
    attribute: float
    matched_attributes: list[str]
    category_match: bool | None
    description: str


def evaluate_competitor_matches(
    seller_title: str,
    competitors: list[dict[str, Any]],
    threshold: float = BASE_THRESHOLD,
    seller_description: str | None = None,
    seller_category: str | None = None,
    seller_specifications: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return internal evidence for compatible candidates, including exploratory scores."""
    if not 0 <= threshold <= 1:
        raise ValueError("Similarity threshold must be between zero and one.")
    if not normalize_title(seller_title):
        return []
    threshold = max(threshold, SIMILARITY_VERIFICATION_FLOOR)

    seller_specifications = matching_specifications(seller_specifications)
    seller_identity = identity_from_listing(seller_title, seller_specifications)
    seller_accessory = bool(seller_identity.accessory) or is_accessory_product(seller_title)
    seller_entities = extract_key_entities(seller_title, specifications=seller_specifications)
    seller_title_entities = extract_key_entities(_identity_title(seller_title))
    seller_brand = _brand_identity(seller_identity.brand, seller_title_entities["brand"])
    seller_desc = _build_description_text(
        seller_entities["normalized_title"], seller_description, seller_category, seller_entities["normalized_attributes"],
    )
    title_texts = [_truncate_text(seller_entities["normalized_title"])]
    description_texts = [_truncate_text(seller_desc)]
    candidates: list[_MatchCandidate] = []
    rejected: Counter[str] = Counter()

    for competitor in competitors or []:
        if not isinstance(competitor, dict):
            continue
        title = competitor.get("product_title") or competitor.get("competitor_title") or competitor.get("title")
        if not isinstance(title, str) or not normalize_title(title):
            continue
        attributes = competitor.get("product_attributes") or competitor.get("competitor_attributes")
        category = competitor.get("product_category") or competitor.get("competitor_category")
        description = competitor.get("product_description") or competitor.get("competitor_description")
        brand = competitor.get("product_brand") or competitor.get("competitor_brand")
        identity = identity_from_listing(title, attributes, brand)
        title_entities = extract_key_entities(_identity_title(title))
        candidate_accessory = bool(identity.accessory) or is_accessory_product(title)
        candidate_brand = _brand_identity(identity.brand, title_entities["brand"])
        evidence = compare_identities(
            seller_identity, identity, context=f"{seller_category or ''} {category or ''} {seller_title} {title}",
            seller_brand=seller_brand, candidate_brand=candidate_brand,
            dimensions_tolerance=SIMILARITY_DIMENSIONS_TOLERANCE,
        )
        seller_family, candidate_family = seller_title_entities["family_tokens"], title_entities["family_tokens"]
        family_conflict = bool(
            seller_brand and seller_brand == candidate_brand and seller_family
            and candidate_family and seller_family.isdisjoint(candidate_family)
        )
        seller_type = _infer_category(seller_title_entities["normalized_title"])
        candidate_type = _infer_category(title_entities["normalized_title"])
        type_conflict = seller_type and candidate_type and seller_type != candidate_type
        reason = evidence.conflict
        if not reason:
            if family_conflict or type_conflict:
                reason = "product_family"
            elif seller_accessory != candidate_accessory:
                reason = "accessory"
            elif _has_title_conflict(seller_title_entities, title_entities) or _variant_conflict(seller_title_entities, title_entities):
                reason = "title_identity"
        if reason:
            rejected[reason] += 1
            continue

        entities = extract_key_entities(title, specifications=attributes)
        keyword = _keyword_overlap_score(seller_entities, entities)
        comparable = seller_entities["normalized_attributes"].keys() & entities["normalized_attributes"].keys()
        attribute, matched_attributes = _attribute_similarity(
            seller_entities["normalized_attributes"], entities["normalized_attributes"],
        )
        category_match = None
        if seller_category and category:
            category_match = normalize_description(seller_category) == normalize_description(category)
        desc = _build_description_text(entities["normalized_title"], description, category, entities["normalized_attributes"])
        candidates.append(_MatchCandidate(
            competitor, evidence.exact, keyword, bool(comparable), attribute, matched_attributes, category_match, desc,
        ))
        title_texts.append(_truncate_text(entities["normalized_title"]))
        description_texts.append(_truncate_text(desc))

    if rejected:
        logger.debug("similarity_identity_rejections counts=%s", dict(rejected))
    if not candidates:
        return []

    try:
        from sentence_transformers import util

        title_embeddings = _embed_texts(title_texts)
        title_scores = util.cos_sim(title_embeddings[1:], title_embeddings[0]).flatten().tolist()
        detail_embeddings = _embed_texts(description_texts)
        detail_scores = util.cos_sim(detail_embeddings[1:], detail_embeddings[0]).flatten().tolist()
    except SimilarityError:
        raise
    except Exception as exc:
        raise SimilarityError("Failed to score competitor embeddings.") from exc

    results = []
    for candidate, title, detail in zip(candidates, title_scores, detail_scores, strict=True):
        title = _bounded_score(title)
        detail = max(_bounded_score(detail), _token_overlap_score(_important_tokens(seller_desc), _important_tokens(candidate.description)))
        title_weight = TITLE_WEIGHT
        keyword_weight = KEYWORD_WEIGHT
        attribute_weight = ATTRIBUTE_WEIGHT
        if not candidate.has_comparable_attributes:
            title_weight += attribute_weight * 0.6
            keyword_weight += attribute_weight * 0.4
            attribute_weight = 0.0

        score = _bounded_score((
            title * title_weight + detail * DESCRIPTION_WEIGHT
            + candidate.keyword * keyword_weight + candidate.attribute * attribute_weight
        ) / (TITLE_WEIGHT + DESCRIPTION_WEIGHT + KEYWORD_WEIGHT + ATTRIBUTE_WEIGHT))
        if candidate.exact_identity:
            score = 1.0

        title_gate = candidate.exact_identity or title >= SIMILARITY_MIN_TITLE_EVIDENCE
        if title_gate and score >= threshold:
            classification = "VERY_STRONG" if score >= SIMILARITY_VERY_STRONG_THRESHOLD else "STRONG"
        elif score >= SIMILARITY_POSSIBLE_THRESHOLD:
            classification = "POSSIBLE"
        else:
            classification = "NOT_VERIFIED"
        results.append({
            **candidate.listing,
            "similarity_score": score,
            "title_similarity": title,
            "description_similarity": detail,
            "attribute_similarity": candidate.attribute,
            "keyword_score": candidate.keyword,
            "ranking_score": float(candidate.listing.get("ranking_score") or 0.0),
            "match_confidence": score,
            "category_match": candidate.category_match,
            "matched_attributes": candidate.matched_attributes,
            "match_classification": classification,
            "exact_identity": candidate.exact_identity,
            "title_gate": title_gate,
        })
    return results
