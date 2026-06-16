import ast
import subprocess
import tempfile
import asyncio
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List

# Allowlist imports — chỉ các module này được phép trong model-generated code
ALLOWED_IMPORTS = {
    "json", "re", "math", "datetime", "collections",
    "itertools", "functools", "pathlib", "typing",
    "asyncio", "app.sdk",  # SDK entry point
}

# Blocked built-ins và call patterns — reject ngay nếu xuất hiện trong AST
BLOCKED_CALLS = {
    "eval", "exec", "compile", "__import__",
    "open",   # filesystem access phải qua STATE_DIR, không phải bare open()
    "breakpoint", "input",
}

@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int

class ASTValidator(ast.NodeVisitor):
    """
    Validate model-generated code trước khi execute.
    Chạy trên AST tree — không thể bị bypass bằng string tricks.
    """
    def __init__(self):
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                self.errors.append(f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        top = (node.module or "").split(".")[0]
        if top not in ALLOWED_IMPORTS:
            self.errors.append(f"Blocked import: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Detect bare calls: eval(...), exec(...), open(...)
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            self.errors.append(f"Blocked call: {node.func.id}()")
        # Detect attribute calls: os.system(...), subprocess.run(...)
        if isinstance(node.func, ast.Attribute):
            full = f"{getattr(node.func.value, 'id', '?')}.{node.func.attr}"
            attr = node.func.attr
            # Block system commands, shell execution, and subprocess spawns
            if attr in {
                "system", "popen", "Popen", "spawn", "spawnl", "spawnv", "spawnlp", "spawnvp",
                "spawnle", "spawnve", "spawnlpe", "spawnvpe", "execl", "execv", "execle", "execve",
                "execlp", "execvp", "execlpe", "execvpe", "create_subprocess_exec", "create_subprocess_shell"
            }:
                self.errors.append(f"Blocked call: {full}()")
            # Block run and call specifically on subprocess-like prefix objects
            elif attr in {"run", "call"} and getattr(node.func.value, 'id', '?') in {"subprocess", "sp"}:
                self.errors.append(f"Blocked call: {full}()")
        self.generic_visit(node)

def validate_code(code: str) -> List[str]:
    """
    Parse và validate code bằng AST.
    Trả về list errors — empty list = code hợp lệ.
    Phải gọi TRƯỚC khi execute, không phải sau.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    validator = ASTValidator()
    validator.visit(tree)
    return validator.errors

class SandboxExecutor:
    def __init__(self, task_id: str, state_dir: Path):
        self.task_id = task_id
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, code: str, timeout: int = 60, turn_number: int = 1) -> ExecutionResult:
        """
        Execute model-generated Python code trong sandbox.
        AST validation chạy TRƯỚC subprocess — không bao giờ execute code chưa được validate.
        """
        # Bước 1: AST validation — reject sớm, không tốn subprocess
        errors = validate_code(code)
        if errors:
            return ExecutionResult(
                stdout="",
                stderr="\n".join(errors),
                returncode=2,  # 2 = validation failure (phân biệt với runtime error)
            )

        # Bước 2: Wrap code với SDK imports và state dir injection
        wrapped_code = self._wrap_with_sdk(code)

        # Write to temp file (Windows requires delete=False during write because subprocess needs to open it)
        fd, script_path = tempfile.mkstemp(suffix='.py', text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(wrapped_code)

            import sys
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

            def run_subprocess():
                try:
                    custom_env = os.environ.copy()
                    custom_env.update({
                        "PYTHONPATH": project_root,
                        "STATE_DIR": str(self.state_dir),
                        "TASK_ID": self.task_id,
                        "TURN_NUMBER": str(turn_number),
                    })
                    return subprocess.run(
                        [sys.executable, script_path],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env=custom_env
                    )
                except subprocess.TimeoutExpired as e:
                    # Handle timeout and capture stdout/stderr safely
                    stdout_str = e.stdout.decode() if e.stdout else ""
                    stderr_str = e.stderr.decode() if e.stderr else f"TimeoutExpired: Command timed out after {timeout} seconds"
                    return subprocess.CompletedProcess(
                        args=e.cmd,
                        returncode=-1,
                        stdout=stdout_str,
                        stderr=stderr_str
                    )
                except Exception as e:
                    return subprocess.CompletedProcess(
                        args=["python", script_path],
                        returncode=-2,
                        stdout="",
                        stderr=f"SubprocessError: {str(e)}"
                    )

            result = await asyncio.to_thread(run_subprocess)

            return ExecutionResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )
        finally:
            # Clean up temporary file
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def _wrap_with_sdk(self, code: str) -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        return f"""
import sys
import os
sys.path.insert(0, r"{project_root}")

try:
    from app.sdk import sdk
except ImportError:
    sdk = None

from pathlib import Path
import json

STATE_DIR = Path(r"{self.state_dir}")

{code}
"""
