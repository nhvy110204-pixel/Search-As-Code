import pytest
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from app.graph.graphs.agent_graph import agent_graph
from app.shared.enums import StopReason

@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.ChatOpenAI")
async def test_agent_graph_full_loop(mock_chat_openai):
    # Mock LLM instances
    mock_llm_instance = MagicMock()
    mock_chat_openai.return_value = mock_llm_instance
    
    # We will simulate 2 turns:
    # Turn 1: Reasoner generates a valid python code block to write to state dir
    # Turn 2: Reasoner sees the file on disk and responds with no code block (terminates graph)
    
    response_turn1 = MagicMock()
    response_turn1.content = """
Let me initialize the search and write intermediate findings.
```python
import json

# Write state output inside the sandbox's STATE_DIR workspace (globally injected by executor wrapper)
output_file = STATE_DIR / "findings.json"
output_file.write_text(json.dumps({"cves": ["CVE-2023-38606"], "status": "extracted"}))
print("File written successfully!")
```
"""
    response_turn2 = MagicMock()
    response_turn2.content = "I found the requested Apple kernel CVE info in findings.json. The task is complete."
    
    mock_llm_instance.ainvoke = AsyncMock()
    mock_llm_instance.ainvoke.side_effect = [response_turn1, response_turn2]
    
    # Input initial state
    initial_state = {
        "task_id": "test-integration-loop",
        "directive": "Extract active iOS kernel exploits",
        "domain_context": None,
        "constraints": [],
    }
    
    # Run the graph
    config = {"configurable": {"thread_id": "test_agent_graph_thread"}}
    final_state = await agent_graph.ainvoke(initial_state, config=config)
    
    # Print turns for debugging
    if final_state.get("turns"):
        print("\n--- TURN 0 STDOUT ---")
        print(final_state["turns"][0].get("stdout"))
        print("--- TURN 0 STDERR ---")
        print(final_state["turns"][0].get("stderr"))
        print("--- RETURN CODE ---")
        print(final_state["turns"][0].get("returncode"))

    # Assertions
    assert final_state["current_turn"] == 1  # 1 execute turn, turn 2 only thinks and ends
    assert "findings.json" in final_state["state_files"]
    assert len(final_state["turn_summaries"]) == 1
    assert final_state["turn_summaries"][0]["turn"] == 1
    assert "findings.json" in final_state["turns"][0]["state_files"]
    
    # Assert code output was saved in workspace
    state_dir = Path(final_state["state_dir"])
    assert state_dir.exists()
    assert (state_dir / "findings.json").exists()
    
    # Cleanup state workspace
    shutil.rmtree(state_dir, ignore_errors=True)


@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.ChatOpenAI")
async def test_agent_graph_sandbox_self_debugging(mock_chat_openai):
    mock_llm_instance = MagicMock()
    mock_chat_openai.return_value = mock_llm_instance
    
    # Mock responses:
    # Turn 1: Generates code that will crash at runtime in sandbox
    response_turn1 = MagicMock()
    response_turn1.content = """
Let's run some code that crashes.
```python
raise ValueError("Simulated sandbox crash")
```
"""
    # Turn 2: Reasoner sees the error and terminates by generating no code
    response_turn2 = MagicMock()
    response_turn2.content = "Since the previous code crashed, I will finalize the run."
    
    mock_llm_instance.ainvoke = AsyncMock()
    mock_llm_instance.ainvoke.side_effect = [response_turn1, response_turn2]
    
    initial_state = {
        "task_id": "test-sandbox-debug-loop",
        "directive": "Test self-debugging on crash",
        "domain_context": None,
        "constraints": [],
    }
    
    config = {"configurable": {"thread_id": "test_sandbox_debug_thread"}}
    final_state = await agent_graph.ainvoke(initial_state, config=config)
    
    # Assertions
    assert final_state["current_turn"] == 1  # 1 executing turn (failed), turn 2 only thinks and ends
    assert len(final_state["turns"]) == 1
    assert final_state["turns"][0]["returncode"] != 0
    assert "Simulated sandbox crash" in final_state["turns"][0]["stderr"]
    
    # Cleanup state workspace
    state_dir = Path(final_state["state_dir"])
    shutil.rmtree(state_dir, ignore_errors=True)


@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.ChatOpenAI")
@patch("app.graph.nodes.finalizer.ChatOpenAI")
async def test_agent_graph_citation_self_correction(mock_finalizer_chat, mock_reasoner_chat):
    # Mock Reasoner
    mock_reasoner_llm = MagicMock()
    mock_reasoner_chat.return_value = mock_reasoner_llm
    
    # Reasoner Turn 1: Write evidence & completion signal
    response_reasoner = MagicMock()
    response_reasoner.content = """
I will gather evidence.
```python
import json
results_file = STATE_DIR / "final_results.json"
results_file.write_text(json.dumps({
    "evidence": [
        {"title": "Doc1", "content": "Evidence text", "metadata": {"page_number": 1}}
    ]
}))
signal_file = STATE_DIR / "completion_signal.json"
signal_file.write_text(json.dumps({
    "is_complete": True,
    "coverage_score": 1.0,
    "confidence_score": 1.0
}))
```
"""
    mock_reasoner_llm.ainvoke = AsyncMock(return_value=response_reasoner)
    
    # Mock Finalizer
    mock_finalizer_llm = MagicMock()
    mock_finalizer_chat.return_value = mock_finalizer_llm
    
    # Finalizer Call 1: Return invalid citation [2] (out of bounds, since len(evidence) == 1)
    response_finalizer_1 = MagicMock()
    response_finalizer_1.content = "According to the document, the zero-day was active [2]."
    
    # Finalizer Call 2: Return valid citation [1]
    response_finalizer_2 = MagicMock()
    response_finalizer_2.content = "According to the document, the zero-day was active [1]."
    
    mock_finalizer_llm.ainvoke = AsyncMock()
    mock_finalizer_llm.ainvoke.side_effect = [response_finalizer_1, response_finalizer_2]
    
    initial_state = {
        "task_id": "test-citation-self-correct",
        "directive": "Extract active exploits",
        "domain_context": None,
        "constraints": [],
    }
    
    config = {"configurable": {"thread_id": "test_citation_self_correct_thread"}}
    final_state = await agent_graph.ainvoke(initial_state, config=config)
    
    # Assertions
    assert final_state["citation_retry_counter"] == 1
    assert final_state["final_answer"] == "According to the document, the zero-day was active [1]."
    assert final_state["unverified_claims"] is None
    
    # Cleanup state workspace
    state_dir = Path(final_state["state_dir"])
    shutil.rmtree(state_dir, ignore_errors=True)


@pytest.mark.anyio
@patch("app.graph.nodes.reasoner.ChatOpenAI")
@patch("app.graph.nodes.finalizer.ChatOpenAI")
async def test_agent_graph_citation_fallback_refusal(mock_finalizer_chat, mock_reasoner_chat):
    # Mock Reasoner
    mock_reasoner_llm = MagicMock()
    mock_reasoner_chat.return_value = mock_reasoner_llm
    
    response_reasoner = MagicMock()
    response_reasoner.content = """
I will write evidence.
```python
import json
results_file = STATE_DIR / "final_results.json"
results_file.write_text(json.dumps({
    "evidence": [
        {"title": "Doc1", "content": "Evidence text"}
    ]
}))
signal_file = STATE_DIR / "completion_signal.json"
signal_file.write_text(json.dumps({
    "is_complete": True,
    "coverage_score": 1.0,
    "confidence_score": 1.0
}))
```
"""
    mock_reasoner_llm.ainvoke = AsyncMock(return_value=response_reasoner)
    
    # Mock Finalizer
    mock_finalizer_llm = MagicMock()
    mock_finalizer_chat.return_value = mock_finalizer_llm
    
    # Finalizer Call 1: Return invalid citation [2]
    response_finalizer_1 = MagicMock()
    response_finalizer_1.content = "Answer with invalid citation [2]."
    
    # Finalizer Call 2: Return invalid citation [3] again
    response_finalizer_2 = MagicMock()
    response_finalizer_2.content = "Answer with invalid citation [3] again."
    
    mock_finalizer_llm.ainvoke = AsyncMock()
    mock_finalizer_llm.ainvoke.side_effect = [response_finalizer_1, response_finalizer_2]
    
    initial_state = {
        "task_id": "test-citation-fallback",
        "directive": "Extract active exploits",
        "domain_context": None,
        "constraints": [],
    }
    
    config = {"configurable": {"thread_id": "test_citation_fallback_thread"}}
    final_state = await agent_graph.ainvoke(initial_state, config=config)
    
    # Assertions
    assert final_state["citation_retry_counter"] == 2
    assert final_state["stop_reason"] == StopReason.CITATION_VALIDATION_FAILED
    # Should contain the proactive refusal text
    assert "no documents uploaded" in final_state["final_answer"].lower()
    
    # Cleanup state workspace
    state_dir = Path(final_state["state_dir"])
    shutil.rmtree(state_dir, ignore_errors=True)
