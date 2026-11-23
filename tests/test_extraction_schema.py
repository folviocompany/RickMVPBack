from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.llm.nvidia import (
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
