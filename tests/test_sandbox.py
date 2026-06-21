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

@pytest.mark.anyio
async def test_sandbox_executor_top_level_await(tmp_path):
    executor = SandboxExecutor(task_id="test-task-top-level-await", state_dir=tmp_path)
    code = """
import asyncio
await asyncio.sleep(0.01)
print("Top-level await executed successfully!")
"""
    res = await executor.execute(code)
    assert res.returncode == 0
    assert "Top-level await executed successfully!" in res.stdout
    assert not res.stderr

def test_to_posix_mount_path():
    from app.guardrails.sandbox import to_posix_mount_path
    import sys
    import os
    # Windows style paths
    assert to_posix_mount_path(r"C:\Users\test") == "/c/Users/test"
    assert to_posix_mount_path(r"d:\Workspace\project") == "/d/Workspace/project"
    # POSIX style paths
    if sys.platform != "win32":
        assert to_posix_mount_path("/home/user/app") == "/home/user/app"
    else:
        current_drive = os.path.splitdrive(os.path.abspath("/"))[0].lower().replace(":", "")
        assert to_posix_mount_path("/home/user/app") == f"/{current_drive}/home/user/app"

@pytest.mark.anyio
async def test_sandbox_executor_docker(tmp_path):
    import shutil
    import subprocess
    from app.config.settings import settings

    # Check if Docker is installed and running
    docker_available = shutil.which("docker") is not None
    docker_running = False
    if docker_available:
        try:
            res = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            docker_running = (res.returncode == 0)
        except Exception:
            pass

    if not docker_running:
        pytest.skip("Docker daemon is not available/running. Skipping Docker sandbox tests.")

    # Check if image is built
    image_exists = False
    try:
        res = subprocess.run(["docker", "image", "inspect", settings.SANDBOX_DOCKER_IMAGE], capture_output=True)
        image_exists = (res.returncode == 0)
    except Exception:
        pass

    if not image_exists:
        pytest.skip(f"Docker image {settings.SANDBOX_DOCKER_IMAGE} not built. Skipping Docker sandbox execution test.")

    # Force Docker runtime
    original_runtime = settings.SANDBOX_RUNTIME
    original_docker_runtime = settings.SANDBOX_DOCKER_RUNTIME
    try:
        settings.SANDBOX_RUNTIME = "docker"
        settings.SANDBOX_DOCKER_RUNTIME = None
        
        executor = SandboxExecutor(task_id="test-docker-execution", state_dir=tmp_path)
        code = """
import json
print(json.dumps({"message": "Hello from Docker!"}))
"""
        res = await executor.execute(code)
        assert res.returncode == 0
        assert "Hello from Docker!" in res.stdout
        assert res.stderr == ""

        # Test pre-flight check failure on invalid runtime
        settings.SANDBOX_DOCKER_RUNTIME = "non-existent-runtime"
        res_fail = await executor.execute(code)
        assert res_fail.returncode == -3
        assert "DockerRuntimeError" in res_fail.stderr

    finally:
        settings.SANDBOX_RUNTIME = original_runtime
        settings.SANDBOX_DOCKER_RUNTIME = original_docker_runtime

