import pytest
import uuid
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.schemas.dto.chat import PreparedChatStream
from app.services.chat.stream import ChatStreamService
from app.models.chat_session import ChatSession
from app.services.chat.stream_state import stream_state_manager

class MockRedis:
    def __init__(self):
        self.store = {}
    def get(self, key):
        return self.store.get(key)
    def exists(self, key):
        return 1 if key in self.store else 0
    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0

@pytest.mark.anyio
@patch("app.services.core.redis_service.redis_cache_service.redis", new_callable=MockRedis)
@patch("app.graph.graphs.agent_graph.agent_graph.aget_state", new_callable=AsyncMock)
@patch("app.graph.graphs.agent_graph.agent_graph.astream_events")
async def test_stream_sac_events_success(mock_astream_events, mock_aget_state, mock_redis, tmp_path):
    # Setup mock events
    async def mock_events_generator(*args, **kwargs):
        # 1. Planner starts and ends
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "planner"},
            "data": {}
        }
        from langchain_core.messages import AIMessage
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "planner"},
            "data": {"output": {"messages": [AIMessage(content="Planning to search.")]}}
        }
        # 2. Reasoner starts and ends with code
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "reasoner"},
            "data": {}
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "reasoner"},
            "data": {"output": {"_pending_code": "print('Code')"}}
        }
        # 3. Executor starts and ends
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "executor"},
            "data": {}
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "executor"},
            "data": {"output": {"turns": [{"stdout": "Output", "stderr": "", "returncode": 0}]}}
        }
        # 4. Finalizer token stream
        yield {
            "event": "on_llm_stream",
            "metadata": {"langgraph_node": "finalizer"},
            "data": {"chunk": "Final"}
        }
        yield {
            "event": "on_llm_stream",
            "metadata": {"langgraph_node": "finalizer"},
            "data": {"chunk": " response"}
        }
    
    mock_astream_events.side_effect = mock_events_generator
    
    # Setup mock final state
    mock_state_obj = MagicMock()
    mock_state_obj.values = {
        "final_answer": "Final response",
        "total_tokens": 150
    }
    mock_aget_state.return_value = mock_state_obj

    # Prepare input
    prepared = PreparedChatStream(
        run_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_message_id=uuid.uuid4(),
        assistant_message_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "Query"}]
    )

    # Mock DB Session & ChatSession project lookup
    mock_db = MagicMock()
    mock_session_factory = MagicMock()
    mock_db_session = MagicMock()
    mock_session_factory.return_value = mock_db_session
    
    mock_chat_session = MagicMock()
    mock_chat_session.project_id = uuid.uuid4()
    mock_db_session.query().filter().first.return_value = mock_chat_session

    # Initialize service
    service = ChatStreamService(db=mock_db, session_factory=mock_session_factory)
    
    # Mock outcome tracker methods so it does not write to real database
    service.outcome = MagicMock()

    async def is_disconnected():
        return False

    # Collect SSE events
    events = []
    async for event in service.stream_sac_events(prepared, is_disconnected):
        events.append(event)

    # Assert event names
    event_names = [e["event"] for e in events]
    assert "message.created" in event_names
    assert "agent.plan" in event_names
    assert "agent.code" in event_names
    assert "agent.sandbox_output" in event_names
    assert "message.delta" in event_names
    assert "message.done" in event_names

    # Check contents
    plan_event = [e for e in events if e["event"] == "agent.plan" and "completed" in e["data"]][0]
    plan_data = json.loads(plan_event["data"])
    assert "Planning to search." in plan_data["plan"]
    assert "duration_ms" in plan_data

    code_event = [e for e in events if e["event"] == "agent.code" and "completed" in e["data"]][0]
    code_data = json.loads(code_event["data"])
    assert code_data["code"] == "print('Code')"

    output_event = [e for e in events if e["event"] == "agent.sandbox_output"][0]
    output_data = json.loads(output_event["data"])
    assert output_data["stdout"] == "Output"

    done_event = [e for e in events if e["event"] == "message.done"][0]
    done_data = json.loads(done_event["data"])
    assert done_data["content"] == "Final response"
