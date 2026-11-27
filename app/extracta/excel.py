"""Exportação provisória do contrato Extracta, sem template Salesforce validado."""

import json
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.extracta.models import DocumentResult
from app.extracta.review import issues


def generate_batch_excel(report: dict, documents: list[dict]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    orders = book.create_sheet("Pedidos")
    orders.append(
        [
            "Lote ID",
            "Documento ID",
            "Arquivo",
            "Pedido índice",
            "Número",
            "Pedido EDI",
            "Perfil",
            "Versão perfil",
            "Emissor",
            "Fornecedor",
            "Emissão original",
            "Pagamento dias",
            "Frete",
            "Local entrega",
            "Total Produtos",
            "Soma calculada",
            "Total Pedido declarado",
            "Diferença Pedido e Produtos",
            "Conferente",
            "Justificativa",
            "Escopo",
        ]
    )
    items = book.create_sheet("Itens")
    items.append(
        [
            "Documento ID",
            "Pedido índice",
            "Número pedido",
            "Linha ID",
            "Página",
            "Descrição",
            "Código original",
            "Embalagem original",
            "Código adicional original",
            "Entrega original",
            "Quantidade",
            "Preço unitário",
            "Total calculado",
            "IPI original",
            "ICMS substituição original",
            "Base original",
            "Desconto comercial original",
            "Desconto adicional original",
            "Vendor original",
            "Frete original",
            "Verba original",
            "Outros original",
            "Peso kg",
            "CP original",
            "Pr Final original",
        ]
    )
    pending = book.create_sheet("Pendencias")
    pending.append(["Documento ID", "Tipo", "Pendência", "Conferente", "Justificativa"])
    audit = book.create_sheet("Auditoria")
    audit.append(
        [
            "Documento ID",
            "Revisão",
            "Ação",
            "Data UTC",
            "Conferente",
            "Nota",
            "Campo",
            "Valor anterior",
            "Valor corrigido",
        ]
    )
    sources = book.create_sheet("Evidencias")
    sources.append(
        [
            "Documento ID",
            "Campo",
            "Página",
            "Texto original",
            "Caixa normalizada",
            "Estratégia",
            "Confiança mínima palavras OCR",
        ]
    )
    for document in documents:
        result = DocumentResult.model_validate(document["result"])
        approval = document.get("approval", {})
        for index, order in enumerate(result.orders):
            orders.append(
                [
                    report["id"],
                    document["id"],
                    document["filename"],
                    index,
                    order.order_number,
                    order.edi_order_number,
                    result.profile_id,
                    result.profile_version,
                    order.issuer,
                    order.supplier,
                    order.issue_date_raw,
                    order.payment_days,
                    order.freight_type,
                    order.delivery_location,
                    order.product_total,
                    order.calculated_product_total,
                    order.order_total,
                    order.reconciliation_difference,
                    approval.get("reviewer"),
                    approval.get("note"),
                    f"{len(documents)} documento(s) selecionado(s) deste lote",
                ]
            )
            for item in order.items:
                items.append(
                    [
                        document["id"],
                        index,
                        order.order_number,
                        item.line_id,
                        item.page_number,
                        item.description,
                        item.product_code_raw,
                        item.packaging_raw,
                        item.barcode_raw,
                        item.delivery_date_raw,
                        item.quantity,
                        item.unit_price,
                        item.calculated_total,
                        item.ipi_raw,
                        item.icms_substitution_raw,
                        item.tax_base_raw,
                        item.commercial_discount_raw,
                        item.additional_discount_raw,
                        item.vendor_raw,
                        item.freight_raw,
                        item.allowance_raw,
                        item.other_raw,
                        item.weight_kg,
                        item.cp_raw,
                        item.final_price_marker_raw,
                    ]
                )
            for field, evidence in order.evidence.items():
                sources.append(
                    [
                        document["id"],
                        f"orders.{index}.{field}",
                        evidence.page_number,
                        evidence.text,
                        json.dumps(evidence.bbox),
                        evidence.strategy,
                        evidence.ocr_word_confidence_min,
                    ]
                )
            for item in order.items:
                for field, evidence in item.evidence.items():
                    sources.append(
                        [
                            document["id"],
                            f"orders.{index}.items.{item.line_id}.{field}",
                            evidence.page_number,
                            evidence.text,
                            json.dumps(evidence.bbox),
                            evidence.strategy,
                            evidence.ocr_word_confidence_min,
                        ]
                    )
        blockers, warnings = issues(document["result"])
        for kind, messages in (("bloqueio", blockers), ("conferida", warnings)):
            for message in messages:
                pending.append(
                    [document["id"], kind, message, approval.get("reviewer"), approval.get("note")]
                )
        for event in document.get("audit", []):
            for change in event.get("changes") or [{}]:
                audit.append(
                    [
                        document["id"],
                        event["revision"],
                        event["action"],
                        event["at"],
                        event["reviewer"],
                        event["note"],
                        change.get("field"),
                        json.dumps(change.get("before"), ensure_ascii=False),
                        json.dumps(change.get("after"), ensure_ascii=False),
                    ]
                )
    for sheet in book:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="2155CD")
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    # Literal strings, including leading '=', are never executable formulas.
                    cell.data_type = "s"
                    cell.number_format = "@"
                elif isinstance(cell.value, (int, float, Decimal)):
                    cell.number_format = "0.00" if sheet.title == "Pedidos" else "0.####"
        if sheet.title in {"Pedidos", "Itens"}:
            columns = (15, 16, 17, 18) if sheet.title == "Pedidos" else (12, 13)
            for index in columns:
                for row in range(2, sheet.max_row + 1):
                    sheet.cell(row, index).number_format = "#,##0.00"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                55, max(15, max(len(str(cell.value or "")) for cell in column) + 2)
            )
    output = BytesIO()
    book.save(output)
    return output.getvalue()
