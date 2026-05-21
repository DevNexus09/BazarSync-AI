from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.scraper import selectors
from app.scraper.utils import (
    normalize_sold_count,
    normalize_text,
    parse_compact_number,
    parse_discount_percentage,
    parse_float,
    parse_price,
    to_absolute_url,
)

logger = logging.getLogger(__name__)


class DarazParser:
    def parse_products(self, html: str, max_results: int | None) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        cards = self._select_cards(soup)
        limit = max_results or len(cards)
        results: list[dict[str, Any]] = []

        for position, card in enumerate(cards[:limit], start=1):
            product_data = self._parse_card(card, position)
            if product_data:
                results.append(product_data)
        return results

    def parse_products_from_json(self, payload: dict[str, Any], max_results: int | None) -> list[dict[str, Any]]:
        items = payload.get("mods", {}).get("listItems", [])
        limit = max_results or len(items)
        results: list[dict[str, Any]] = []
        for position, item in enumerate(items[:limit], start=1):
            product_data = self._parse_json_item(item, position)
            if product_data:
                results.append(product_data)
        return results

    def _select_cards(self, soup: BeautifulSoup) -> list[Tag]:
        for selector in selectors.PRODUCT_CARD_SELECTORS:
            cards = soup.select(selector)
            if cards:
                return cards
        return []

    def _parse_card(self, card: Tag, position: int) -> dict[str, Any] | None:
        title_node = self._select_first(card, selectors.PRODUCT_TITLE_SELECTORS)
        title = normalize_text(self._get_text_or_attr(title_node, "title"))

        link_node = self._select_first(card, selectors.PRODUCT_LINK_SELECTORS)
        url = to_absolute_url(self._get_attr(link_node, "href"))

        price_text = self._select_text(card, selectors.PRICE_SELECTORS)
        original_price_text = self._select_text(card, selectors.ORIGINAL_PRICE_SELECTORS)
        discount_text = self._select_text(card, selectors.DISCOUNT_SELECTORS)
        store_text = self._select_text(card, selectors.STORE_NAME_SELECTORS)
        rating_text = self._select_text(card, selectors.RATING_SELECTORS)
        rating_count_text = self._select_text(card, selectors.RATING_COUNT_SELECTORS)
        sold_text = self._select_text(card, selectors.SOLD_COUNT_SELECTORS)
        stock_text = self._select_text(card, selectors.STOCK_STATUS_SELECTORS)

        image_node = self._select_first(card, selectors.IMAGE_SELECTORS)
        image_url = self._get_attr(image_node, "src") or self._get_attr(image_node, "data-src")
        image_url = to_absolute_url(image_url)

        if not title and not url and not price_text:
            logger.debug("Skipping empty product card at position %s.", position)
            return None

        return {
            "product_title": title,
            "product_price": parse_price(price_text),
            "original_price": parse_price(original_price_text),
            "discount_percentage": parse_discount_percentage(discount_text),
            "store_name": normalize_text(store_text),
            "rating": parse_float(rating_text),
            "rating_count": parse_compact_number(rating_count_text),
            "sold_count": normalize_sold_count(sold_text),
            "stock_status": normalize_text(stock_text),
            "daraz_product_url": url,
            "product_image_url": image_url,
            "search_position": position,
        }

    def _parse_json_item(self, item: dict[str, Any], position: int) -> dict[str, Any] | None:
        title = normalize_text(item.get("name"))
        price = parse_price(str(item.get("price") or item.get("priceShow") or ""))
        original_price = parse_price(str(item.get("originalPrice") or item.get("originalPriceShow") or ""))
        discount = parse_discount_percentage(str(item.get("discount") or ""))
        if discount == 0 and original_price > 0 and price > 0 and original_price > price:
            discount = int(round((1 - price / original_price) * 100))

        sold_raw = item.get("itemSoldCntShow") or item.get("soldCount")
        sold_text = normalize_sold_count(str(sold_raw) if sold_raw else "")
        in_stock = item.get("inStock")
        stock_status = "in_stock" if in_stock is True else "out_of_stock" if in_stock is False else ""

        url = to_absolute_url(str(item.get("itemUrl") or ""))
        image_url = to_absolute_url(str(item.get("image") or ""))

        if not title and not url and price == 0:
            return None

        return {
            "product_title": title,
            "product_price": price,
            "original_price": original_price,
            "discount_percentage": discount,
            "store_name": normalize_text(item.get("sellerName")),
            "rating": parse_float(str(item.get("ratingScore") or "")),
            "rating_count": parse_compact_number(str(item.get("review") or "")),
            "sold_count": sold_text,
            "stock_status": stock_status,
            "daraz_product_url": url,
            "product_image_url": image_url,
            "search_position": position,
        }

    def parse_product_detail(self, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        description = ""
        for selector in selectors.DETAIL_DESCRIPTION_SELECTORS:
            node = soup.select_one(selector)
            if node:
                description = normalize_text(node.get_text(" ", strip=True))
                if description:
                    break

        specifications: dict[str, str] = {}
        spec_sections: list[Tag] = []
        for selector in selectors.DETAIL_SPEC_SECTION_SELECTORS:
            spec_sections = soup.select(selector)
            if spec_sections:
                break

        for section in spec_sections:
            rows = section.select(",".join(selectors.DETAIL_SPEC_ROW_SELECTORS))
            for row in rows:
                key = self._select_text(row, selectors.DETAIL_SPEC_KEY_SELECTORS)
                value = self._select_text(row, selectors.DETAIL_SPEC_VALUE_SELECTORS)
                if not key or not value:
                    text = normalize_text(row.get_text(" ", strip=True))
                    if ":" in text:
                        key, value = [part.strip() for part in text.split(":", 1)]
                if key and value:
                    specifications[key] = value

        brand = ""
        for selector in selectors.DETAIL_BRAND_SELECTORS:
            node = soup.select_one(selector)
            if node:
                brand = normalize_text(node.get_text(" ", strip=True))
                if brand:
                    break

        category = ""
        breadcrumb_nodes = []
        for selector in selectors.DETAIL_BREADCRUMB_SELECTORS:
            breadcrumb_nodes = soup.select(selector)
            if breadcrumb_nodes:
                break
        if breadcrumb_nodes:
            breadcrumb_texts = [
                normalize_text(node.get_text(" ", strip=True))
                for node in breadcrumb_nodes
            ]
            if len(breadcrumb_texts) >= 2:
                category = breadcrumb_texts[-2]
            elif breadcrumb_texts:
                category = breadcrumb_texts[-1]

        if not brand:
            for key in ("brand", "Brand"):
                if key in specifications:
                    brand = specifications[key]
                    break

        if not category:
            for key in ("category", "Category"):
                if key in specifications:
                    category = specifications[key]
                    break

        return {
            "product_description": description,
            "product_category": category,
            "product_brand": brand,
            "product_attributes": specifications,
        }

    def _select_first(self, root: Tag, selectors_list: list[str]) -> Tag | None:
        for selector in selectors_list:
            node = root.select_one(selector)
            if node:
                return node
        return None

    def _select_text(self, root: Tag, selectors_list: list[str]) -> str:
        node = self._select_first(root, selectors_list)
        return normalize_text(node.get_text(strip=True) if node else "")

    def _get_attr(self, node: Tag | None, attr: str) -> str:
        if not node:
            return ""
        value = node.get(attr)
        return value if isinstance(value, str) else ""

    def _get_text_or_attr(self, node: Tag | None, attr: str) -> str:
        if not node:
            return ""
        attr_value = node.get(attr)
        if isinstance(attr_value, str) and attr_value.strip():
            return attr_value
        return node.get_text(strip=True)
