import pytest
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from app.graph.graphs.agent_graph import agent_graph

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
