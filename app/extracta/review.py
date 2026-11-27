import copy
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.extracta.models import DocumentResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemCorrection(StrictModel):
    line_id: str
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    product_code_raw: str | None = Field(default=None, max_length=100)
    packaging_raw: str | None = Field(default=None, max_length=200)
    barcode_raw: str | None = Field(default=None, max_length=100)
    delivery_date_raw: str | None = Field(default=None, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0, le=1_000_000_000, decimal_places=4)
    unit_price: Decimal | None = Field(
        default=None, ge=0, le=Decimal("9999999999999.99"), decimal_places=2
    )
    ipi_raw: str | None = Field(default=None, max_length=100)
    icms_substitution_raw: str | None = Field(default=None, max_length=100)
    tax_base_raw: str | None = Field(default=None, max_length=100)
    commercial_discount_raw: str | None = Field(default=None, max_length=100)
    additional_discount_raw: str | None = Field(default=None, max_length=100)
    vendor_raw: str | None = Field(default=None, max_length=100)
    freight_raw: str | None = Field(default=None, max_length=100)
    allowance_raw: str | None = Field(default=None, max_length=100)
    other_raw: str | None = Field(default=None, max_length=100)
    weight_kg: Decimal | None = Field(default=None, ge=0, le=1_000_000_000, decimal_places=4)
    cp_raw: str | None = Field(default=None, max_length=100)
    final_price_marker_raw: str | None = Field(default=None, max_length=100)


class OrderCorrection(StrictModel):
    order_index: int = Field(ge=0)
    order_number: str | None = Field(default=None, max_length=100)
    edi_order_number: str | None = Field(default=None, max_length=100)
    issuer: str | None = Field(default=None, max_length=300)
    supplier: str | None = Field(default=None, max_length=300)
    issue_date_raw: str | None = Field(default=None, max_length=50)
    payment_days: int | None = Field(default=None, ge=0, le=3650)
    freight_type: str | None = Field(default=None, max_length=50)
    delivery_location: str | None = Field(default=None, max_length=1000)
    product_total: Decimal | None = Field(
        default=None, ge=0, le=Decimal("9999999999999.99"), decimal_places=2
    )
    order_total: Decimal | None = Field(
        default=None, ge=0, le=Decimal("9999999999999.99"), decimal_places=2
    )
    items: list[ItemCorrection] = Field(default_factory=list, max_length=1000)


class DocumentCorrection(StrictModel):
    revision: int = Field(ge=0)
    reviewer: str = Field(min_length=2, max_length=100)
    note: str = Field(default="", max_length=2000)
    orders: list[OrderCorrection] = Field(min_length=1, max_length=100)


class Approval(StrictModel):
    revision: int = Field(ge=0)
    reviewer: str = Field(min_length=2, max_length=100)
    acknowledge_issues: bool = False
    note: str = Field(default="", max_length=2000)


def find_document(report: dict, doc_id: str) -> dict:
    doc = next((item for item in report["documents"] if item["id"] == doc_id), None)
    if doc is None:
        raise HTTPException(404, "Documento não encontrado neste lote")
    return doc


def check_revision(report: dict, document: dict, revision: int) -> None:
    if report["status"] != "completed":
        raise HTTPException(409, "Aguarde o lote terminar antes de conferir")
    if not document.get("result") or document["status"] in {"failed", "interrupted"}:
        raise HTTPException(422, "Documento sem resultado disponível para conferência")
    if document.get("revision", 0) != revision:
        raise HTTPException(409, "O documento mudou. Atualize a tela antes de salvar")


def recalculate(result: dict) -> None:
    for order in result["orders"]:
        items = order["items"]
        if items and all(
            i.get("quantity") is not None and i.get("unit_price") is not None for i in items
        ):
            total = sum(
                (Decimal(str(i["quantity"])) * Decimal(str(i["unit_price"]))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                for i in items
            )
            order["calculated_product_total"] = str(total)
        else:
            order["calculated_product_total"] = None
        order["reconciliation_difference"] = (
            str(Decimal(str(order["order_total"])) - Decimal(str(order["product_total"])))
            if order.get("order_total") is not None and order.get("product_total") is not None
            else None
        )


def issues(result: dict) -> tuple[list[str], list[str]]:
    blockers, warnings = [], list(result.get("warnings", []))
    if not result.get("orders"):
        blockers.append("Nenhum pedido extraído")
    if not result.get("profile_id"):
        blockers.append("Perfil documental não identificado")
    for index, order in enumerate(result.get("orders", []), 1):
        prefix = f"Pedido {index}"
        if not order.get("order_number") or not order.get("items"):
            blockers.append(f"{prefix}: número ou mercadorias ausentes")
        for field, label in (
            ("supplier", "fornecedor"),
            ("issuer", "empresa emissora"),
            ("delivery_location", "local de entrega"),
            ("payment_days", "prazo de pagamento"),
        ):
            if order.get(field) is None or order.get(field) == "":
                warnings.append(f"{prefix}: {label} não identificado")
        calculated = order.get("calculated_product_total")
        products = order.get("product_total")
        if products is None or calculated is None:
            warnings.append(f"{prefix}: total dos produtos não reconciliado")
        elif abs(Decimal(str(calculated)) - Decimal(str(products))) > Decimal("0.05"):
            warnings.append(f"{prefix}: soma dos itens diverge do total Produtos")
        if order.get("order_total") is None:
            warnings.append(f"{prefix}: total declarado do pedido ausente")
        if order.get("reconciliation_difference") is not None and Decimal(
            str(order["reconciliation_difference"])
        ):
            warnings.append(
                f"{prefix}: diferença entre Pedido e Produtos de "
                f"{order['reconciliation_difference']}; conferir tributos/ajustes"
            )
        warnings.extend(
            w for w in order.get("warnings", []) if "conflito" in w or "não interpretada" in w
        )
        for item in order.get("items", []):
            if (
                item.get("quantity") is None
                or Decimal(str(item["quantity"])) <= 0
                or item.get("unit_price") is None
                or Decimal(str(item["unit_price"])) < 0
                or not item.get("description", "").strip()
            ):
                blockers.append(
                    f"{prefix}, linha {item['line_id']}: descrição, quantidade "
                    "ou preço inválido/ausente"
                )
            if not item.get("product_code_raw"):
                warnings.append(f"{prefix}, linha {item['line_id']}: código original ausente")
            warnings.extend(
                f"{prefix}, linha {item['line_id']}: {w}" for w in item.get("warnings", [])
            )
    return list(dict.fromkeys(blockers)), list(dict.fromkeys(warnings))


def audit(document: dict, action: str, reviewer: str, note: str, changes=None):
    if not reviewer.strip():
        raise HTTPException(422, "Informe quem realizou a conferência")
    document["revision"] = document.get("revision", 0) + 1
    document.setdefault("audit", []).append(
        {
            "action": action,
            "reviewer": reviewer.strip(),
            "note": note.strip(),
            "at": datetime.now(UTC).isoformat(),
            "revision": document["revision"],
            "changes": changes or [],
        }
    )


def correct(report: dict, doc_id: str, payload: DocumentCorrection) -> None:
    doc = find_document(report, doc_id)
    check_revision(report, doc, payload.revision)
    result = copy.deepcopy(doc["result"])
    changes = []
    seen_orders = set()
    for correction in payload.orders:
        index = correction.order_index
        if index >= len(result["orders"]) or index in seen_orders:
            raise HTTPException(422, "Pedido inválido ou repetido na correção")
        seen_orders.add(index)
        order = result["orders"][index]
        assignments = [
            (
                order,
                f"orders.{index}",
                correction.model_dump(
                    mode="json", exclude_unset=True, exclude={"order_index", "items"}
                ),
            )
        ]
        by_id = {item["line_id"]: item for item in order["items"]}
        seen_lines = set()
        for item in correction.items:
            if item.line_id not in by_id or item.line_id in seen_lines:
                raise HTTPException(422, "Linha inválida ou repetida na correção")
            seen_lines.add(item.line_id)
            assignments.append(
                (
                    by_id[item.line_id],
                    f"orders.{index}.items.{item.line_id}",
                    item.model_dump(mode="json", exclude_unset=True, exclude={"line_id"}),
                )
            )
        for entity, prefix, values in assignments:
            for field, value in values.items():
                if isinstance(value, str):
                    value = value.strip() or None
                old = entity.get(field)
                if old != value:
                    changes.append({"field": f"{prefix}.{field}", "before": old, "after": value})
                    entity[field] = value
    if not changes:
        return
    try:
        DocumentResult.model_validate(result)
    except ValueError as exc:
        raise HTTPException(422, "Correção contém campos inválidos") from exc
    doc.setdefault("extraction_result", copy.deepcopy(doc["result"]))
    recalculate(result)
    result["status"] = doc["status"] = "needs_review"
    doc["result"] = result
    doc.pop("approval", None)
    audit(doc, "corrected", payload.reviewer, payload.note, changes)


def approve(report: dict, doc_id: str, payload: Approval) -> None:
    doc = find_document(report, doc_id)
    check_revision(report, doc, payload.revision)
    result = doc["result"]
    recalculate(result)
    blockers, warnings = issues(result)
    if blockers:
        raise HTTPException(422, "; ".join(blockers))
    if warnings and (not payload.acknowledge_issues or not payload.note.strip()):
        raise HTTPException(422, "Confirme as pendências e registre uma justificativa")
    doc.setdefault("extraction_result", copy.deepcopy(result))
    audit(doc, "approved", payload.reviewer, payload.note)
    doc["approval"] = {**doc["audit"][-1], "acknowledged_issues": warnings}
    doc["status"] = result["status"] = "validated"


def with_review(report: dict) -> dict:
    report = copy.deepcopy(report)
    for doc in report["documents"]:
        if doc.get("result"):
            blockers, warnings = issues(doc["result"])
            doc["review_blockers"], doc["review_issues"] = blockers, warnings
    return report
