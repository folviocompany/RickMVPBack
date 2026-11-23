import pymupdf


class MemoryUpload:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        return self._content if size < 0 else self._content[:size]

    async def close(self) -> None:
        return None


def make_pdf(*pages: str) -> bytes:
    document = pymupdf.open()
    try:
        for content in pages:
            page = document.new_page()
            page.insert_text((72, 72), content)
        return document.tobytes()
    finally:
        document.close()
