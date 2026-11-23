from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.llm.nvidia import (
    FACT_FALLBACK_MARKER,
    _code_candidates,
    _extract_unit_price,
    build_bic_item_blocks,
    count_bic_item_candidates,
)
from app.schemas.extraction import ItemExtraido, PedidoExtraido


def test_normalizes_cnpj_and_preserves_product_codes():
    pedido = PedidoExtraido(
        cnpj_cliente="09.477.652/0112-01",
        itens=[{"seq_bic": "109703", "ref_cliente": "0068", "quantidade": 1}],
    )
    assert pedido.cnpj_cliente == "09477652011201"
    assert pedido.itens[0].ref_cliente == "0068"


def test_rejects_invalid_cnpj():
    with pytest.raises(ValidationError):
        PedidoExtraido(cnpj_cliente="123", itens=[{"quantidade": 1}])


def test_marks_inconsistent_total_for_review():
    item = ItemExtraido(quantidade=10, valor_unitario=Decimal("5"), valor_total=Decimal("80"))
    assert "diverge" in item.observacao


def test_normalizes_brazilian_decimal_and_ignores_composite_package():
    item = ItemExtraido(
        quantidade=2,
        embalagem_cx="0040X0012X1UND",
        codigo_produto="00025423/136",
        valor_unitario="1.574,57",
    )

    assert item.embalagem_cx is None
    assert item.codigo_produto == "00025423"
    assert item.valor_unitario == Decimal("1574.57")


def test_ignores_unrealistic_numeric_package():
    item = ItemExtraido(quantidade=1, embalagem_cx="70330717558")
    assert item.embalagem_cx is None


def test_counts_bic_product_lines_without_headers():
    text = """PEDIDO DE COMPRA BIC
Fornecedor: BIC
MERCADORIA
ACENDEDOR BIC HANDY
AP.BARB.BIC FLEX 3 AZUL
TOTAIS BIC
"""

    assert count_bic_item_candidates(text) == 2
    _, blocks = build_bic_item_blocks(text)
    assert blocks == ["ACENDEDOR BIC HANDY", "AP.BARB.BIC FLEX 3 AZUL"]


def test_recovers_decimal_separator_read_as_zero():
    block = "AP.BARB.BIC FLEX 3 L4P3\n28/10\n2\n1008061 Pr Final N"
    assert _extract_unit_price(block) == Decimal("1008.61")


def test_prefers_more_complete_overview_and_ignores_supplier_name():
    text = """--- PÁGINA 1 - FAIXA 1/3 (OCR) ---
BIC AMAZONIA S A
MERCADORIA
ACENDEDOR BIC HANDY
--- PÁGINA 1 - FAIXA 2/3 (OCR) ---
AP.BARB.BIC FLEX 3
--- OCR SUPLEMENTAR DE PÁGINAS COMPLETAS ---
--- PÁGINA 1 - VISÃO GERAL (OCR) ---
BIC AMAZONIA S A
MERCADORIA
ACENDEDOR BIC HANDY
AP.BARB.BIC FLEX 3
AP.BARB. BICFFLEX HYBRID
AP.BARB.BIC SOLEIL
"""

    assert count_bic_item_candidates(text) == 4
    _, blocks = build_bic_item_blocks(text)
    assert len(blocks) == 4
    assert blocks[0].startswith("ACENDEDOR BIC HANDY")
    assert blocks[-1] == "AP.BARB.BIC SOLEIL"


def test_repairs_two_misread_as_leading_zero_in_product_code():
    candidates = _code_candidates("AP.BARB.BIC\n20025423/136", detail_priority=0)
    assert max(candidates)[1] == "00025423"


def test_enriches_overview_with_detailed_facts_when_fields_are_missing():
    text = """--- PÁGINA 1 - FAIXA 1/3 (OCR) ---
MERCADORIA
AP.BARB.BIC FLEX 3 AZUL
28/10
2
672,41
00067817/152
AP.BARB.BIC SOLEIL NATURALS
28/10
3
538,13
00073520/142
--- OCR SUPLEMENTAR DE PÁGINAS COMPLETAS ---
--- PÁGINA 1 - VISÃO GERAL (OCR) ---
MERCADORIA
AP.BARB.BIC FLEX 3 AZUL
28/10
2
672,41
0X0678000152
AP.BARB.BIC SOLEIL NATURALS
28/10
538,13
00073520/142
AP.BARB.BIC ITEM EXTRA
28/10
1
10,00
00000001/100
"""

    _, blocks = build_bic_item_blocks(text)
    assert len(blocks) == 3
    assert FACT_FALLBACK_MARKER in blocks[0]
    assert FACT_FALLBACK_MARKER in blocks[1]
    assert FACT_FALLBACK_MARKER not in blocks[2]


def test_enriches_suspicious_short_code_from_detailed_ocr():
    text = """--- PÁGINA 1 - FAIXA 1/3 (OCR) ---
MERCADORIA
AP.BARB.BIC 3 INTENSITY
28/10
2
1063,39
20051361/144
--- OCR SUPLEMENTAR DE PÁGINAS COMPLETAS ---
--- PÁGINA 1 - VISÃO GERAL (OCR) ---
MERCADORIA
APTBNSB.BIC 3 INTENSITY
28/10
2
1063,39
000 1361/144
AP.BARB.BIC ITEM EXTRA
28/10
1
10,00
00000001/100
"""

    _, blocks = build_bic_item_blocks(text)
    assert FACT_FALLBACK_MARKER in blocks[0]
    combined_codes = _code_candidates(blocks[0], detail_priority=0)
    assert max(combined_codes)[1] == "00051361"
