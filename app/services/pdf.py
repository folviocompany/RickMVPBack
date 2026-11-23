from io import BytesIO

import pymupdf


class InvalidPdfError(ValueError):
    pass


class PdfNeedsOcrError(InvalidPdfError):
    pass


def validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise InvalidPdfError("O arquivo enviado não possui assinatura de PDF")

    try:
        with pymupdf.open(stream=BytesIO(content), filetype="pdf") as document:
            if document.page_count == 0:
                raise InvalidPdfError("O PDF não possui páginas")
    except InvalidPdfError:
        raise
    except Exception as exc:
        raise InvalidPdfError("Não foi possível ler o PDF") from exc


def extract_pdf_text(content: bytes) -> str:
    validate_pdf(content)
    try:
        with pymupdf.open(stream=BytesIO(content), filetype="pdf") as document:
            pages = []
            for number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    pages.append(f"--- PÁGINA {number} ---\n{text}")
    except Exception as exc:
        raise InvalidPdfError("Não foi possível ler o PDF") from exc

    if not pages:
        raise PdfNeedsOcrError("O PDF não contém texto pesquisável; será necessário OCR")
    return "\n\n".join(pages)


def render_pdf_for_ocr(content: bytes) -> list[tuple[str, bytes]]:
    validate_pdf(content)
    images = []
    with pymupdf.open(stream=BytesIO(content), filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            overview = None
            for dpi, quality in ((120, 65), (110, 60), (100, 55), (90, 50)):
                pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
                candidate = pixmap.tobytes("jpeg", jpg_quality=quality)
                base64_size = ((len(candidate) + 2) // 3) * 4
                if base64_size < 180_000:
                    overview = candidate
                    break
            if overview is None:
                raise InvalidPdfError("Não foi possível reduzir a página para o limite do OCR")
            images.append((f"PÁGINA {page_number} - VISÃO GERAL", overview))

            height = page.rect.height
            bands = ((0.0, 0.29), (0.29, 0.665), (0.665, 1.0))
            for band_number, (start, end) in enumerate(bands, start=1):
                clip = pymupdf.Rect(
                    page.rect.x0,
                    page.rect.y0 + height * start,
                    page.rect.x1,
                    page.rect.y0 + height * end,
                )
                encoded = None
                for dpi, quality in ((200, 72), (180, 68), (160, 64), (140, 60), (120, 56)):
                    pixmap = page.get_pixmap(
                        dpi=dpi,
                        colorspace=pymupdf.csGRAY,
                        alpha=False,
                        clip=clip,
                    )
                    candidate = pixmap.tobytes("jpeg", jpg_quality=quality)
                    base64_size = ((len(candidate) + 2) // 3) * 4
                    if base64_size < 180_000:
                        encoded = candidate
                        break
                if encoded is None:
                    raise InvalidPdfError("Não foi possível reduzir a faixa para o limite do OCR")
                label = f"PÁGINA {page_number} - FAIXA {band_number}/3"
                images.append((label, encoded))
    return images
