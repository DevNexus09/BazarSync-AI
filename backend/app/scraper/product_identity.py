from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_IDENTIFIER_KEYS = {"gtin", "gtin8", "gtin12", "gtin13", "gtin14", "ean", "upc", "isbn", "isbn10", "isbn13"}
_MODEL_KEYS = ("mpn", "model number", "model no", "manufacturer part number", "model")
_UNKNOWN = {"", "unknown", "none", "n/a", "na", "generic", "no brand", "not specified"}
_BRANDS = {
    "অ্যাপল": "apple", "আইফোন": "iphone", "আইপ্যাড": "ipad", "স্যামসাং": "samsung",
    "গ্যালাক্সি": "galaxy", "শাওমি": "xiaomi", "রেডমি": "redmi", "সনি": "sony",
    "গুগল": "google", "পিক্সেল": "pixel", "ডাভ": "dove",
}
_ACCESSORY_TYPES = {
    "cover": r"\b(?:case|cover|screen guard|screen protector|tempered glass|কভার|প্রটেক্টর)\b",
    "charger": r"\b(?:charger|চার্জার|adapter)\b",
    "replacement": r"\b(?:replacement|spare part|replacement battery|রিপ্লেসমেন্ট)\b",
}
_TECH = r"\b(?:phones?|smartphones?|iphone|galaxy|redmi|pixel|ipad|tablets?|laptops?|macbook|notebooks?|computers?|thinkpad|poco|oneplus)\b"
_BUNDLE = r"\b(?:bundle|combo|multipack|pack of [2-9]\d*|[2-9]\d*\s*pack|কম্বো|বান্ডেল)\b"
_REFURBISHED = r"\b(?:refurbished|renewed|reconditioned|open box|used|second hand|রিফারবিশড|ব্যবহৃত)\b"


def normalize_identity_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().translate(_DIGITS)
    for source, target in _BRANDS.items():
        text = re.sub(rf"(?<!\w){source}(?!\w)", target, text)
    return " ".join(text.split())


def identifier_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _gtin(value: str, key: str) -> str | None:
    digits = re.sub(r"[\s-]", "", value).upper()
    if key.startswith("isbn") and re.fullmatch(r"[0-9]{9}[0-9X]", digits):
        numbers = [int(digit) if digit != "X" else 10 for digit in digits]
        if sum((10 - index) * digit for index, digit in enumerate(numbers)) % 11:
            return None
        stem = "978" + digits[:9]
        digits = stem + str((-sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(stem))) % 10)
    lengths = {"gtin8": (8,), "gtin12": (12,), "gtin13": (13,), "gtin14": (14,),
               "ean": (8, 13), "upc": (12,), "isbn": (13,), "isbn10": (13,), "isbn13": (13,)}
    if len(digits) not in lengths.get(key, (8, 12, 13, 14)) or not re.fullmatch(r"[0-9]+", digits):
        return None
    if key.startswith("isbn") and not digits.startswith(("978", "979")):
        return None
    if len(set(digits)) == 1:
        return None
    if sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(reversed(digits))) % 10:
        return None
    return digits.zfill(14)


@dataclass(frozen=True)
class ProductIdentity:
    attributes: Mapping[str, str]
    gtins: frozenset[str]
    brand: str | None
    model: str | None
    accessory: str | None
    product_identifier: str | None
    condition: str | None
    package: str | None
    package_from_title: bool
    title_type: str | None
    title_attributes: Mapping[str, str]


@dataclass(frozen=True)
class IdentityEvidence:
    conflict: str | None = None
    exact: bool = False


def identity_from_listing(title: str, specifications: Mapping[str, str] | None, brand: str | None = None) -> ProductIdentity:
    text = normalize_identity_text(title)
    attributes = {
        " ".join(re.sub(r"[_-]+", " ", normalize_identity_text(str(key))).split()): normalize_identity_text(str(value))
        for key, value in (specifications or {}).items()
        if value is not None and normalize_identity_text(str(value)) not in _UNKNOWN
    }
    title_attributes = {}
    for field, pattern in (
        ("volume", r"\b(\d+(?:\.\d+)?\s*(?:ml|litres?|liters?|l))\b"),
        ("screen size", r"\b(\d+(?:\.\d+)?\s*(?:inches|inch))\b"),
        ("generation", r"\b((?:gen(?:eration)?\s*\d+)|(?:\d+(?:st|nd|rd|th)?\s*gen(?:eration)?))\b"),
        ("ram", r"\b(\d+(?:\.\d+)?\s*gb)\s*ram\b"),
    ):
        values = re.findall(pattern, text)
        if len(values) == 1:
            title_attributes[field] = values[0]
    if re.search(_TECH, text):
        capacity_title = re.sub(r"\b\d+(?:\.\d+)?\s*gb\s*ram\b", "", text)
        storage = re.findall(r"\b(\d+(?:\.\d+)?\s*(?:gb|tb))\b", capacity_title)
        if len(storage) == 1:
            title_attributes["storage"] = storage[0]
    gtins = frozenset(
        code for field, value in attributes.items()
        if (key := identifier_key(field)) in _IDENTIFIER_KEYS and (code := _gtin(value, key))
    )
    model = next(
        (identifier_key(attributes[key]) for key in _MODEL_KEYS
         if key in attributes and len(identifier_key(attributes[key])) >= 3 and any(c.isdigit() for c in attributes[key])),
        None,
    )
    raw_brand = normalize_identity_text(brand or "")
    if raw_brand in _UNKNOWN:
        raw_brand = attributes.get("brand", "")
    primary_title = re.split(r"\bwith\b", text, maxsplit=1)[0]
    types = {"shampoo", "conditioner", "kettle", "bottle", "mug", "cup", "plate"}
    title_types = types & set(re.findall(r"[a-z]+", primary_title))
    title_type = next(iter(title_types)) if len(title_types) == 1 else None
    accessory = next((kind for kind, pattern in _ACCESSORY_TYPES.items() if re.search(pattern, primary_title)), None)
    condition_text = attributes.get("condition", "")
    condition = (
        "refurbished" if re.search(_REFURBISHED, text + " " + condition_text)
        else "new" if condition_text in {"new", "brand new"} or re.search(r"\b(?:new|factory sealed|নতুন)\b", text)
        else None
    )
    pack_text = attributes.get("pack quantity") or attributes.get("pack size") or attributes.get("number of items", "")
    title_count = re.search(r"\b(?:pack of\s*)?([1-9]\d*)\s*(?:pack|pcs|pieces)\b|\bpack of ([1-9]\d*)\b", text)
    count = title_count or re.fullmatch(r"[1-9]\d*", pack_text)
    bundle_match = re.search(_BUNDLE, text)
    if count:
        package = next(group for group in count.groups() if group is not None) if count.groups() else count[0]
    elif bundle_match:
        package = "bundle"
    else:
        package = None
    # A seller SKU or marketplace listing ID is scoped to that seller/listing. Only an explicitly
    # labelled manufacturer product identifier is comparable across stores.
    product_identifier = identifier_key(attributes.get("manufacturer product identifier", "")) or None
    return ProductIdentity(attributes, gtins, raw_brand if raw_brand not in _UNKNOWN else None,
                           model, accessory, product_identifier, condition, package, bool(title_count or bundle_match),
                           title_type, title_attributes)


def compare_identities(
    seller: ProductIdentity, candidate: ProductIdentity, *, context: str,
    seller_brand: str | None, candidate_brand: str | None, dimensions_tolerance: float,
) -> IdentityEvidence:
    for name, left, right in (
        ("brand", seller_brand, candidate_brand), ("model", seller.model, candidate.model),
        ("manufacturer_product_identifier", seller.product_identifier, candidate.product_identifier),
        ("accessory", seller.accessory, candidate.accessory), ("condition", seller.condition, candidate.condition),
    ):
        if left and right and left != right:
            return IdentityEvidence(conflict=name)
    if candidate.condition == "refurbished" and seller.condition is None:
        return IdentityEvidence(conflict="condition")
    incompatible_types = (
        {"shampoo", "conditioner"}, {"bottle", "kettle"}, {"mug", "plate"}, {"cup", "plate"},
    )
    if {seller.title_type, candidate.title_type} in incompatible_types:
        return IdentityEvidence(conflict="product_type")
    if ((seller.package and candidate.package and seller.package != candidate.package)
            or (seller.package_from_title and candidate.package is None)
            or (candidate.package_from_title and seller.package is None)):
        return IdentityEvidence(conflict="package")
    left_color = seller.attributes.get("color") or seller.attributes.get("colour")
    right_color = candidate.attributes.get("color") or candidate.attributes.get("colour")
    known_colors = {"black", "white", "red", "blue", "green", "pink", "silver", "gold", "gray", "purple"}
    left_color = "gray" if left_color == "grey" else left_color
    right_color = "gray" if right_color == "grey" else right_color
    if left_color in known_colors and right_color in known_colors and left_color != right_color:
        return IdentityEvidence(conflict="color")
    if seller.gtins and candidate.gtins and seller.gtins.isdisjoint(candidate.gtins):
        return IdentityEvidence(conflict="gtin")

    keys = {
        "generation": ("generation", "gen"),
        "capacity": ("volume", "net volume", "capacity"),
        "battery": ("battery capacity", "battery"),
        "screen": ("screen size", "display size", "screen diagonal"),
        "dimensions": ("dimensions", "dimension"),
    }
    if re.search(_TECH, normalize_identity_text(context)):
        keys.update({"ram": ("ram", "memory ram"), "storage": ("storage", "rom", "ssd", "hdd", "storage capacity")})
    for name, aliases in keys.items():
        tolerance = Decimal(str(dimensions_tolerance)) if name in {"screen", "dimensions"} else Decimal(0)
        left_values = _measurements(seller, aliases, name)
        right_values = _measurements(candidate, aliases, name)
        for left in left_values:
            for right in right_values:
                if len(left) == len(right) and any(
                    abs(a - b) > max(a, b) * tolerance for a, b in zip(left, right, strict=True)
                ):
                    return IdentityEvidence(conflict=name)

    exact = bool(
        (len(seller.gtins) == len(candidate.gtins) == 1 and seller.gtins == candidate.gtins)
        or (seller_brand and seller_brand == candidate_brand and (
            (seller.model and seller.model == candidate.model)
            or (seller.product_identifier and seller.product_identifier == candidate.product_identifier)
        ))
    )
    return IdentityEvidence(exact=exact)


def _measurements(identity: ProductIdentity, aliases: tuple[str, ...], kind: str) -> set[tuple[Decimal, ...]]:
    return {
        value for fields in (identity.attributes, identity.title_attributes)
        for alias in aliases if alias in fields
        if (value := _measurement(fields[alias], kind)) is not None
    }


def _measurement(value: str, kind: str) -> tuple[Decimal, ...] | None:
    if kind == "generation":
        match = re.fullmatch(r"(?:gen(?:eration)?\s*)?(\d+)(?:st|nd|rd|th)?(?:\s*gen(?:eration)?)?", value)
        return (Decimal(match[1]),) if match else None
    if kind in {"ram", "storage"}:
        units = {"mb": Decimal(1) / 1024, "gb": Decimal(1), "tb": Decimal(1024)}
    elif kind == "capacity":
        units = {"ml": Decimal(1), "l": Decimal(1000), "litre": Decimal(1000), "liter": Decimal(1000),
                 "litres": Decimal(1000), "liters": Decimal(1000)}
    elif kind == "battery":
        units = {"mah": Decimal(1), "ah": Decimal(1000)}
    else:
        units = {"mm": Decimal(1), "cm": Decimal(10), "in": Decimal("25.4"),
                 "inch": Decimal("25.4"), "inches": Decimal("25.4"), '"': Decimal("25.4")}
    parts = re.split(r"\s*[x×]\s*", value)
    if len(parts) > 3 or (kind != "dimensions" and len(parts) != 1):
        return None
    matches = [re.fullmatch(r"(\d{1,9}(?:\.\d{1,4})?)\s*([a-z\"]*)", part) for part in parts]
    if not all(matches) or matches[-1][2] not in units:
        return None
    unit = matches[-1][2]
    if any(match[2] and match[2] not in units for match in matches):
        return None
    amounts = tuple(Decimal(match[1]) * units[match[2] or unit] for match in matches)
    return tuple(sorted(amounts)) if kind == "dimensions" else amounts
