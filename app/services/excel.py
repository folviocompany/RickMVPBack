from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.schemas.orders import PedidoResponse

HEADERS = [
    "Cód. Cliente",
    "Cód. Indústria",
    "Descrição",
    "Embalagem (CX)",
    "Quantidade",
    "Valor Unitário",
    "Valor Total",
    "Observação",
    "Status",
]


def generate_order_excel(order: PedidoResponse) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pedido"

    header_fill = PatternFill("solid", fgColor="D9E1F2")
    mapped_fill = PatternFill("solid", fgColor="C6EFCE")
    review_fill = PatternFill("solid", fgColor="FFC7CE")
    total_fill = PatternFill("solid", fgColor="D9D9D9")

    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill

    total_quantity = 0
    total_value = 0
    for item in order.itens:
        sheet.append(
            [
                item.codigo_original,
                item.codigo_industria or "NÃO MAPEADO",
                item.descricao_produto,
                item.embalagem_cx,
                item.quantidade,
                item.valor_unitario,
                item.valor_total,
                item.observacao,
                "OK" if item.mapeado else "Revisar",
            ]
        )
        fill = mapped_fill if item.mapeado else review_fill
        for cell in sheet[sheet.max_row]:
            cell.fill = fill
        total_quantity += item.quantidade
        total_value += item.valor_total or 0

    sheet.append(["TOTAL", None, None, None, total_quantity, None, total_value, None, None])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
        cell.fill = total_fill

    for column in ("F", "G"):
        for cell in sheet[column][1:]:
            cell.number_format = "#,##0.00"
    for cells in sheet.columns:
        width = min(max(len(str(cell.value or "")) for cell in cells) + 2, 60)
        sheet.column_dimensions[cells[0].column_letter].width = width

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
