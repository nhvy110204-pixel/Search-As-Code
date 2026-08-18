import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import uuid

# Ensure backend root is in Python module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock external packages if running on host environment outside container
for mod_name in [
    "qdrant_client",
    "qdrant_client.models",
    "qdrant_client.http.models",
    "pypdf",
    "docling",
    "docling.document_converter",
    "docling.datamodel.base_models",
    "docling.datamodel.pipeline_options",
    "torch",
    "redis"
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from app.rag.ingestion.handlers.parse_handler import (
    PdfProfile,
    BATCH_SIZE_BY_PROFILE,
    _detect_pdf_profile,
    _get_converter_for_profile,
    _free_memory,
    _fallback_pdf_extraction,
    _run_docling_conversion_batch,
)
ph_module = sys.modules["app.rag.ingestion.handlers.parse_handler"]

if getattr(ph_module, "pypdf", None) is None:
    ph_module.pypdf = MagicMock()


class TestParseHandlerPdfProfiling(unittest.TestCase):
    """Test suite for Smart Profile Classifier and Ingestion Handlers in parse_handler.py."""

    def test_pdf_profiles_and_batch_sizes(self):
        """Verify profile constants and adaptive batch sizes."""
        self.assertEqual(PdfProfile.DIGITAL_BOOK, "DIGITAL_BOOK")
        self.assertEqual(PdfProfile.SLIDE_VISUAL, "SLIDE_VISUAL")
        self.assertEqual(PdfProfile.SCANNED, "SCANNED")

        self.assertEqual(BATCH_SIZE_BY_PROFILE[PdfProfile.DIGITAL_BOOK], 40)
        self.assertEqual(BATCH_SIZE_BY_PROFILE[PdfProfile.SLIDE_VISUAL], 15)
        self.assertEqual(BATCH_SIZE_BY_PROFILE[PdfProfile.SCANNED], 15)

    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_detect_slide_visual_by_landscape_aspect_ratio(self, mock_pdf_reader_cls):
        """Landscape slides (16:9 or 4:3) must be classified as SLIDE_VISUAL."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader

        # Create mock 16:9 landscape page (width=1920, height=1080 -> ratio 1.77 >= 1.15)
        mock_page = MagicMock()
        mock_mbox = MagicMock()
        mock_mbox.width = 1920
        mock_mbox.height = 1080
        mock_page.mediabox = mock_mbox
        mock_page.extract_text.return_value = "System Architecture Overview Title"
        mock_page.images = [MagicMock()] # 1 diagram image

        mock_reader.pages = [mock_page] * 5

        profile = _detect_pdf_profile("mock_path.pdf", "sample_document.pdf")
        self.assertEqual(profile, PdfProfile.SLIDE_VISUAL)

    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_detect_digital_book_by_portrait_text_density(self, mock_pdf_reader_cls):
        """Portrait standard book with rich text must be classified as DIGITAL_BOOK."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader

        # Create mock Portrait A4 page (width=595, height=842 -> ratio 0.7 < 1.15)
        mock_page = MagicMock()
        mock_mbox = MagicMock()
        mock_mbox.width = 595
        mock_mbox.height = 842
        mock_page.mediabox = mock_mbox
        mock_page.extract_text.return_value = "This is a full paragraph of deep text content. " * 30
        mock_page.images = []

        mock_reader.pages = [mock_page] * 10

        profile = _detect_pdf_profile("mock_path.pdf", "deep_learning_handbook.pdf")
        self.assertEqual(profile, PdfProfile.DIGITAL_BOOK)

    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_detect_scanned_pdf(self, mock_pdf_reader_cls):
        """Scanned document with 0 selectable text must be classified as SCANNED."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader

        mock_page = MagicMock()
        mock_mbox = MagicMock()
        mock_mbox.width = 595
        mock_mbox.height = 842
        mock_page.mediabox = mock_mbox
        mock_page.extract_text.return_value = "" # No text layer
        mock_page.images = [MagicMock()]

        mock_reader.pages = [mock_page] * 3

        profile = _detect_pdf_profile("mock_path.pdf", "scanned_receipt.pdf")
        self.assertEqual(profile, PdfProfile.SCANNED)

    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_detect_slide_by_filename_heuristic(self, mock_pdf_reader_cls):
        """Filename matching slide keywords with visual images must trigger SLIDE_VISUAL."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader

        mock_page = MagicMock()
        mock_mbox = MagicMock()
        mock_mbox.width = 600
        mock_mbox.height = 600
        mock_page.mediabox = mock_mbox
        mock_page.extract_text.return_value = "Topic 1 Overview"
        mock_page.images = [MagicMock()]

        mock_reader.pages = [mock_page] * 4

        profile = _detect_pdf_profile("mock_path.pdf", "[Slide_v2]-Operate-LLM-Applications.pdf")
        self.assertEqual(profile, PdfProfile.SLIDE_VISUAL)

    def test_free_memory_execution(self):
        """Verify _free_memory runs without raising exceptions."""
        try:
            _free_memory()
        except Exception as e:
            self.fail(f"_free_memory raised unexpected exception: {e}")

    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_fallback_pdf_extraction(self, mock_pdf_reader_cls):
        """Verify pypdf fallback extraction correctly builds markdown per page."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader

        mock_page_1 = MagicMock()
        mock_page_1.extract_text.return_value = "Content of slide 1"
        mock_page_2 = MagicMock()
        mock_page_2.extract_text.return_value = "Content of slide 2"

        mock_reader.pages = [mock_page_1, mock_page_2]

        result = _fallback_pdf_extraction("mock_path.pdf", start_page=1, end_page=2)
        self.assertIn("## Page 1\n\nContent of slide 1", result)
        self.assertIn("## Page 2\n\nContent of slide 2", result)

    @patch("app.rag.ingestion.handlers.parse_handler._get_converter_for_profile")
    @patch("app.rag.ingestion.handlers.parse_handler.pypdf.PdfReader")
    def test_run_docling_conversion_batch_incremental_progress(self, mock_pdf_reader_cls, mock_get_converter):
        """Verify batching triggers incremental progress updates to DB."""
        mock_reader = MagicMock()
        mock_pdf_reader_cls.return_value = mock_reader
        # 30 pages with batch_size 15 for SLIDE_VISUAL -> 2 batches
        mock_reader.pages = [MagicMock()] * 30

        mock_converter = MagicMock()
        mock_res = MagicMock()
        mock_res.export_to_markdown.return_value = "# Slide Batch Content"
        mock_converter.convert.return_value = mock_res
        mock_get_converter.return_value = mock_converter

        mock_uow = MagicMock()
        task_id = uuid.uuid4()

        result = _run_docling_conversion_batch(
            "mock_path.pdf",
            profile=PdfProfile.SLIDE_VISUAL,
            uow=mock_uow,
            task_id=task_id
        )

        self.assertIn("# Slide Batch Content", result)
        # Verify uow.ingestion_tasks.update_task_progress was called for both batches
        self.assertEqual(mock_uow.ingestion_tasks.update_task_progress.call_count, 2)
        mock_uow.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
