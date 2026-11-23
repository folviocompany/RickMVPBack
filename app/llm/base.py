from typing import Protocol

from app.schemas.extraction import DocumentoExtraido


class ExtractionProvider(Protocol):
    async def extract_orders(self, document_text: str) -> DocumentoExtraido: ...
