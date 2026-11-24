import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.orders import ItemPedidoUpdate, PedidoUpdate


def test_normalizes_cnpj_on_order_update():
    payload = PedidoUpdate(cnpj_cliente="12.345.678/0001-90")
    assert payload.cnpj_cliente == "12345678000190"


def test_rejects_invalid_cnpj_on_order_update():
    with pytest.raises(ValidationError, match="14 dígitos"):
        PedidoUpdate(cnpj_cliente="123")


def test_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        ItemPedidoUpdate(id=uuid.uuid4(), quantidade=0)


def test_rejects_null_quantity_when_explicitly_provided():
    with pytest.raises(ValidationError, match="não pode ser vazia"):
        ItemPedidoUpdate.model_validate({"id": str(uuid.uuid4()), "quantidade": None})


def test_rejects_value_larger_than_database_column():
    with pytest.raises(ValidationError):
        ItemPedidoUpdate(id=uuid.uuid4(), valor_total=Decimal("10000000000000"))
