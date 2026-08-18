import pytest
import os
import pypdf
from unittest.mock import MagicMock
from uuid import uuid4

from app.rag.ingestion.handlers.parse_handler import (
    _is_scanned_pdf,
    _fallback_pdf_extraction,
    _run_docling_conversion_batch,
    _free_memory,
    parse_handler
)


def create_sample_pdf(file_path: str, num_pages: int = 5):
    writer = pypdf.PdfWriter()
    for i in range(num_pages):
        writer.add_blank_page(width=300, height=300)
    with open(file_path, "wb") as f:
        writer.write(f)


def test_is_scanned_pdf_blank(tmp_path):
    pdf_path = str(tmp_path / "blank.pdf")
    create_sample_pdf(pdf_path, num_pages=3)
    assert _is_scanned_pdf(pdf_path) is True


def test_fallback_pdf_extraction_range(tmp_path):
    pdf_path = str(tmp_path / "sample.pdf")
    create_sample_pdf(pdf_path, num_pages=10)
    res = _fallback_pdf_extraction(pdf_path, start_page=1, end_page=5)
    assert isinstance(res, str)


def test_batch_conversion_pagination_with_task_id(tmp_path):
    pdf_path = str(tmp_path / "multipage.pdf")
    create_sample_pdf(pdf_path, num_pages=6)
    
    mock_uow = MagicMock()
    task_id = uuid4()
    
    res = _run_docling_conversion_batch(
        pdf_path,
        is_scanned=False,
        batch_size=2,
        uow=mock_uow,
        task_id=task_id
    )
    assert isinstance(res, str)
    assert mock_uow.ingestion_tasks.update_task_progress.called


def test_free_memory():
    _free_memory()
