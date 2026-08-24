import os
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import uuid
from datetime import datetime

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

from app.shared.enums import DocumentStatus, IngestionTaskStatus, StepStatus
from app.core.exceptions import ReconciliationError, QuarantineException, ProviderRateLimitError
from app.rag.ingestion.pipeline_state import PipelineState
from app.rag.ingestion.ingestion_pipeline import IngestionPipeline


class TestIngestionStateMachine(unittest.IsolatedAsyncioTestCase):
    """Test suite for 3-tier State Machine and deterministic error routing."""

    def setUp(self):
        self.mock_uow = MagicMock()
        self.mock_uow_factory = MagicMock(return_value=self.mock_uow)
        self.mock_uow.__enter__.return_value = self.mock_uow
        self.pipeline = IngestionPipeline(self.mock_uow_factory)

    async def test_reconciliation_error_routes_to_failed_retryable(self):
        """When Reconciliation Gate raises ReconciliationError, task becomes FAILED_RETRYABLE."""
        task_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_task = MagicMock()
        mock_task.id = task_id
        mock_task.status = IngestionTaskStatus.RUNNING
        mock_task.progress = 95.0

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.pipeline_state = {}

        self.mock_uow.ingestion_tasks.get.return_value = mock_task
        self.mock_uow.documents.get.return_value = mock_doc

        # Mock execute pipeline to simulate Reconciliation failure
        self.pipeline._execute_pipeline = AsyncMock(
            side_effect=ReconciliationError("Missing vectors", report={"failed_chunk_count": 20}, is_retryable=True)
        )

        with self.assertRaises(ReconciliationError):
            await self.pipeline.execute_async(task_id, doc_id, project_id)

        # Document must remain in PROCESSING to allow worker retry
        self.assertEqual(mock_doc.status, DocumentStatus.PROCESSING)
        self.mock_uow.ingestion_tasks.update_task_progress.assert_called_with(
            task_id,
            IngestionTaskStatus.FAILED_RETRYABLE,
            95.0,
            error_message="Missing vectors",
            last_error_step="virus_scan",
            progress_metadata={
                "stage_label": "Lỗi tại bước virus_scan: Missing vectors",
                "current_step": "virus_scan",
            }
        )

    async def test_quarantine_routes_to_quarantined_and_permanent_fail(self):
        """When document is infected or rejected, document becomes QUARANTINED and task FAILED_PERMANENT."""
        task_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_task = MagicMock()
        mock_task.id = task_id
        mock_task.status = IngestionTaskStatus.RUNNING
        mock_task.progress = 10.0

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.pipeline_state = {}

        self.mock_uow.ingestion_tasks.get.return_value = mock_task
        self.mock_uow.documents.get.return_value = mock_doc

        self.pipeline._execute_pipeline = AsyncMock(
            side_effect=QuarantineException("Malware signature EICAR detected", reason="virus_scan_failed")
        )

        with self.assertRaises(QuarantineException):
            await self.pipeline.execute_async(task_id, doc_id, project_id)

        self.assertEqual(mock_doc.status, DocumentStatus.QUARANTINED)
        self.mock_uow.ingestion_tasks.update_task_progress.assert_called_with(
            task_id,
            IngestionTaskStatus.FAILED_PERMANENT,
            10.0,
            error_message="Malware signature EICAR detected",
            last_error_step="virus_scan",
            progress_metadata={
                "stage_label": "Lỗi tại bước virus_scan: Malware signature EICAR detected",
                "current_step": "virus_scan",
            }
        )

    async def test_successful_clean_run_marks_ready_and_completed(self):
        """When pipeline executes cleanly, document becomes READY and task becomes COMPLETED."""
        task_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_task = MagicMock()
        mock_task.id = task_id
        mock_task.status = IngestionTaskStatus.RUNNING
        mock_task.progress = 0.0

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.pipeline_state = {}

        self.mock_uow.ingestion_tasks.get.return_value = mock_task
        self.mock_uow.documents.get.return_value = mock_doc

        self.pipeline._execute_pipeline = AsyncMock(
            return_value={
                "chunk_count": 25,
                "failed_chunk_ids": [],
                "reconciliation_report": {"is_invariant_matched": True}
            }
        )

        result = await self.pipeline.execute_async(task_id, doc_id, project_id)

        self.assertEqual(mock_doc.status, DocumentStatus.READY)
        self.assertEqual(mock_doc.chunk_count, 25)
        self.assertFalse(mock_doc.has_partial_failures)
        self.assertEqual(result["status"], "ready")

    async def test_partial_success_marks_partially_available(self):
        """When pipeline executes with minor failed chunks, document is PARTIALLY_AVAILABLE."""
        task_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()

        mock_task = MagicMock()
        mock_task.id = task_id
        mock_task.status = IngestionTaskStatus.RUNNING

        mock_doc = MagicMock()
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.PROCESSING
        mock_doc.pipeline_state = {}

        self.mock_uow.ingestion_tasks.get.return_value = mock_task
        self.mock_uow.documents.get.return_value = mock_doc

        self.pipeline._execute_pipeline = AsyncMock(
            return_value={
                "chunk_count": 50,
                "failed_chunk_ids": ["c_1"],
                "reconciliation_report": {"is_invariant_matched": False, "failed_ratio": 0.02}
            }
        )

        result = await self.pipeline.execute_async(task_id, doc_id, project_id)

        self.assertEqual(mock_doc.status, DocumentStatus.PARTIALLY_AVAILABLE)
        self.assertTrue(mock_doc.has_partial_failures)
        self.assertEqual(result["status"], "partially_available")


if __name__ == "__main__":
    unittest.main()
