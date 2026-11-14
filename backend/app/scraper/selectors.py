from __future__ import annotations

PRODUCT_CARD_SELECTORS = [
    "[data-qa-locator='product-item']",
    "div.gridItem--Yd0sa",
]

PRODUCT_TITLE_SELECTORS = [
    "a[title]",
    "div.title--wFj93 a",
    "div.title a",
]

PRODUCT_LINK_SELECTORS = [
    "a[title]",
    "a[href]",
]

PRICE_SELECTORS = [
    "[data-qa-locator='product-item-price']",
    "span.price",
    "span.price--NVB62",
]

ORIGINAL_PRICE_SELECTORS = [
    "del",
    "span.price--F8sUZ",
]

DISCOUNT_SELECTORS = [
    "span.discount--HADrg",
    "span.discount",
]

STORE_NAME_SELECTORS = [
    "[data-qa-locator='product-item-seller']",
    "div.seller-info--THVGd a",
    "div.store-name a",
]

RATING_SELECTORS = [
    "span.rating--pwPrV",
    "div.rating--pwPrV",
]

RATING_COUNT_SELECTORS = [
    "span.review--UUyMr",
    "span.rating__review",
]

SOLD_COUNT_SELECTORS = [
    "span.quantity--fA0Pc",
    "span.sold-count",
]

IMAGE_SELECTORS = [
    "img",
]

STOCK_STATUS_SELECTORS = [
    "span.in-stock",
    "span.stock",
]

DETAIL_DESCRIPTION_SELECTORS = [
    "div.pdp-product-detail__desc",
    "div#module_product_detail div.pdp-product-detail",
    ".product-description",
    "div.description",
]

DETAIL_SPEC_SECTION_SELECTORS = [
    "div.pdp-product-detail__specification",
    "div#module_product_detail",
    ".product-specification",
    "div.specification",
]

DETAIL_SPEC_ROW_SELECTORS = [
    "tr",
    "li",
    "div.specification-item",
]

DETAIL_SPEC_KEY_SELECTORS = [
    "th",
    "span.specification-title",
    "span.key",
    "div.specification-key",
]

DETAIL_SPEC_VALUE_SELECTORS = [
    "td",
    "span.specification-value",
    "span.value",
    "div.specification-value",
]

DETAIL_BREADCRUMB_SELECTORS = [
    "ul.breadcrumb li",
    "ol.breadcrumb li",
    "nav.breadcrumb li",
]

DETAIL_BRAND_SELECTORS = [
    "a[data-qa-locator='breadcrumb-brand']",
    "div.pdp-product-brand a",
    "a.brand",
]


CARD_FIELD_SELECTORS = {
    "current_price": PRICE_SELECTORS,
    "original_price": ORIGINAL_PRICE_SELECTORS,
    "discount_percentage": DISCOUNT_SELECTORS,
    "seller_name": STORE_NAME_SELECTORS,
    "rating": RATING_SELECTORS,
    "review_count": RATING_COUNT_SELECTORS,
    "sold_label": SOLD_COUNT_SELECTORS,
    "stock_text": STOCK_STATUS_SELECTORS,
}
JSON_LD_SELECTOR = 'script[type="application/ld+json"]'
APPLICATION_JSON_SELECTOR = 'script[type="application/json"]'
