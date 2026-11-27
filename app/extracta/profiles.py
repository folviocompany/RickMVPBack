"""Registry explícito. Nenhuma regra executável é produzida pela IA."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.extracta.models import DocumentItem, DocumentOrder, Evidence, Line


def normalized(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", text.upper()))


def decimal_br(raw: str) -> Decimal | None:
    raw = raw.strip().rstrip(",")
    if not re.fullmatch(r"\d+(?:\.\d{3})*(?:,\d+)?", raw):
        return None
    try:
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def evidence(line: Line) -> Evidence:
    confidences = [word.confidence for word in line.words if word.confidence is not None]
    return Evidence(
        page_number=line.page_number,
        text=line.text,
        bbox=line.bbox,
        strategy=line.strategy,
        ocr_word_confidence_min=min(confidences) if confidences else None,
    )


@dataclass(frozen=True)
class AtacadaoProfile:
    id: str = "atacadao_purchase_order"
    version: str = "0.1.0"
    anchors: tuple[str, ...] = (
        "PEDIDODECOMPRA",
        "PEDIDOEDI",
        "NUMERO",
        "MERCADORIA",
        "DTENT",
        "QTDE",
        "UNITARIO",
        "TOTAIS",
        "ATACADAOSA",
    )

    def matches(self, lines: list[Line]) -> bool:
        text = normalized(" ".join(line.text for line in lines))
        hits = {anchor for anchor in self.anchors if anchor in text}
        return len(hits) >= 5 and "MERCADORIA" in hits and "PEDIDOEDI" in hits

    def extract(self, lines: list[Line]) -> list[DocumentOrder]:
        orders: dict[tuple, DocumentOrder] = {}
        for page_number in sorted({line.page_number for line in lines}):
            page = [line for line in lines if line.page_number == page_number]
            header = DocumentOrder()
            for index, line in enumerate(page):
                text = line.text
                for field, pattern in (
                    ("order_number", r"Numero\s*[:.]?\s*(\d+)"),
                    ("edi_order_number", r"Pedido\s+EDI[.\s:]*([0-9]+)"),
                    ("issue_date_raw", r"(\d{2}/\d{2}/\d{2,4})"),
                    ("issue_time", r"(\d{2}:\d{2})"),
                    ("freight_type", r"Frete\s*:\s*(CIF|FOB)"),
                ):
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        setattr(header, field, match.group(1))
                        header.evidence[field] = evidence(line)
                if "ATACADAOSA" in normalized(text):
                    header.issuer = "ATACADAO S.A."
                    header.evidence["issuer"] = evidence(line)
                if "CONDICOESDEPAGTO" in normalized(text) and index + 1 < len(page):
                    next_line = page[index + 1]
                    # Payment is below its anchor, inside the same column.
                    anchor = next(
                        (
                            w.bbox[0]
                            for w in line.words
                            if normalized(w.text).startswith("CONDICOES")
                        ),
                        0.37,
                    )
                    candidates = [
                        w
                        for w in next_line.words
                        if anchor - 0.02 <= w.bbox[0] <= anchor + 0.09
                        and re.fullmatch(r"\d{1,3}", w.text)
                    ]
                    if candidates:
                        header.payment_days = int(candidates[0].text)
                        header.evidence["payment_days"] = evidence(next_line)
                if "TOTAIS" in normalized(text):
                    # OCR can split cents from the comma. Keep original evidence unchanged.
                    totals_text = re.sub(r",\s+(\d{2})\b", r",\1", text)
                    for field, pattern in (
                        ("product_total", r"Produtos\s*:\s*([\d.,]+)"),
                        ("order_total", r"Pedido\s*:\s*([\d.,]+)"),
                    ):
                        match = re.search(pattern, totals_text, re.IGNORECASE)
                        if match:
                            setattr(header, field, decimal_br(match.group(1)))
                            header.evidence[field] = evidence(line)
                    match = re.search(r"Pedido\s*:\s*[\d.,]+\s+([\d.,]+)", totals_text, re.I)
                    if match:
                        header.total_weight = decimal_br(match.group(1))
                        header.evidence["total_weight"] = evidence(line)

            key = (header.order_number, header.edi_order_number)
            if key == (None, None):
                key = (None, page_number)
                header.warnings.append(f"Página {page_number}: pedido sem identificação legível")
            order = orders.get(key)
            if order is None:
                orders[key] = order = header
            else:
                for field in (
                    "issuer",
                    "issue_date_raw",
                    "issue_time",
                    "payment_days",
                    "freight_type",
                    "product_total",
                    "order_total",
                    "total_weight",
                ):
                    value = getattr(header, field)
                    previous = getattr(order, field)
                    if value is not None and previous is not None and value != previous:
                        order.warnings.append(f"Página {page_number}: conflito no campo {field}")
                    elif previous is None and value is not None:
                        setattr(order, field, value)
                        order.evidence[field] = header.evidence[field]

            in_table = False
            current = None
            for line in page:
                if "MERCADORIA" in normalized(line.text):
                    in_table = True
                    continue
                if "TOTAIS" in normalized(line.text):
                    in_table = False
                if not in_table:
                    continue
                # A merchandise row must contain a description followed by its date and values.
                match = re.search(
                    r"^\s*[|]?\s*(.+?)\s+(\d{2}/\d{2})\s+(\d+)\s+([\d.,]+)\s+(.*)",
                    line.text,
                )
                if match:
                    description, delivery, quantity, unit_price, tail = match.groups()
                    if not re.search(r"[A-Za-zÀ-ÿ]{2}", description):
                        continue
                    current = DocumentItem(
                        line_id=f"p{page_number}-l{len(order.items) + 1}",
                        page_number=page_number,
                        description=description.strip(),
                        delivery_date_raw=delivery,
                        quantity=Decimal(quantity),
                        unit_price=decimal_br(unit_price),
                    )
                    for field in ("description", "delivery_date_raw", "quantity", "unit_price"):
                        current.evidence[field] = evidence(line)
                    columns = tail.strip().rstrip("|").split()
                    raw_fields = (
                        "ipi_raw",
                        "icms_substitution_raw",
                        "tax_base_raw",
                        "commercial_discount_raw",
                        "additional_discount_raw",
                        "vendor_raw",
                        "freight_raw",
                        "allowance_raw",
                        "other_raw",
                    )
                    if len(columns) == 11:
                        for field, value in zip(raw_fields, columns[:9], strict=True):
                            setattr(current, field, value)
                            current.evidence[field] = evidence(line)
                        current.weight_kg = decimal_br(columns[9])
                        current.cp_raw = columns[10]
                        current.evidence["weight_kg"] = evidence(line)
                        current.evidence["cp_raw"] = evidence(line)
                    else:
                        current.warnings.append("Colunas de tributos/peso ambíguas; conferir linha")
                    order.items.append(current)
                    continue
                if current is not None:
                    code = re.search(r"\b(\d+/\d+)\s+(CXA\s+\S+)", line.text)
                    if code and current.product_code_raw is None:
                        current.product_code_raw = code.group(1)
                        current.packaging_raw = code.group(2)
                        for field in ("product_code_raw", "packaging_raw"):
                            current.evidence[field] = evidence(line)
                        rest = line.text[code.end() :]
                        barcode = re.search(r"\b(\d{8,18})\b", rest)
                        if barcode:
                            current.barcode_raw = barcode.group(1)
                            current.evidence["barcode_raw"] = evidence(line)
                        marker = re.search(r"Pr\s+Final\s+(\w+)", rest, re.I)
                        if marker:
                            current.final_price_marker_raw = marker.group(1)
                            current.evidence["final_price_marker_raw"] = evidence(line)
                    elif re.search(r"\d{2}/\d{2}", line.text):
                        order.warnings.append(
                            f"Página {page_number}: possível mercadoria não interpretada: "
                            f"{line.text}"
                        )
        return list(orders.values())


PROFILES = (AtacadaoProfile(),)


def recognize(lines: list[Line]) -> AtacadaoProfile | None:
    return next((profile for profile in PROFILES if profile.matches(lines)), None)


def validate_orders(orders: list[DocumentOrder]) -> None:
    for order in orders:
        if not order.items:
            order.warnings.append("Nenhuma mercadoria extraída")
        values = [item.calculated_total for item in order.items]
        if values and all(value is not None for value in values):
            order.calculated_product_total = sum(values, Decimal("0"))
        if order.product_total is not None and order.calculated_product_total is not None:
            difference = order.calculated_product_total - order.product_total
            if abs(difference) > Decimal("0.05"):
                order.warnings.append(f"Soma das mercadorias diverge de Produtos em {difference}")
        else:
            order.warnings.append("Não foi possível reconciliar o total dos produtos")
        if order.product_total is not None and order.order_total is not None:
            order.reconciliation_difference = order.order_total - order.product_total
            if order.reconciliation_difference:
                order.warnings.append(
                    f"Pedido difere de Produtos em {order.reconciliation_difference}; "
                    "tributos e ajustes exigem conferência"
                )
        if order.order_number is None or order.edi_order_number is None:
            order.warnings.append("Identificação do pedido incompleta")
        if order.payment_days is None:
            order.warnings.append("Prazo de pagamento ausente")
        if order.issuer is None:
            order.warnings.append("Empresa emissora não identificada")
        if order.supplier is None:
            order.warnings.append("Fornecedor ainda não extraído; conferir documento original")
        if order.delivery_location is None:
            order.warnings.append("Local de entrega não identificado")
        for item in order.items:
            if item.quantity is None or item.quantity <= 0 or item.unit_price is None:
                item.warnings.append("Quantidade ou preço inválido/ausente")
            if item.product_code_raw is None:
                item.warnings.append("Código composto não identificado")
        # Do not claim a business document is approved because its arithmetic closes.
        order.warnings.append("Conferência humana necessária antes da exportação final")
