from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Word(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None


class Line(BaseModel):
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]
    strategy: Literal["text", "ocr"]
    words: list[Word] = Field(default_factory=list)


class Evidence(BaseModel):
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]
    strategy: str
    ocr_word_confidence_min: float | None = None
    review_status: str = "unreviewed"


class DocumentItem(BaseModel):
    line_id: str
    page_number: int
    description: str
    product_code_raw: str | None = None
    packaging_raw: str | None = None
    barcode_raw: str | None = None
    delivery_date_raw: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    ipi_raw: str | None = None
    icms_substitution_raw: str | None = None
    tax_base_raw: str | None = None
    commercial_discount_raw: str | None = None
    additional_discount_raw: str | None = None
    vendor_raw: str | None = None
    freight_raw: str | None = None
    allowance_raw: str | None = None
    other_raw: str | None = None
    weight_kg: Decimal | None = None
    cp_raw: str | None = None
    final_price_marker_raw: str | None = None
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @property
    def calculated_total(self) -> Decimal | None:
        if self.quantity is None or self.unit_price is None:
            return None
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class DocumentOrder(BaseModel):
    order_number: str | None = None
    edi_order_number: str | None = None
    issuer: str | None = None
    supplier: str | None = None
    issue_date_raw: str | None = None
    issue_time: str | None = None
    payment_days: int | None = None
    freight_type: str | None = None
    delivery_location: str | None = None
    product_total: Decimal | None = None
    order_total: Decimal | None = None
    calculated_product_total: Decimal | None = None
    total_weight: Decimal | None = None
    reconciliation_difference: Decimal | None = None
    items: list[DocumentItem] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RecoverySuggestion(BaseModel):
    order_index: int = Field(ge=0)
    line_id: str | None = None
    field: Literal["quantity", "unit_price", "ipi_raw", "weight_kg", "cp_raw", "supplier"]
    source_ids: list[str]
    value: str
    normalized_value: str
    quote: str
    page_number: int
    bbox: tuple[float, float, float, float]
    strategy: Literal["llm_candidate"] = "llm_candidate"
    status: Literal["unreviewed"] = "unreviewed"


class DocumentResult(BaseModel):
    source_document_id: str
    filename: str
    sha256: str
    page_count: int = 0
    profile_id: str | None = None
    profile_version: str | None = None
    status: Literal["needs_review", "validated", "failed"] = "needs_review"
    strategy: str = "local"
    orders: list[DocumentOrder] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    ocr_passes: int = 0
    llm_calls: int = 0
    transitions: list[str] = Field(default_factory=list)
    recovery_candidates: list[RecoverySuggestion] = Field(default_factory=list)
    recovery_events: list[str] = Field(default_factory=list)
    llm_usage: dict[str, int] = Field(default_factory=dict)
