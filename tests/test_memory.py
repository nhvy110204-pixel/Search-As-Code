import pytest
import uuid
import json
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User
from app.models.user_memory import UserMemory
from app.shared.enums import MemoryType
from app.services.agent.memory_service import MemoryService
from app.graph.nodes.extractor import extractor_node
from app.graph.graphs.agent_graph import agent_graph

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session):
    """Create a temporary user in the database to satisfy foreign key constraints."""
    user = User(
        username=f"testuser_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashedpassword123",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    db_session.delete(user)
    db_session.commit()


@pytest.mark.anyio
@patch("app.services.agent.memory_service.embed")
@patch("app.core.qdrant.qdrant_manager.upsert_vector")
async def test_save_and_recall_memory(mock_upsert, mock_embed, db_session, test_user):
    # Mock SDK embedding provider
    mock_embed.return_value = [[0.1] * 1536]
    
    user_id = test_user.id
    content = "User prefers using pure urllib for simple HTTP requests."
    
    # Save memory
    embedding_id = await MemoryService.save_memory(
        db=db_session,
        user_id=user_id,
        content=content,
        memory_type=MemoryType.PREFERENCE
    )
    db_session.commit()
    
    assert embedding_id is not None
    mock_upsert.assert_called_once()
    
    # Verify in DB
    db_record = db_session.scalar(
        select(UserMemory).where(UserMemory.embedding_id == embedding_id)
    )
    assert db_record is not None
    assert db_record.content == content
    assert db_record.user_id == user_id
    
    # Recall memory (will use DB fallback in offline test since Qdrant client is mocked or empty)
    recalled = await MemoryService.recall_memories(
        db=db_session,
        user_id=user_id,
        query="HTTP requests",
        limit=2
    )
    
    assert len(recalled) >= 1
    assert content in recalled
    
    # Cleanup DB record
    db_session.delete(db_record)
    db_session.commit()


@pytest.mark.anyio
@patch("app.graph.nodes.extractor.ChatOpenAI")
@patch("app.services.agent.memory_service.embed")
async def test_extractor_node_saves_memories(mock_embed, mock_chat_openai, db_session, test_user):
    # Mock SDK embedding
    mock_embed.return_value = [[0.2] * 1536]
    
    # Mock ChatOpenAI to return a JSON array string representing extracted facts
    mock_llm_instance = MagicMock()
    mock_chat_openai.return_value = mock_llm_instance
    
    mock_response = MagicMock()
    mock_response.content = '["User prefers pure python standard libraries.", "The database port is 5432."]'
    mock_llm_instance.ainvoke = AsyncMock(return_value=mock_response)
    
    user_id = test_user.id
    state = {
        "user_id": str(user_id),
        "directive": "Retrieve system configs",
        "turn_summaries": [
            {"turn": 1, "action": "sdk.retrieve()", "outcome": "Success"}
        ],
        "messages": []
    }
    
    # Execute extractor node
    await extractor_node(state)
    
    # Verify that memories are persisted into PostgreSQL
    db_records = db_session.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id)
    ).all()
    
    assert len(db_records) == 2
    contents = [r.content for r in db_records]
    assert "User prefers pure python standard libraries." in contents
    assert "The database port is 5432." in contents
    
    # Cleanup
    for r in db_records:
        db_session.delete(r)
    db_session.commit()


@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.ChatOpenAI")
@patch("app.graph.nodes.extractor.ChatOpenAI")
@patch("app.services.agent.memory_service.embed")
async def test_agent_graph_full_memory_loop(mock_embed, mock_extractor_llm, mock_reasoner_llm, db_session, test_user):
    # Mock embeddings
    mock_embed.return_value = [[0.3] * 1536]
    
    # Mock Reasoner LLM (Turn 1 returns code, Turn 2 returns final answer)
    mock_reasoner_instance = MagicMock()
    mock_reasoner_llm.return_value = mock_reasoner_instance
    
    resp_reasoner_1 = MagicMock()
    resp_reasoner_1.content = """
I will search for target server port.
```python
import json
output_file = STATE_DIR / "port.json"
output_file.write_text(json.dumps({"port": 8080}))
print("Port written!")
```
"""
    resp_reasoner_2 = MagicMock()
    resp_reasoner_2.content = "Port 8080 was discovered. The task is complete."
    mock_reasoner_instance.ainvoke = AsyncMock()
    mock_reasoner_instance.ainvoke.side_effect = [resp_reasoner_1, resp_reasoner_2]
    
    # Mock Extractor LLM (returns one preference)
    mock_extractor_instance = MagicMock()
    mock_extractor_llm.return_value = mock_extractor_instance
    resp_extractor = MagicMock()
    resp_extractor.content = '["User uses local development port 8080."]'
    mock_extractor_instance.ainvoke = AsyncMock(return_value=resp_extractor)
    
    user_id = test_user.id
    initial_state = {
        "task_id": "test-memory-e2e-loop",
        "user_id": str(user_id),
        "directive": "Find dev server config",
        "domain_context": None,
        "constraints": []
    }
    
    # Run graph with a specific session thread config (should use checkpointer)
    config = {"configurable": {"thread_id": "test_e2e_memory_thread"}}
    final_state = await agent_graph.ainvoke(initial_state, config=config)
    
    # Assertions
    assert final_state["current_turn"] == 1
    assert "port.json" in final_state["state_files"]
    
    # Verify that the extractor node successfully saved the new memory record
    db_records = db_session.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id)
    ).all()
    
    assert len(db_records) == 1
    assert db_records[0].content == "User uses local development port 8080."
    
    # Cleanup
    db_session.delete(db_records[0])
    db_session.commit()
