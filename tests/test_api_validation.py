import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.processing import create_process
from tests.async_runner import run_async
from tests.pdf_factory import MemoryUpload


def test_upload_rejects_non_pdf_before_database_access():
    async def scenario():
        upload = MemoryUpload("pedido.txt", b"nao e pdf")
        with pytest.raises(HTTPException) as error:
            await create_process(BackgroundTasks(), upload, None)  # type: ignore[arg-type]
        return error

    error = run_async(scenario())
    assert error.value.status_code == 422
    assert "assinatura de PDF" in error.value.detail
