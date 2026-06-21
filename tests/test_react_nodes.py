import pytest
import shutil
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from app.graph.state.agent_state import AgentState, TurnSummary
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reasoner import reasoner_node, build_working_memory, _extract_code_block
from app.graph.nodes.execution_validator import execution_validator_node

def test_extract_code_block():
    # Test valid python block
    code1 = """Here is the code:
```python
import json
print("Hello")
```
Hope it works!"""
    assert _extract_code_block(code1) == 'import json\nprint("Hello")'

    # Test raw code fence
    code2 = """```
import math
print(math.sqrt(4))
```"""
    assert _extract_code_block(code2) == 'import math\nprint(math.sqrt(4))'

    # Test no code block
    assert _extract_code_block("print('hello')") is None


def test_build_working_memory():
    state = {
        "task_id": "test-task-id",
        "directive": "Retrieve CVE info",
        "domain_context": None,
        "constraints": ["limit to 5 hits", "exclude drafts"],
        "messages": [],
        "turns": [],
        "current_turn": 1,
        "max_turns": 5,
        "state_dir": "/tmp/test",
        "state_files": ["step1_results.json"],
        "turn_summaries": [
            TurnSummary(turn=1, action="sdk.retrieve()", outcome="OK")
        ],
        "last_error": "SyntaxError: invalid syntax",
    }
    memory = build_working_memory(state)
    
    assert "Retrieve CVE info" in memory
    assert "limit to 5 hits" in memory
    assert "Turn 1:" in memory
    assert "Action: sdk.retrieve()" in memory
    assert "step1_results.json" in memory
    assert "SyntaxError: invalid syntax" in memory


@pytest.mark.anyio
async def test_planner_node_initialization():
    state = {
        "task_id": "test-planner-task",
        "directive": "Extract active exploits",
        "domain_context": "CVE-2023-38606",
        "constraints": ["No system calls"],
    }
    
    res = await planner_node(state)
    
    assert res["current_turn"] == 0
    assert res["max_turns"] == 10
    assert res["coverage_score"] == 0.0
    assert res["is_complete"] is False
    assert res["_pending_code"] is None
    
    # Check that the directory was created
    state_dir = Path(res["state_dir"])
    assert state_dir.exists()
    
    # Check messages
    messages = res["messages"]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "sdk.search.web_many" in messages[0].content
    assert "Extract active exploits" in messages[1].content
    assert "CVE-2023-38606" in messages[1].content
    assert "No system calls" in messages[1].content
    
    # Cleanup directory
    shutil.rmtree(state_dir, ignore_errors=True)


@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.get_llm_client")
async def test_reasoner_node_execution(mock_get_llm_client):
    # Mock LLM instance and its asynchronous invoke method
    mock_llm_instance = MagicMock()
    mock_get_llm_client.return_value = mock_llm_instance
    
    mock_response = MagicMock()
    mock_response.content = """
I will search for the requested CVEs now.
```python
from app.sdk import sdk
results = await sdk.retrieve("CVE-2023-38606")
```
"""
    mock_llm_instance.ainvoke = AsyncMock(return_value=mock_response)
    
    # State with system message and initial workspace files
    state = {
        "task_id": "test-reasoner-task",
        "directive": "Extract active exploits",
        "messages": [
            SystemMessage(content="System instruction template"),
            HumanMessage(content="User input")
        ],
        "turns": [],
        "current_turn": 0,
        "max_turns": 10,
        "state_dir": "/tmp/test",
        "state_files": [],
        "turn_summaries": [],
    }
    
    res = await reasoner_node(state)
    
    # Verify mock was called
    mock_llm_instance.ainvoke.assert_called_once()
    
    # Check return state
    assert res["_pending_code"] == 'from app.sdk import sdk\nresults = await sdk.retrieve("CVE-2023-38606")'
    assert len(res["messages"]) == 1
    assert isinstance(res["messages"][0], AIMessage)
    assert "I will search for the requested CVEs now." in res["messages"][0].content


@pytest.mark.anyio
async def test_execution_validator_node_pass_through_on_failed_execution():
    state = {
        "current_turn": 1,
        "turns": [
            {
                "turn_number": 1,
                "generated_code": "print('hello')",
                "stdout": "",
                "stderr": "ValueError: sandbox crash",
                "returncode": 1,
                "sdk_calls": 0,
                "state_files": []
            }
        ]
    }
    res = await execution_validator_node(state)
    assert res == {}  # Verify clean pass-through


@pytest.mark.anyio
async def test_execution_validator_node_calculates_scores():
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_dir = Path(tmp_dir)
        hits_file = state_dir / "retrieved_hits_turn_1.json"
        hits_file.write_text(json.dumps([
            {"id": "hit1", "title": "Doc1", "content": "Text", "score": 0.8}
        ]))
        
        completion_file = state_dir / "completion_signal.json"
        completion_file.write_text(json.dumps({
            "is_complete": True,
            "coverage_score": 0.95,
            "confidence_score": 0.9
        }))
        
        state = {
            "current_turn": 1,
            "state_dir": tmp_dir,
            "coverage_score": 0.0,
            "confidence_score": 0.0,
            "turns": [
                {
                    "turn_number": 1,
                    "generated_code": "sdk.retrieve()",
                    "returncode": 0,
                    "sdk_calls": 1
                }
            ]
        }
        
        res = await execution_validator_node(state)
        assert res["evidence_count"] == 1
        assert res["retrieval_score"] == 0.8
        assert res["coverage_score"] == 0.95
        assert res["confidence_score"] == 0.9
        assert res["is_complete"] is True
