import os
import sys
import unittest
from unittest.mock import MagicMock
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

from app.shared.enums import DocumentStatus
from app.core.exceptions import ReconciliationError
from app.rag.ingestion.pipeline_state import PipelineState
from app.rag.ingestion.handlers.finalize_handler import finalize_handler


class TestIngestionReconciliationGate(unittest.IsolatedAsyncioTestCase):
    """Unit test suite for Hard Reconciliation Invariant Gate in finalize_handler.py."""

    async def test_reconciliation_exact_match_marks_ready(self):
        """When 100% chunks match links and zero failed, document becomes READY."""
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.processing_metadata = {}

        mock_uow = MagicMock()
        mock_uow.documents.get.return_value = mock_doc

        pipeline_state = PipelineState()
        pipeline_state.new_chunk_ids = ["chunk_1", "chunk_2", "chunk_3"]
        pipeline_state.expected_chunk_count = 3
        pipeline_state.actual_link_count = 3
        pipeline_state.actual_embedded_count = 3
        pipeline_state.failed_chunk_ids = []

        res = await finalize_handler(mock_uow, doc_id, project_id, pipeline_state)

        self.assertEqual(mock_doc.status, DocumentStatus.READY)
        self.assertFalse(mock_doc.has_partial_failures)
        self.assertTrue(res["reconciliation_report"]["is_invariant_matched"])
        self.assertEqual(res["reconciliation_report"]["failed_ratio"], 0.0)

    async def test_reconciliation_minor_loss_marks_partially_available(self):
        """When 1 out of 100 chunks fails (< 5%), document becomes PARTIALLY_AVAILABLE."""
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.processing_metadata = {}

        mock_uow = MagicMock()
        mock_uow.documents.get.return_value = mock_doc

        pipeline_state = PipelineState()
        pipeline_state.new_chunk_ids = [f"c_{i}" for i in range(100)]
        pipeline_state.expected_chunk_count = 100
        pipeline_state.actual_link_count = 100
        pipeline_state.actual_embedded_count = 99
        pipeline_state.failed_chunk_ids = ["c_99"] # 1% failure < 5%

        res = await finalize_handler(mock_uow, doc_id, project_id, pipeline_state)

        self.assertEqual(mock_doc.status, DocumentStatus.PARTIALLY_AVAILABLE)
        self.assertTrue(mock_doc.has_partial_failures)
        self.assertEqual(res["reconciliation_report"]["failed_chunk_count"], 1)
        self.assertEqual(res["reconciliation_report"]["failed_ratio"], 0.01)

    async def test_reconciliation_high_failure_ratio_raises_error(self):
        """When 20 out of 100 chunks fail (20% >= 5%), Reconciliation Gate raises ReconciliationError."""
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.processing_metadata = {}

        mock_uow = MagicMock()
        mock_uow.documents.get.return_value = mock_doc

        pipeline_state = PipelineState()
        pipeline_state.new_chunk_ids = [f"c_{i}" for i in range(100)]
        pipeline_state.expected_chunk_count = 100
        pipeline_state.actual_link_count = 100
        pipeline_state.actual_embedded_count = 80
        pipeline_state.failed_chunk_ids = [f"c_{i}" for i in range(80, 100)] # 20% failure

        with self.assertRaises(ReconciliationError) as ctx:
            await finalize_handler(mock_uow, doc_id, project_id, pipeline_state)

        self.assertTrue(ctx.exception.is_retryable)
        self.assertEqual(ctx.exception.report["failed_chunk_count"], 20)

    async def test_reconciliation_missing_links_raises_error(self):
        """When link count is severely lower than expected chunks, raises ReconciliationError."""
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.processing_metadata = {}

        mock_uow = MagicMock()
        mock_uow.documents.get.return_value = mock_doc

        pipeline_state = PipelineState()
        pipeline_state.new_chunk_ids = [f"c_{i}" for i in range(50)]
        pipeline_state.expected_chunk_count = 50
        pipeline_state.actual_link_count = 10 # Missing 40 links!
        pipeline_state.actual_embedded_count = 50
        pipeline_state.failed_chunk_ids = []

        with self.assertRaises(ReconciliationError):
            await finalize_handler(mock_uow, doc_id, project_id, pipeline_state)


if __name__ == "__main__":
    unittest.main()
