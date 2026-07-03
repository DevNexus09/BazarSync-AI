from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_policy import PricingObjective, PricingPolicy
from app.models.product import Product
from app.schemas.pricing_policy import (
    FeeBreakdownResponse,
    MarketplaceFeePolicyResponse,
    MarketplaceFeePolicyUpsert,
    MinimumSafePricePreviewResponse,
    PricingPolicyResponse,
    PricingPolicyUpsert,
)
from app.services.pricing_calculator import FeeInputs, PricingCalculator


class PricingPolicyNotFoundError(Exception):
    pass


class ProductOwnershipError(Exception):
    pass


class PricingPolicyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_product_policy(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
    ) -> PricingPolicyResponse:
        product = self._product_for_seller(seller_id=seller_id, product_id=product_id)
        policy = self._active_policy(seller_id=seller_id, product_id=product_id, marketplace=marketplace)
        if policy:
            return PricingPolicyResponse.model_validate(policy)
        return self._default_policy_response(product=product, marketplace=marketplace)

    def upsert_product_policy(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        payload: PricingPolicyUpsert,
    ) -> PricingPolicyResponse:
        product = self._product_for_seller(seller_id=seller_id, product_id=product_id)
        effective_from = _ensure_utc(payload.effective_from or datetime.now(timezone.utc))
        if payload.effective_to and _ensure_utc(payload.effective_to) <= effective_from:
            raise ValueError("effective_to must be after effective_from")
        if payload.minimum_allowed_price and payload.maximum_allowed_price and payload.minimum_allowed_price > payload.maximum_allowed_price:
            raise ValueError("minimum_allowed_price cannot exceed maximum_allowed_price")

        policy = self._active_policy(seller_id=seller_id, product_id=product_id, marketplace=payload.marketplace)
        if policy is None:
            policy = PricingPolicy(
                seller_id=seller_id,
                product_id=product_id,
                marketplace=payload.marketplace,
                currency=payload.currency.upper(),
                minimum_margin_rate=payload.minimum_margin_rate or _default_margin_rate(product.minimum_margin),
                minimum_unit_profit=payload.minimum_unit_profit,
                maximum_price_decrease_rate=payload.maximum_price_decrease_rate,
                maximum_price_increase_rate=payload.maximum_price_increase_rate,
                minimum_allowed_price=payload.minimum_allowed_price,
                maximum_allowed_price=payload.maximum_allowed_price,
                price_increment=payload.price_increment,
                recommendation_cooldown_hours=payload.recommendation_cooldown_hours,
                objective=payload.objective,
                is_active=payload.is_active,
                effective_from=effective_from,
                effective_to=_ensure_utc(payload.effective_to) if payload.effective_to else None,
            )
            self._db.add(policy)
        else:
            policy.currency = payload.currency.upper()
            policy.minimum_margin_rate = payload.minimum_margin_rate or _default_margin_rate(product.minimum_margin)
            policy.minimum_unit_profit = payload.minimum_unit_profit
            policy.maximum_price_decrease_rate = payload.maximum_price_decrease_rate
            policy.maximum_price_increase_rate = payload.maximum_price_increase_rate
            policy.minimum_allowed_price = payload.minimum_allowed_price
            policy.maximum_allowed_price = payload.maximum_allowed_price
            policy.price_increment = payload.price_increment
            policy.recommendation_cooldown_hours = payload.recommendation_cooldown_hours
            policy.objective = payload.objective
            policy.is_active = payload.is_active
            policy.effective_from = effective_from
            policy.effective_to = _ensure_utc(payload.effective_to) if payload.effective_to else None
        self._db.commit()
        self._db.refresh(policy)
        return PricingPolicyResponse.model_validate(policy)

    def create_marketplace_fee_policy(
        self,
        *,
        seller_id: UUID,
        payload: MarketplaceFeePolicyUpsert,
    ) -> MarketplaceFeePolicyResponse:
        if payload.product_id:
            self._product_for_seller(seller_id=seller_id, product_id=payload.product_id)
        effective_from = _ensure_utc(payload.effective_from or datetime.now(timezone.utc))
        if payload.effective_to and _ensure_utc(payload.effective_to) <= effective_from:
            raise ValueError("effective_to must be after effective_from")
        fee = MarketplaceFeePolicy(
            seller_id=seller_id,
            product_id=payload.product_id,
            marketplace=payload.marketplace,
            category=payload.category,
            currency=payload.currency.upper(),
            percentage_commission_rate=payload.percentage_commission_rate,
            payment_fee_rate=payload.payment_fee_rate,
            fixed_per_order_fee=payload.fixed_per_order_fee,
            fixed_per_unit_fee=payload.fixed_per_unit_fee,
            fulfilment_fee=payload.fulfilment_fee,
            shipping_subsidy=payload.shipping_subsidy,
            other_variable_cost=payload.other_variable_cost,
            source=payload.source,
            version=payload.version,
            is_active=payload.is_active,
            effective_from=effective_from,
            effective_to=_ensure_utc(payload.effective_to) if payload.effective_to else None,
        )
        self._db.add(fee)
        self._db.commit()
        self._db.refresh(fee)
        return _fee_response(fee, is_default=False, scope=_fee_scope(fee))

    def list_marketplace_fee_policies(
        self,
        *,
        seller_id: UUID,
        product_id: UUID | None,
        marketplace: str | None,
    ) -> list[MarketplaceFeePolicyResponse]:
        product = None
        if product_id:
            product = self._product_for_seller(seller_id=seller_id, product_id=product_id)
        statement = select(MarketplaceFeePolicy).where(MarketplaceFeePolicy.seller_id == seller_id)
        if marketplace:
            statement = statement.where(MarketplaceFeePolicy.marketplace == marketplace)
        if product:
            statement = statement.where(
                (MarketplaceFeePolicy.product_id == product.id)
                | (
                    MarketplaceFeePolicy.product_id.is_(None)
                    & (MarketplaceFeePolicy.category == product.category)
                )
                | (
                    MarketplaceFeePolicy.product_id.is_(None)
                    & MarketplaceFeePolicy.category.is_(None)
                )
            )
        statement = statement.order_by(
            MarketplaceFeePolicy.effective_from.desc(),
            MarketplaceFeePolicy.created_at.desc(),
        )
        policies = self._db.execute(statement).scalars().all()
        return [_fee_response(policy, is_default=False, scope=_fee_scope(policy)) for policy in policies]

    def expire_marketplace_fee_policy(
        self,
        *,
        seller_id: UUID,
        fee_policy_id: UUID,
        effective_to: datetime,
    ) -> MarketplaceFeePolicyResponse:
        policy = self._db.execute(
            select(MarketplaceFeePolicy).where(
                MarketplaceFeePolicy.id == fee_policy_id,
                MarketplaceFeePolicy.seller_id == seller_id,
            )
        ).scalar_one_or_none()
        if policy is None:
            raise PricingPolicyNotFoundError
        expires_at = _ensure_utc(effective_to)
        if expires_at <= _ensure_utc(policy.effective_from):
            raise ValueError("effective_to must be after effective_from")
        policy.effective_to = expires_at
        self._db.commit()
        self._db.refresh(policy)
        return _fee_response(policy, is_default=False, scope=_fee_scope(policy))

    def effective_fee_policy(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
        as_of: datetime | None = None,
    ) -> MarketplaceFeePolicyResponse:
        product = self._product_for_seller(seller_id=seller_id, product_id=product_id)
        fee = self._effective_fee(product=product, seller_id=seller_id, marketplace=marketplace, as_of=as_of)
        if fee:
            return _fee_response(fee, is_default=False, scope=_fee_scope(fee))
        return MarketplaceFeePolicyResponse(
            id=None,
            seller_id=seller_id,
            product_id=None,
            marketplace=marketplace,
            category=None,
            currency="BDT",
            percentage_commission_rate=Decimal("0.000000"),
            payment_fee_rate=Decimal("0.000000"),
            fixed_per_order_fee=Decimal("0.00"),
            fixed_per_unit_fee=Decimal("0.00"),
            fulfilment_fee=Decimal("0.00"),
            shipping_subsidy=Decimal("0.00"),
            other_variable_cost=Decimal("0.00"),
            source="DEFAULT_ZERO_FEES",
            version="default",
            is_active=True,
            effective_from=_ensure_utc(as_of or datetime.now(timezone.utc)),
            effective_to=None,
            is_default=True,
            scope="seller",
        )

    def preview_minimum_safe_price(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
        candidate_price: Decimal | None,
        as_of: datetime | None = None,
    ) -> MinimumSafePricePreviewResponse:
        product = self._product_for_seller(seller_id=seller_id, product_id=product_id)
        policy = self.get_product_policy(seller_id=seller_id, product_id=product_id, marketplace=marketplace)
        fee_policy = self.effective_fee_policy(seller_id=seller_id, product_id=product_id, marketplace=marketplace, as_of=as_of)
        fees = _fee_inputs(fee_policy)
        calculator = PricingCalculator(currency=policy.currency)
        minimum_safe = calculator.calculate_minimum_safe_price(
            unit_cost=product.cost_price,
            fees=fees,
            minimum_margin_rate=policy.minimum_margin_rate or _default_margin_rate(product.minimum_margin),
            minimum_unit_profit=policy.minimum_unit_profit,
            price_increment=policy.price_increment,
        )
        validation = None
        if candidate_price is not None:
            validation = calculator.validate_candidate_price(
                candidate_price=candidate_price,
                current_price=product.selling_price,
                unit_cost=product.cost_price,
                fees=fees,
                minimum_margin_rate=policy.minimum_margin_rate or _default_margin_rate(product.minimum_margin),
                minimum_unit_profit=policy.minimum_unit_profit,
                price_increment=policy.price_increment,
                minimum_allowed_price=policy.minimum_allowed_price,
                maximum_allowed_price=policy.maximum_allowed_price,
                maximum_price_decrease_rate=policy.maximum_price_decrease_rate,
                maximum_price_increase_rate=policy.maximum_price_increase_rate,
            )
        fixed_costs = fees.fixed_costs
        return MinimumSafePricePreviewResponse(
            product_id=product.id,
            marketplace=marketplace,
            currency=policy.currency,
            unit_cost=product.cost_price,
            current_price=product.selling_price,
            minimum_margin_rate=policy.minimum_margin_rate or _default_margin_rate(product.minimum_margin),
            minimum_unit_profit=policy.minimum_unit_profit,
            percentage_fee_rate=fees.percentage_fee_rate,
            fixed_costs=fixed_costs,
            minimum_safe_price=minimum_safe,
            candidate_price=candidate_price,
            candidate_valid=validation.is_valid if validation else None,
            candidate_reasons=validation.reasons if validation else [],
            unit_profit=validation.unit_profit if validation else None,
            margin_rate=validation.margin_rate if validation else None,
            fee_breakdown=_breakdown_response(validation.fee_breakdown) if validation else None,
        )

    def _product_for_seller(self, *, seller_id: UUID, product_id: UUID) -> Product:
        product = self._db.execute(
            select(Product).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()
        if product is None:
            raise ProductOwnershipError
        return product

    def _active_policy(self, *, seller_id: UUID, product_id: UUID, marketplace: str) -> PricingPolicy | None:
        return self._db.execute(
            select(PricingPolicy)
            .where(
                PricingPolicy.seller_id == seller_id,
                PricingPolicy.product_id == product_id,
                PricingPolicy.marketplace == marketplace,
                PricingPolicy.is_active.is_(True),
            )
            .order_by(PricingPolicy.effective_from.desc(), PricingPolicy.created_at.desc())
        ).scalar_one_or_none()

    def _effective_fee(
        self,
        *,
        product: Product,
        seller_id: UUID,
        marketplace: str,
        as_of: datetime | None,
    ) -> MarketplaceFeePolicy | None:
        timestamp = _ensure_utc(as_of or datetime.now(timezone.utc))
        statement = (
            select(MarketplaceFeePolicy)
            .where(
                MarketplaceFeePolicy.seller_id == seller_id,
                MarketplaceFeePolicy.marketplace == marketplace,
                MarketplaceFeePolicy.is_active.is_(True),
                MarketplaceFeePolicy.effective_from <= timestamp,
                ((MarketplaceFeePolicy.effective_to.is_(None)) | (MarketplaceFeePolicy.effective_to > timestamp)),
                (
                    (MarketplaceFeePolicy.product_id == product.id)
                    | (
                        MarketplaceFeePolicy.product_id.is_(None)
                        & (MarketplaceFeePolicy.category == product.category)
                    )
                    | (
                        MarketplaceFeePolicy.product_id.is_(None)
                        & MarketplaceFeePolicy.category.is_(None)
                    )
                ),
            )
        )
        candidates = self._db.execute(statement).scalars().all()
        return select_effective_fee_policy(
            candidates,
            product_id=product.id,
            category=product.category,
            as_of=timestamp,
        )

    @staticmethod
    def _default_policy_response(*, product: Product, marketplace: str) -> PricingPolicyResponse:
        return PricingPolicyResponse(
            id=None,
            seller_id=product.seller_id,
            product_id=product.id,
            marketplace=marketplace,
            currency="BDT",
            minimum_margin_rate=_default_margin_rate(product.minimum_margin),
            minimum_unit_profit=Decimal("0.00"),
            maximum_price_decrease_rate=None,
            maximum_price_increase_rate=None,
            minimum_allowed_price=None,
            maximum_allowed_price=None,
            price_increment=Decimal("1.00"),
            recommendation_cooldown_hours=24,
            objective=PricingObjective.MAXIMIZE_EXPECTED_PROFIT,
            is_active=True,
            effective_from=datetime.now(timezone.utc),
            effective_to=None,
            is_default=True,
        )


def _default_margin_rate(product_minimum_margin: Decimal) -> Decimal:
    value = Decimal(str(product_minimum_margin or Decimal("0")))
    if value >= Decimal("1"):
        return (value / Decimal("100")).quantize(Decimal("0.000001"))
    return value.quantize(Decimal("0.000001"))


def select_effective_fee_policy(
    candidates: list[MarketplaceFeePolicy],
    *,
    product_id: UUID,
    category: str | None,
    as_of: datetime,
) -> MarketplaceFeePolicy | None:
    timestamp = _ensure_utc(as_of)
    valid = [
        fee
        for fee in candidates
        if fee.is_active
        and fee.effective_from <= timestamp
        and (fee.effective_to is None or fee.effective_to > timestamp)
        and (
            fee.product_id == product_id
            or (fee.product_id is None and fee.category == category)
            or (fee.product_id is None and fee.category is None)
        )
    ]
    if not valid:
        return None

    def priority(fee: MarketplaceFeePolicy) -> tuple[int, datetime, datetime]:
        if fee.product_id == product_id:
            scope_priority = 0
        elif fee.category == category:
            scope_priority = 1
        else:
            scope_priority = 2
        created_at = fee.created_at or fee.effective_from
        return (scope_priority, -fee.effective_from.timestamp(), -created_at.timestamp())

    return sorted(valid, key=priority)[0]


def _fee_inputs(policy: MarketplaceFeePolicyResponse) -> FeeInputs:
    return FeeInputs(
        percentage_commission_rate=Decimal(str(policy.percentage_commission_rate)),
        payment_fee_rate=Decimal(str(policy.payment_fee_rate)),
        fixed_per_order_fee=Decimal(str(policy.fixed_per_order_fee)),
        fixed_per_unit_fee=Decimal(str(policy.fixed_per_unit_fee)),
        fulfilment_fee=Decimal(str(policy.fulfilment_fee)),
        shipping_subsidy=Decimal(str(policy.shipping_subsidy)),
        other_variable_cost=Decimal(str(policy.other_variable_cost)),
    )


def _fee_scope(policy: MarketplaceFeePolicy) -> str:
    if policy.product_id:
        return "product"
    if policy.category:
        return "category"
    return "seller"


def _fee_response(policy: MarketplaceFeePolicy, *, is_default: bool, scope: str) -> MarketplaceFeePolicyResponse:
    return MarketplaceFeePolicyResponse(
        id=policy.id,
        seller_id=policy.seller_id,
        product_id=policy.product_id,
        marketplace=policy.marketplace,
        category=policy.category,
        currency=policy.currency,
        percentage_commission_rate=policy.percentage_commission_rate,
        payment_fee_rate=policy.payment_fee_rate,
        fixed_per_order_fee=policy.fixed_per_order_fee,
        fixed_per_unit_fee=policy.fixed_per_unit_fee,
        fulfilment_fee=policy.fulfilment_fee,
        shipping_subsidy=policy.shipping_subsidy,
        other_variable_cost=policy.other_variable_cost,
        source=policy.source,
        version=policy.version,
        is_active=policy.is_active,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        is_default=is_default,
        scope=scope,
    )


def _breakdown_response(breakdown) -> FeeBreakdownResponse:
    return FeeBreakdownResponse(
        price=breakdown.price,
        percentage_commission_amount=breakdown.percentage_commission_amount,
        payment_fee_amount=breakdown.payment_fee_amount,
        fixed_per_order_fee=breakdown.fixed_per_order_fee,
        fixed_per_unit_fee=breakdown.fixed_per_unit_fee,
        fulfilment_fee=breakdown.fulfilment_fee,
        shipping_subsidy=breakdown.shipping_subsidy,
        other_variable_cost=breakdown.other_variable_cost,
        total_fee_amount=breakdown.total_fee_amount,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
