import pytest

from app.services.pdf import InvalidPdfError, extract_pdf_text
from tests.pdf_factory import make_pdf


def test_extracts_and_labels_all_pdf_pages():
    text = extract_pdf_text(make_pdf("PEDIDO 123", "CONTINUACAO DO PEDIDO"))
    assert "--- PÁGINA 1 ---" in text
    assert "--- PÁGINA 2 ---" in text
    assert "PEDIDO 123" in text
    assert "CONTINUACAO DO PEDIDO" in text


def test_rejects_file_without_pdf_signature():
    with pytest.raises(InvalidPdfError, match="assinatura de PDF"):
        extract_pdf_text(b"arquivo que nao e pdf")


def test_reports_scanned_pdf_without_searchable_text():
    with pytest.raises(InvalidPdfError, match="OCR"):
        extract_pdf_text(make_pdf(""))
