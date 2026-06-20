import pytest
import asyncio
from pathlib import Path
from app.guardrails.sandbox import validate_code, SandboxExecutor, ExecutionResult

def test_ast_validation_allowed():
    # Allowed imports and calls
    code = """
import json
import math
from pathlib import Path

data = {"value": math.sqrt(16)}
print(json.dumps(data))
"""
    errors = validate_code(code)
    assert len(errors) == 0, f"Expected no errors, got: {errors}"

def test_ast_validation_syntax_error():
    code = """
def func(
   print("Hello")
"""
    errors = validate_code(code)
    assert len(errors) > 0
    assert any("SyntaxError" in err for err in errors)

def test_ast_validation_blocked_imports():
    # Attempting to import unauthorized modules
    code1 = "import os"
    assert "Blocked import: os" in validate_code(code1)

    code2 = "from subprocess import run"
    assert "Blocked import: subprocess" in validate_code(code2)

    code3 = "import sys"
    assert "Blocked import: sys" in validate_code(code3)

def test_ast_validation_blocked_calls():
    # Attempting to use eval, exec, compile, open
    assert any("Blocked call: eval" in err for err in validate_code("eval('1 + 1')"))
    assert any("Blocked call: exec" in err for err in validate_code("exec('a = 1')"))
    assert any("Blocked call: open" in err for err in validate_code("open('file.txt', 'r')"))

    # Attribute calls
    assert any("Blocked call: os.system" in err for err in validate_code("import os; os.system('echo 1')"))
    assert any("Blocked call: subprocess.run" in err for err in validate_code("import subprocess; subprocess.run(['ls'])"))

@pytest.mark.anyio
async def test_sandbox_executor_success(tmp_path):
    executor = SandboxExecutor(task_id="test-task-success", state_dir=tmp_path)
    code = """
import json
import math

result = math.factorial(5)
print(json.dumps({"factorial": result}))
"""
    res = await executor.execute(code)
    assert res.returncode == 0
    assert "120" in res.stdout
    assert res.stderr == ""

@pytest.mark.anyio
async def test_sandbox_executor_validation_failure(tmp_path):
    executor = SandboxExecutor(task_id="test-task-fail-val", state_dir=tmp_path)
    code = "import os; os.system('clear')"
    res = await executor.execute(code)
    assert res.returncode == 2
    assert "Blocked import: os" in res.stderr
    assert res.stdout == ""

@pytest.mark.anyio
async def test_sandbox_executor_runtime_error(tmp_path):
    executor = SandboxExecutor(task_id="test-task-fail-run", state_dir=tmp_path)
    code = "1 / 0"
    res = await executor.execute(code)
    assert res.returncode != 0
    assert res.returncode != 2  # Not a validation error
    assert "ZeroDivisionError" in res.stderr

@pytest.mark.anyio
async def test_sandbox_executor_timeout(tmp_path):
    executor = SandboxExecutor(task_id="test-task-timeout", state_dir=tmp_path)
    # Simple busy loop or sleep that exceeds timeout
    code = """
import asyncio

async def run():
    await asyncio.sleep(5)

asyncio.run(run())
"""
    res = await executor.execute(code, timeout=1)
    assert res.returncode == -1
    assert "TimeoutExpired" in res.stderr

@pytest.mark.anyio
async def test_executor_node_success(tmp_path):
    from app.graph.nodes.executor import executor_node
    import uuid
    
    state = {
        "task_id": str(uuid.uuid4()),
        "directive": "test task",
        "domain_context": None,
        "constraints": [],
        "messages": [],
        "turns": [],
        "current_turn": 0,
        "max_turns": 10,
        "state_dir": str(tmp_path),
        "state_files": [],
        "turn_summaries": [],
        "last_coverage_summary": None,
        "last_error": None,
        "coverage_score": 0.0,
        "confidence_score": 0.0,
        "results": None,
        "is_complete": False,
        "stop_reason": None,
        "total_sdk_calls": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "_pending_code": "print('Hello World')"
    }
    
    new_state = await executor_node(state)
    assert new_state["current_turn"] == 1
    assert len(new_state["turns"]) == 1
    assert new_state["turns"][0]["returncode"] == 0
    assert "Hello World" in new_state["turns"][0]["stdout"]
    assert new_state["_pending_code"] is None
