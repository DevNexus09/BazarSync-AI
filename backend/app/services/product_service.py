from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.products import ProductCreate, ProductUpdate

INVENTORY_RECALC_SPEC_KEYS = {
    "incoming_quantity",
    "confirmed_incoming_quantity",
    "purchase_order_quantity",
    "supplier_lead_time",
    "safety_buffer_days",
    "review_period_days",
    "minimum_order_quantity",
    "moq",
    "pack_size",
    "case_size",
}


class ProductNotFoundError(Exception):
    pass


class ProductService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_products(self, seller_id: UUID, *, limit: int, offset: int) -> tuple[list[Product], int]:
        statement = (
            select(Product)
            .where(Product.seller_id == seller_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = self._db.execute(statement).scalars().all()

        total_statement = select(func.count()).select_from(Product).where(Product.seller_id == seller_id)
        total = self._db.execute(total_statement).scalar_one()
        return items, total

    def get_product(self, seller_id: UUID, product_id: UUID) -> Product | None:
        statement = select(Product).where(
            Product.seller_id == seller_id,
            Product.id == product_id,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def create_product(self, seller_id: UUID, payload: ProductCreate) -> Product:
        searchable_text = self._build_searchable_text(
            title=payload.title,
            description=payload.description,
            category=payload.category,
            specifications=payload.specifications or {},
        )
        product = Product(
            seller_id=seller_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            specifications=payload.specifications or {},
            searchable_text=searchable_text,
            cost_price=payload.cost_price,
            selling_price=payload.selling_price,
            stock_quantity=payload.stock_quantity,
            supplier_lead_time=payload.supplier_lead_time,
            minimum_margin=payload.minimum_margin,
        )
        self._db.add(product)
        self._db.commit()
        self._db.refresh(product)
        return product

    def update_product(self, seller_id: UUID, product_id: UUID, payload: ProductUpdate) -> Product:
        product = self.get_product(seller_id, product_id)
        if not product:
            raise ProductNotFoundError

        old_stock_quantity = product.stock_quantity
        old_cost_price = product.cost_price
        old_supplier_lead_time = product.supplier_lead_time
        old_specifications = dict(product.specifications or {})
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(product, field, value)

        if any(
            field in updates
            for field in ("title", "description", "category", "specifications")
        ):
            product.searchable_text = self._build_searchable_text(
                title=product.title,
                description=product.description or "",
                category=product.category or "",
                specifications=product.specifications or {},
            )

        self._db.commit()
        self._db.refresh(product)
        if _requires_inventory_recalculation(
            updates=updates,
            old_stock_quantity=old_stock_quantity,
            old_supplier_lead_time=old_supplier_lead_time,
            old_specifications=old_specifications,
            product=product,
        ):
            from app.tasks.inventory_intelligence_workflow_tasks import enqueue_product_recalculation

            enqueue_product_recalculation(
                seller_id=seller_id,
                product_id=product_id,
                reason="product_inventory_inputs_changed",
            )
        if _requires_dead_stock_recalculation(
            updates=updates,
            old_stock_quantity=old_stock_quantity,
            old_cost_price=old_cost_price,
            product=product,
        ):
            from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

            reason = "product_cost_update" if "cost_price" in updates and product.cost_price != old_cost_price else "inventory_adjustment"
            enqueue_dead_stock_recalculation(
                seller_id=seller_id,
                product_id=product_id,
                reason=reason,
            )
        return product

    @staticmethod
    def _build_searchable_text(
        *,
        title: str,
        description: str,
        category: str,
        specifications: dict[str, str],
    ) -> str:
        specs_text = " ".join(
            f"{key} {value}".strip()
            for key, value in specifications.items()
            if key and value
        )
        combined = " ".join(
            part for part in (title, description, category, specs_text) if part
        )
        return " ".join(combined.split()).strip()

    def delete_product(self, seller_id: UUID, product_id: UUID) -> None:
        product = self.get_product(seller_id, product_id)
        if not product:
            raise ProductNotFoundError
        self._db.delete(product)
        self._db.commit()


def _requires_inventory_recalculation(
    *,
    updates: dict,
    old_stock_quantity: int,
    old_supplier_lead_time: int,
    old_specifications: dict[str, str],
    product: Product,
) -> bool:
    if "stock_quantity" in updates and product.stock_quantity != old_stock_quantity:
        return True
    if "supplier_lead_time" in updates and product.supplier_lead_time != old_supplier_lead_time:
        return True
    if "specifications" not in updates:
        return False
    new_specifications = product.specifications or {}
    for key in INVENTORY_RECALC_SPEC_KEYS:
        if old_specifications.get(key) != new_specifications.get(key):
            return True
    return False


def _requires_dead_stock_recalculation(
    *,
    updates: dict,
    old_stock_quantity: int,
    old_cost_price,
    product: Product,
) -> bool:
    if "stock_quantity" in updates and product.stock_quantity != old_stock_quantity:
        return True
    if "cost_price" in updates and product.cost_price != old_cost_price:
        return True
    return False
