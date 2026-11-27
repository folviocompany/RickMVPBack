import os
import shutil
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

from app.core.config import Settings
from app.extracta.models import Line, Word

_ocr_lock = threading.Lock()


def executable(settings: Settings) -> str:
    configured = settings.extracta_tesseract_cmd
    found = shutil.which(configured)
    if found:
        return found
    if configured == "tesseract" and os.name == "nt":
        candidate = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "Tesseract não encontrado. Instale o executável e configure EXTRACTA_TESSERACT_CMD."
    )


def ocr_config(settings: Settings, psm: int) -> str:
    return f"--psm {psm}"


@contextmanager
def configured(settings: Settings):
    previous = os.environ.get("TESSDATA_PREFIX")
    data = settings.extracta_tessdata_dir
    if data is None and Path("data/tessdata/por.traineddata").is_file():
        data = Path("data/tessdata")
    if data is not None:
        os.environ["TESSDATA_PREFIX"] = str(data.resolve())
    try:
        pytesseract.pytesseract.tesseract_cmd = executable(settings)
        yield
    finally:
        if previous is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = previous


def check_ocr(settings: Settings) -> dict:
    try:
        with _ocr_lock, configured(settings):
            available = pytesseract.get_languages(config=ocr_config(settings, 6))
        missing = set(settings.extracta_ocr_lang.split("+")) - set(available)
        if missing:
            raise RuntimeError(
                f"Instale os idiomas OCR: {', '.join(sorted(missing))}. "
                "Configure EXTRACTA_TESSDATA_DIR para a pasta dos arquivos traineddata."
            )
        return {"available": True, "languages": available}
    except (RuntimeError, OSError, pytesseract.TesseractError) as exc:
        return {"available": False, "message": str(exc)}


def read_page(page: pymupdf.Page, number: int, settings: Settings, psm: int) -> list[Line]:
    pix = page.get_pixmap(dpi=settings.extracta_ocr_dpi, colorspace=pymupdf.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    # pytesseract's executable setting is global; keep configuration and execution atomic.
    with _ocr_lock, configured(settings):
        data = pytesseract.image_to_data(
            image,
            lang=settings.extracta_ocr_lang,
            config=ocr_config(settings, psm),
            output_type=pytesseract.Output.DICT,
            timeout=settings.extracta_ocr_timeout_seconds,
        )
    grouped = defaultdict(list)
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        if not text:
            continue
        left, top = data["left"][i], data["top"][i]
        width, height = data["width"][i], data["height"][i]
        word = Word(
            text=text,
            bbox=(
                left / pix.width,
                top / pix.height,
                (left + width) / pix.width,
                (top + height) / pix.height,
            ),
            confidence=float(data["conf"][i]) if float(data["conf"][i]) >= 0 else None,
        )
        grouped[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(word)
    lines = []
    for words in grouped.values():
        words.sort(key=lambda word: word.bbox[0])
        lines.append(
            Line(
                page_number=number,
                text=" ".join(word.text for word in words),
                strategy="ocr",
                bbox=(
                    min(w.bbox[0] for w in words),
                    min(w.bbox[1] for w in words),
                    max(w.bbox[2] for w in words),
                    max(w.bbox[3] for w in words),
                ),
                words=words,
            )
        )
    return sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))


def text_lines(page: pymupdf.Page, number: int) -> list[Line]:
    groups = defaultdict(list)
    for x0, y0, x1, y1, text, block, line, _ in page.get_text("words"):
        groups[(block, line)].append(
            Word(
                text=text,
                bbox=(
                    x0 / page.rect.width,
                    y0 / page.rect.height,
                    x1 / page.rect.width,
                    y1 / page.rect.height,
                ),
            )
        )
    return sorted(
        [
            Line(
                page_number=number,
                text=" ".join(w.text for w in words),
                strategy="text",
                bbox=(
                    min(w.bbox[0] for w in words),
                    min(w.bbox[1] for w in words),
                    max(w.bbox[2] for w in words),
                    max(w.bbox[3] for w in words),
                ),
                words=words,
            )
            for words in groups.values()
        ],
        key=lambda line: line.bbox[1],
    )
