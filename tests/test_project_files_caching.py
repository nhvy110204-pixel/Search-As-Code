import json
import uuid
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
from pathlib import Path

from app.graph.nodes.finalizer import finalizer_node
from app.graph.state.agent_state import AgentState
from app.shared.enums import StopReason
from app.models.document import Document
from app.services.core.document import DocumentService
from app.schemas.dto.document import DocumentCreate, DocumentUpdate
from app.guardrails.router import check_query_relevance
from app.graph.nodes.executor import executor_node
from app.guardrails.sandbox import SandboxExecutor
from app.sdk.low_level.retrieval import retrieve

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_redis():
    mock_r = MagicMock()
    mock_r.get.return_value = None
    return mock_r

@pytest.mark.anyio
@patch("app.services.core.redis_service.redis_cache_service")
@patch("app.graph.nodes.finalizer.SessionLocal")
@patch("app.graph.nodes.finalizer.get_llm_client")
async def test_finalizer_cache_miss_populates_redis(
    mock_llm_client, mock_session_local, mock_redis_service, mock_redis
):
    mock_redis_service.redis = mock_redis
    project_id = uuid.uuid4()
    
    # Mock database session and documents
    mock_db_session = MagicMock()
    mock_session_local.return_value = mock_db_session
    
    doc1 = Document(
        id=uuid.uuid4(),
        project_id=project_id,
        file_name="test_doc1.pdf",
        description="Test Doc 1 Description",
        status="completed",
        chunk_count=5,
        processing_metadata={"global_summary": "Summary of doc 1"},
        created_at=datetime.utcnow()
    )
    mock_db_session.query.return_value.filter.return_value.all.return_value = [doc1]
    
    # Mock LLM response to avoid network call
    mock_llm = AsyncMock()
    mock_llm_response = MagicMock()
    mock_llm_response.content = "Final answer content"
    mock_llm.ainvoke.return_value = mock_llm_response
    mock_llm_client.return_value = mock_llm

    state = AgentState(
        project_id=str(project_id),
        state_dir="/tmp/sac_states/test",
        stop_reason=StopReason.INSUFFICIENT_EVIDENCE,
        directive="test",
        unverified_claims=None
    )
    
    # Exec
    res = await finalizer_node(state)
    
    # Assert
    assert "test_doc1.pdf" in res["final_answer"]
    mock_redis.get.assert_called_once_with(f"project:{project_id}:documents_metadata")
    mock_redis.setex.assert_called_once()
    
    # Check what was cached
    args, kwargs = mock_redis.setex.call_args
    assert args[0] == f"project:{project_id}:documents_metadata"
    assert args[1] == 3600
    
    saved_metadata = json.loads(args[2])
    assert len(saved_metadata) == 1
    assert saved_metadata[0]["file_name"] == "test_doc1.pdf"
    assert saved_metadata[0]["global_summary"] == "Summary of doc 1"


@pytest.mark.anyio
@patch("app.services.core.redis_service.redis_cache_service")
@patch("app.graph.nodes.finalizer.SessionLocal")
async def test_finalizer_cache_hit_bypasses_db(
    mock_session_local, mock_redis_service, mock_redis
):
    mock_redis_service.redis = mock_redis
    project_id = uuid.uuid4()
    
    cached_metadata = [
        {
            "id": str(uuid.uuid4()),
            "file_name": "cached_doc.pdf",
            "description": "Cached Description",
            "status": "completed",
            "chunk_count": 10,
            "global_summary": "Cached Summary",
            "created_at": datetime.utcnow().isoformat()
        }
    ]
    mock_redis.get.return_value = json.dumps(cached_metadata)
    
    mock_db_session = MagicMock()
    mock_session_local.return_value = mock_db_session

    state = AgentState(
        project_id=str(project_id),
        state_dir="/tmp/sac_states/test",
        stop_reason=StopReason.INSUFFICIENT_EVIDENCE,
        directive="test",
        unverified_claims=None
    )
    
    # Exec
    res = await finalizer_node(state)
    
    # Assert
    assert "cached_doc.pdf" in res["final_answer"]
    mock_redis.get.assert_called_once_with(f"project:{project_id}:documents_metadata")
    # DB query should NOT be called
    mock_db_session.query.assert_not_called()


@pytest.mark.anyio
@patch("app.guardrails.router.ChatOpenAI")
async def test_check_query_relevance_rich_metadata(mock_chat):
    mock_response = AsyncMock()
    mock_response.content = "IN_SCOPE"
    mock_instance = mock_chat.return_value
    mock_instance.ainvoke.return_value = mock_response
    
    rich_metadata = [
        {
            "file_name": "hr_policy.pdf",
            "description": "HR policy guide",
            "global_summary": "This document contains vacation rules and guidelines"
        }
    ]
    
    # Exec with rich metadata dict list
    res = await check_query_relevance(
        query="How many vacation days do I get?",
        project_files=rich_metadata
    )
    
    assert res is True
    # Verify the compiled prompt contains the summary and name
    system_prompt = mock_instance.ainvoke.call_args[0][0][0].content
    assert "hr_policy.pdf: This document contains vacation rules and guidelines" in system_prompt


@patch("app.services.core.document.redis_cache_service")
def test_document_service_invalidates_cache(mock_redis_service):
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    project_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    
    mock_doc = Document(id=doc_id, project_id=project_id)
    
    mock_repo = MagicMock()
    # Mock repository methods instead of mocking BaseService class
    mock_repo.create.return_value = mock_doc
    mock_repo.update.return_value = mock_doc
    mock_repo.soft_delete.return_value = True
    mock_repo.get.return_value = mock_doc
    
    service = DocumentService(repository=mock_repo)
    
    # Exec Create
    service.create(DocumentCreate(
        user_id=uuid.uuid4(),
        project_id=project_id,
        file_name="new.pdf",
        file_size_bytes=100,
        mime_type="application/pdf",
        storage_path="project/new.pdf"
    ))
    mock_redis.delete.assert_any_call(f"project:{project_id}:documents_metadata")
    
    # Reset mock and Exec Update
    mock_redis.delete.reset_mock()
    service.update(doc_id, DocumentUpdate(file_name="updated.pdf"))
    mock_redis.delete.assert_any_call(f"project:{project_id}:documents_metadata")
    
    # Reset mock and Exec Delete
    mock_redis.delete.reset_mock()
    service.delete(doc_id)
    mock_redis.delete.assert_any_call(f"project:{project_id}:documents_metadata")


@pytest.mark.anyio
@patch("app.graph.nodes.executor.SandboxExecutor")
@patch("app.graph.nodes.executor.validate_code")
async def test_executor_node_propagates_project_id(mock_validate, mock_executor_class):
    mock_validate.return_value = []
    mock_executor_inst = MagicMock()
    mock_executor_inst.execute = AsyncMock(return_value=MagicMock())
    mock_executor_class.return_value = mock_executor_inst
    
    project_id = str(uuid.uuid4())
    state = AgentState(
        task_id="task-123",
        state_dir="/tmp/sac_states/test",
        project_id=project_id,
        _pending_code="print('hello')",
        current_turn=0
    )
    
    # Exec
    await executor_node(state)
    
    # Assert project_id was passed to SandboxExecutor
    mock_executor_class.assert_called_once_with(
        task_id="task-123",
        state_dir=Path("/tmp/sac_states/test"),
        project_id=project_id
    )


@pytest.mark.anyio
@patch("app.guardrails.sandbox.subprocess.run")
async def test_sandbox_executor_sets_project_id_env(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="done", stderr="")
    
    project_id = str(uuid.uuid4())
    executor = SandboxExecutor(
        task_id="task-123",
        state_dir=Path("/tmp/sac_states/test"),
        project_id=project_id
    )
    
    # Exec local execution flow
    with patch("app.guardrails.sandbox.settings") as mock_settings:
        mock_settings.SANDBOX_RUNTIME = "local"
        await executor.execute("print('local run')")
        
    # Assert PROJECT_ID is set in the env
    called_env = mock_run.call_args[1]["env"]
    assert called_env["PROJECT_ID"] == project_id


@pytest.mark.anyio
@patch("app.core.qdrant.qdrant_manager")
@patch("app.rag.embeddings.manager.EmbeddingManager")
@patch("app.sdk.low_level.retrieval.os.environ")
async def test_sdk_retrieve_filters_by_project_id(mock_environ, mock_emb_manager, mock_qdrant):
    project_id = str(uuid.uuid4())
    # Mock environment variable PROJECT_ID
    mock_environ.get.side_effect = lambda key, default=None: project_id if key == "PROJECT_ID" else default
    
    # Mock embeddings provider
    mock_provider = MagicMock()
    mock_provider.embed_text.return_value = [0.1] * 1536
    mock_emb_manager.get_provider.return_value = mock_provider
    
    # Mock Qdrant results
    mock_qdrant.search_vectors.return_value = []
    
    # Exec
    await retrieve(query="test query")
    
    # Assert Qdrant search_vectors was called with project filter
    mock_qdrant.search_vectors.assert_called_once()
    kwargs = mock_qdrant.search_vectors.call_args[1]
    assert "query_filter" in kwargs
    assert kwargs["query_filter"] is not None
    
    # Verify filter condition
    q_filter = kwargs["query_filter"]
    assert q_filter.must[0].key == "project_id"
    assert q_filter.must[0].match.value == project_id
