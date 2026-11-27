from decimal import Decimal

from app.core.config import Settings
from app.extracta.models import Line
from app.extracta.profiles import AtacadaoProfile, decimal_br, validate_orders
from app.extracta.workflow import analyze_document
from tests.pdf_factory import make_pdf


def line(text, page=1):
    return Line(page_number=page, text=text, bbox=(0, 0, 1, 1), strategy="text")


def test_pt_br_decimal_does_not_confuse_absence_and_zero():
    assert decimal_br("1.574,57") == Decimal("1574.57")
    assert decimal_br("0,00") == 0
    assert decimal_br("") is None
    assert decimal_br("valor 50") is None


def test_preserves_raw_codes_and_repeated_merchandise_across_pages():
    lines = []
    for page in (1, 2):
        lines.extend(
            [
                line("PEDIDO DE COMPRA Pedido EDI: 123 Numero: 42", page),
                line("MERCADORIA Dt.Ent Qtde Unitario", page),
                line(
                    "AP.BIC TESTE 28/10 2 10,00 15,0 0,00 0,00 "
                    "0,0000 0,000 0,00 0,00 0,00 0,00 1,2 S",
                    page,
                ),
                line("00001234/123 CXA 0001X0012X1UND 70330717558 Pr Final N", page),
                line("/ X X Pr Final", page),
            ]
        )
    lines.append(line("TOTAIS Produtos: 40,00 Pedido: 46,00 2,4", 2))
    profile = AtacadaoProfile()
    assert profile.matches(lines)
    orders = profile.extract(lines)
    assert len(orders) == 1
    assert len(orders[0].items) == 2
    assert orders[0].items[1].page_number == 2
    assert orders[0].items[0].product_code_raw == "00001234/123"
    assert orders[0].items[0].barcode_raw == "70330717558"
    assert orders[0].items[0].packaging_raw == "CXA 0001X0012X1UND"
    validate_orders(orders)
    assert orders[0].calculated_product_total == 40
    assert orders[0].order_total == 46
    assert orders[0].reconciliation_difference == 6
    assert any("tributos" in warning for warning in orders[0].warnings)


def test_different_orders_are_not_merged():
    profile = AtacadaoProfile()
    orders = profile.extract(
        [
            line("Pedido EDI: 123 Numero: 42", 1),
            line("Pedido EDI: 456 Numero: 43", 2),
        ]
    )
    assert len(orders) == 2


def test_split_cents_are_rejoined_but_evidence_is_preserved():
    orders = AtacadaoProfile().extract(
        [
            line("Numero: 1 Pedido EDI: 2"),
            line("TOTAIS Produtos: 22.115,82 Pedido: 22.115, 82 124,3"),
        ]
    )
    assert orders[0].order_total == Decimal("22115.82")
    assert orders[0].total_weight == Decimal("124.3")
    assert "22.115, 82" in orders[0].evidence["order_total"].text


def test_invalid_pdf_fails_without_ocr_or_remote_calls():
    result = analyze_document(b"not-pdf", "anything.pdf", Settings())
    assert result.status == "failed"
    assert result.llm_calls == 0


def test_unknown_text_profile_routes_to_review_without_remote_calls():
    content = make_pdf("A document without purchase orders. " * 10)
    result = analyze_document(content, "unknown.pdf", Settings())
    assert result.status == "needs_review"
    assert result.profile_id is None
    assert result.llm_calls == 0


def test_page_limit_is_checked_before_ocr():
    result = analyze_document(
        make_pdf("one", "two"),
        "renamed.pdf",
        Settings(
            extracta_max_pages_per_document=1,
        ),
    )
    assert result.status == "failed"
    assert result.ocr_passes == 0
