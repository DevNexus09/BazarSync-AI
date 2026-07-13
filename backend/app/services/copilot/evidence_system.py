from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NO_CONTEXT = "NO_CONTEXT"


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    domain: str
    source_type: str
    source_table: str
    source_id: str
    product_id: str | None = None
    product_name: str | None = None
    title: str = "Evidence"
    summary: str = ""
    snippet: str | None = None
    event_time: str | None = None
    freshness: str = FreshnessStatus.UNKNOWN.value
    confidence: str = ConfidenceLevel.LOW.value
    url: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class MissingDataItem:
    key: str
    domain: str
    message: str
    blocking: bool
    next_action: str
    required_for: list[str]
    severity: str
    source_table: str | None = None
    setup_href: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class DataFreshnessItem:
    domain: str
    source_table: str | None
    latest_available_at: str | None
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class ToolUsageItem:
    tool_name: str
    domain: str
    status: str
    duration_ms: int
    evidence_count: int
    missing_data_count: int

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    level: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "reasons": list(self.reasons)}


class CopilotEvidenceBuilder:
    def build(self, tool_results: list[ToolExecutionResult]) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        seen: set[str] = set()
        for result in tool_results:
            domain = _domain_for_tool(result)
            for index, raw in enumerate(result.evidence):
                item = _evidence_item(raw, result=result, domain=domain, index=index)
                if item.evidence_id in seen:
                    continue
                evidence.append(item)
                seen.add(item.evidence_id)
        return evidence


class CopilotMissingDataAggregator:
    def aggregate(self, tool_results: list[ToolExecutionResult], extra_missing: list[Any] | None = None) -> list[MissingDataItem]:
        items: list[MissingDataItem] = []
        for result in tool_results:
            domain = _domain_for_tool(result)
            for raw in result.missing_data:
                items.append(_missing_item(raw, domain=domain, tool_name=result.tool_name))
            if result.error:
                items.append(
                    MissingDataItem(
                        key=f"{result.tool_name.upper()}_FAILED",
                        domain=domain,
                        source_table=None,
                        message=str(result.error.get("message") or "Tool failed safely."),
                        blocking=result.status == ToolExecutionStatus.BLOCKED,
                        next_action="Retry after checking setup and data availability.",
                        setup_href=None,
                        required_for=[result.tool_name],
                        severity="HIGH" if result.status == ToolExecutionStatus.BLOCKED else "MEDIUM",
                    )
                )
        for raw in extra_missing or []:
            items.append(_missing_item(raw, domain="UNKNOWN", tool_name="copilot"))
        return _dedupe_missing(items)


class CopilotFreshnessAnalyzer:
    def analyze(self, tool_results: list[ToolExecutionResult]) -> list[DataFreshnessItem]:
        items: list[DataFreshnessItem] = []
        for result in tool_results:
            domain = _domain_for_tool(result)
            source_tables = _source_tables(result)
            latest = _latest_datetime(result.data)
            status = _freshness_status(latest, result=result)
            message = _freshness_message(status=status, tool_name=result.tool_name, latest=latest)
            for source_table in source_tables or [None]:
                items.append(
                    DataFreshnessItem(
                        domain=domain,
                        source_table=source_table,
                        latest_available_at=latest.isoformat() if latest else None,
                        status=status.value,
                        message=message,
                    )
                )
        return _dedupe_freshness(items)


class CopilotConfidenceScorer:
    def score(
        self,
        *,
        evidence: list[EvidenceItem],
        missing_data: list[MissingDataItem],
        freshness: list[DataFreshnessItem],
        tool_results: list[ToolExecutionResult],
    ) -> ConfidenceResult:
        if not evidence:
            return ConfidenceResult(ConfidenceLevel.NO_CONTEXT.value, ["No seller-specific evidence was available."])
        reasons: list[str] = []
        blocking = [item for item in missing_data if item.blocking]
        failed = [result for result in tool_results if result.status != ToolExecutionStatus.SUCCEEDED]
        stale = [item for item in freshness if item.status == FreshnessStatus.STALE.value]
        direct = [item for item in evidence if item.domain != "RAG_MEMORY"]
        memory = [item for item in evidence if item.domain == "RAG_MEMORY"]
        partial = [item for item in missing_data if "partial" in item.message.casefold() or item.severity == "MEDIUM"]

        if blocking:
            reasons.append("Blocking setup or source data is missing.")
            return ConfidenceResult(ConfidenceLevel.LOW.value, reasons)
        if failed:
            reasons.append("One or more tools failed or were blocked.")
        if stale:
            reasons.append("Some sources are stale.")
        if partial:
            reasons.append("Some calculations are partial or missing dependencies.")
        if direct and not failed and not stale and not partial:
            return ConfidenceResult(ConfidenceLevel.HIGH.value, reasons or ["Current direct evidence is available."])
        if direct and not blocking:
            return ConfidenceResult(ConfidenceLevel.MEDIUM.value if not stale else ConfidenceLevel.LOW.value, reasons or ["Direct evidence is available with some limitations."])
        if memory:
            return ConfidenceResult(ConfidenceLevel.LOW.value, reasons or ["Answer is based on historical memory only."])
        return ConfidenceResult(ConfidenceLevel.LOW.value, reasons or ["Evidence is limited."])


def tool_usage_items(tool_results: list[ToolExecutionResult]) -> list[ToolUsageItem]:
    return [
        ToolUsageItem(
            tool_name=result.tool_name,
            domain=_domain_for_tool(result),
            status=result.status.value,
            duration_ms=result.runtime_ms,
            evidence_count=len(result.evidence),
            missing_data_count=len(result.missing_data),
        )
        for result in tool_results
    ]


def _evidence_item(raw: Any, *, result: ToolExecutionResult, domain: str, index: int) -> EvidenceItem:
    data = raw if isinstance(raw, dict) else {}
    source_table = str(data.get("source_table") or data.get("source_type") or result.tool_name)
    source_id = str(data.get("source_id") or data.get("id") or index + 1)
    evidence_id = str(data.get("evidence_id") or f"{source_table}:{source_id}")
    memory_chunk = _memory_chunk(result.data, evidence_id, index)
    product = _find_product(result.data)
    event_time = data.get("event_time") or data.get("created_at") or data.get("captured_at") or (memory_chunk or {}).get("event_time")
    snippet = data.get("snippet") or data.get("summary") or (memory_chunk or {}).get("snippet") or (memory_chunk or {}).get("chunk_text")
    title = str(data.get("title") or (memory_chunk or {}).get("source_type") or source_table)
    return EvidenceItem(
        evidence_id=evidence_id,
        domain=domain,
        source_type=str(data.get("source_type") or source_table),
        source_table=source_table,
        source_id=source_id,
        product_id=_string_or_none(data.get("product_id") or (memory_chunk or {}).get("product_id") or product.get("id")),
        product_name=_string_or_none(data.get("product_name") or product.get("title") or product.get("name")),
        title=title,
        summary=str(data.get("summary") or title),
        snippet=str(snippet)[:500] if snippet else None,
        event_time=_iso_or_none(event_time),
        freshness=_freshness_status(_parse_datetime(event_time), result=result).value,
        confidence=_confidence_from_result(result),
        url=_string_or_none(data.get("url")),
        path=_string_or_none(data.get("path")),
    )


def _missing_item(raw: Any, *, domain: str, tool_name: str) -> MissingDataItem:
    if isinstance(raw, dict):
        key = str(raw.get("key") or _missing_key(str(raw.get("message") or raw)))
        template = _MISSING_TEMPLATES.get(key, {})
        return MissingDataItem(
            key=key,
            domain=str(raw.get("domain") or template.get("domain") or domain),
            source_table=raw.get("source_table") or template.get("source_table"),
            message=str(raw.get("message") or template.get("message") or "Required data is missing."),
            blocking=bool(raw.get("blocking", template.get("blocking", False))),
            next_action=str(raw.get("next_action") or template.get("next_action") or "Review source setup."),
            setup_href=raw.get("setup_href") or template.get("setup_href"),
            required_for=list(raw.get("required_for") or template.get("required_for") or [tool_name]),
            severity=str(raw.get("severity") or template.get("severity") or "MEDIUM"),
        )
    text = str(raw)
    key = _missing_key(text)
    template = _MISSING_TEMPLATES.get(key, {})
    return MissingDataItem(
        key=key,
        domain=str(template.get("domain") or domain),
        source_table=template.get("source_table"),
        message=str(template.get("message") or text),
        blocking=bool(template.get("blocking", False)),
        next_action=str(template.get("next_action") or "Review source setup."),
        setup_href=template.get("setup_href"),
        required_for=list(template.get("required_for") or [tool_name]),
        severity=str(template.get("severity") or "MEDIUM"),
    )


_MISSING_TEMPLATES: dict[str, dict[str, Any]] = {
    "MISSING_PRODUCT_COST": {
        "domain": "PROFIT_MARGIN",
        "source_table": "products",
        "message": "Product cost is missing, so profit and margin cannot be calculated.",
        "blocking": True,
        "next_action": "Add product landed cost.",
        "setup_href": "/dashboard/products",
        "required_for": ["profit", "margin", "capital recovery"],
        "severity": "HIGH",
    },
    "MISSING_MARKETPLACE_FEE_POLICY": {
        "domain": "PRICING",
        "source_table": "marketplace_fee_policies",
        "message": "Marketplace fee policy is missing, so discount and profit estimates cannot be calculated safely.",
        "blocking": True,
        "next_action": "Set up marketplace fees.",
        "setup_href": "/dashboard/pricing",
        "required_for": ["profit", "discount simulation", "recovery estimate"],
        "severity": "HIGH",
    },
    "MISSING_SALES_HISTORY": {
        "domain": "SALES_REVENUE",
        "source_table": "sales_records",
        "message": "Sales history has not been imported or is incomplete.",
        "blocking": False,
        "next_action": "Import completed and fulfilled sales records.",
        "setup_href": "/dashboard/imports",
        "required_for": ["sales trend", "last sale", "revenue diagnosis"],
        "severity": "MEDIUM",
    },
    "VISIBILITY_DATA_UNAVAILABLE": {
        "domain": "SEO_VISIBILITY",
        "source_table": "product_visibility_metrics",
        "message": "Visibility data is unavailable, so SEO diagnosis cannot be evaluated.",
        "blocking": False,
        "next_action": "Add or import visibility metrics.",
        "setup_href": "/dashboard/products",
        "required_for": ["SEO diagnosis", "low visibility detection"],
        "severity": "MEDIUM",
    },
}


def _missing_key(text: str) -> str:
    normalized = text.casefold()
    if "cost" in normalized or "landed cost" in normalized:
        return "MISSING_PRODUCT_COST"
    if "fee" in normalized:
        return "MISSING_MARKETPLACE_FEE_POLICY"
    if "sales" in normalized or "sale history" in normalized:
        return "MISSING_SALES_HISTORY"
    if "visibility" in normalized or "seo" in normalized:
        return "VISIBILITY_DATA_UNAVAILABLE"
    if "no data" in normalized or "not found" in normalized:
        return "SOURCE_DATA_MISSING"
    return "MISSING_CONTEXT"


def _source_tables(result: ToolExecutionResult) -> list[str]:
    tables = []
    for item in result.evidence:
        if isinstance(item, dict) and item.get("source_table"):
            tables.append(str(item["source_table"]))
    return list(dict.fromkeys(tables))


def _source_table_for_freshness(result: ToolExecutionResult) -> str | None:
    tables = _source_tables(result)
    return tables[0] if len(tables) == 1 else None


def _latest_datetime(value: Any) -> datetime | None:
    values = _collect_datetimes(value)
    return max(values) if values else None


def _collect_datetimes(value: Any) -> list[datetime]:
    found: list[datetime] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"event_time", "created_at", "updated_at", "captured_at", "calculated_at", "generated_at", "sold_at", "latest_available_at"}:
                parsed = _parse_datetime(item)
                if parsed:
                    found.append(parsed)
            else:
                found.extend(_collect_datetimes(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_datetimes(item))
    return found


def _freshness_status(latest: datetime | None, *, result: ToolExecutionResult | None = None) -> FreshnessStatus:
    if result is not None and result.status != ToolExecutionStatus.SUCCEEDED:
        return FreshnessStatus.UNKNOWN
    if latest is None:
        return FreshnessStatus.MISSING if result is not None and not result.evidence else FreshnessStatus.UNKNOWN
    now = datetime.now(timezone.utc)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return FreshnessStatus.STALE if (now - latest).days > 90 else FreshnessStatus.FRESH


def _freshness_message(status: FreshnessStatus, *, tool_name: str, latest: datetime | None) -> str:
    if status == FreshnessStatus.FRESH:
        return f"{tool_name} has recent source data."
    if status == FreshnessStatus.STALE:
        return f"{tool_name} source data is stale; latest record is {latest.isoformat() if latest else 'unknown'}."
    if status == FreshnessStatus.MISSING:
        return f"{tool_name} did not return freshness evidence."
    return f"{tool_name} freshness is unknown."


def _memory_chunk(data: dict[str, Any], evidence_id: str, index: int) -> dict[str, Any] | None:
    chunks = data.get("memory_chunks")
    if not isinstance(chunks, list):
        return None
    for chunk in chunks:
        if isinstance(chunk, dict) and chunk.get("evidence_id") == evidence_id:
            return chunk
    if 0 <= index < len(chunks) and isinstance(chunks[index], dict):
        return chunks[index]
    return None


def _find_product(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        product = value.get("product") or value.get("affected_product")
        if isinstance(product, dict):
            return product
        for item in value.values():
            found = _find_product(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_product(item)
            if found:
                return found
    return {}


def _domain_for_tool(result: ToolExecutionResult) -> str:
    name = result.tool_name
    if "revenue" in name or "sales" in name:
        return "SALES_REVENUE"
    if "profit" in name or "margin" in name or "fee" in name:
        return "PROFIT_MARGIN"
    if "pricing" in name or "price" in name or "discount" in name:
        return "PRICING"
    if "competitor" in name or "market" in name:
        return "COMPETITOR"
    if "inventory" in name or "stock" in name or "restock" in name or "reorder" in name:
        return "INVENTORY"
    if "memory" in name or "rag" in name:
        return "RAG_MEMORY"
    if "visibility" in name or "seo" in name or "listing" in name:
        return "SEO_VISIBILITY"
    if "promotion" in name:
        return "PROMOTION"
    if "dead_stock" in name or "capital_recovery" in name:
        return "DEAD_STOCK"
    if "alert" in name:
        return "ALERTS"
    if "product" in name or name in {"count_products", "list_products", "search_products"}:
        return "PRODUCT_CATALOG"
    return "GENERAL_BUSINESS"


def _confidence_from_result(result: ToolExecutionResult) -> str:
    if result.status != ToolExecutionStatus.SUCCEEDED:
        return ConfidenceLevel.NO_CONTEXT.value
    value = _find_value(result.data, "confidence") or _find_value(result.data, "retrieval_confidence")
    text = str(value or "").upper()
    if text in {item.value for item in ConfidenceLevel}:
        return text
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ConfidenceLevel.MEDIUM.value if result.evidence else ConfidenceLevel.LOW.value
    if numeric > 1:
        numeric = numeric / 100
    if numeric >= 0.75:
        return ConfidenceLevel.HIGH.value
    if numeric >= 0.45:
        return ConfidenceLevel.MEDIUM.value
    return ConfidenceLevel.LOW.value


def _find_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _find_value(item, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_value(item, key)
            if found is not None:
                return found
    return None


def _dedupe_missing(items: list[MissingDataItem]) -> list[MissingDataItem]:
    output: dict[tuple[str, str], MissingDataItem] = {}
    for item in items:
        key = (item.key, item.domain)
        existing = output.get(key)
        if existing is None or (item.blocking and not existing.blocking):
            output[key] = item
    return list(output.values())


def _dedupe_freshness(items: list[DataFreshnessItem]) -> list[DataFreshnessItem]:
    output: dict[tuple[str, str | None], DataFreshnessItem] = {}
    rank = {"FRESH": 0, "UNKNOWN": 1, "MISSING": 2, "STALE": 3}
    for item in items:
        key = (item.domain, item.source_table)
        existing = output.get(key)
        if existing is None or rank[item.status] > rank[existing.status]:
            output[key] = item
    return list(output.values())


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso_or_none(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.isoformat()
    return str(value) if value else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "", [], {}) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isoformat") and value.__class__.__name__ == "date":
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    return value
