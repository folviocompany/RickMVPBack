import asyncio
import base64

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core.config import Settings
from app.services.pdf import InvalidPdfError, render_pdf_for_ocr


class NvidiaOcrService:
    def __init__(self, settings: Settings):
        if settings.nvidia_api_key is None:
            raise RuntimeError("NVIDIA_API_KEY não configurada para OCR")
        self.url = settings.nvidia_ocr_url
        self.api_key = settings.nvidia_api_key.get_secret_value()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        reraise=True,
    )
    async def _extract_image(self, client: httpx.AsyncClient, image: bytes) -> str:
        response = await client.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            json={
                "input": [
                    {
                        "type": "image_url",
                        "url": ("data:image/jpeg;base64," + base64.b64encode(image).decode()),
                    }
                ],
                "merge_levels": ["paragraph"],
            },
        )
        response.raise_for_status()
        payload = response.json()
        detections = payload.get("data", [{}])[0].get("text_detections", [])
        lines = [
            detection.get("text_prediction", {}).get("text", "").strip() for detection in detections
        ]
        return "\n".join(line for line in lines if line)

    async def extract_pdf(self, content: bytes) -> str:
        images = await asyncio.to_thread(render_pdf_for_ocr, content)
        detail_pages = []
        overview_pages = []
        async with httpx.AsyncClient(timeout=90) as client:
            for label, image in images:
                text = await self._extract_image(client, image)
                if text:
                    page_text = f"--- {label} (OCR) ---\n{text}"
                    if "VISÃO GERAL" in label:
                        overview_pages.append(page_text)
                    else:
                        detail_pages.append(page_text)
        if not detail_pages and not overview_pages:
            raise InvalidPdfError("O OCR não reconheceu texto no documento")
        sections = ["\n\n".join(detail_pages or overview_pages)]
        if detail_pages and overview_pages:
            sections.append(
                "--- OCR SUPLEMENTAR DE PÁGINAS COMPLETAS ---\n" + "\n\n".join(overview_pages)
            )
        return "\n\n".join(sections)
