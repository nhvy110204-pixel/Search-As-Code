import ast
import subprocess
import tempfile
import asyncio
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from app.config.settings import settings

logger = logging.getLogger(__name__)

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
    # Bọc tạm thời code vào hàm async để cho phép cú pháp 'await' ở mức top-level
    validation_code = "async def __validation_main():\n" + "\n".join("    " + line for line in code.splitlines())
    try:
        tree = ast.parse(validation_code)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    validator = ASTValidator()
    validator.visit(tree)
    return validator.errors

def to_posix_mount_path(path_str: str) -> str:
    r"""
    Convert Windows path (e.g. C:\path\to\dir) to POSIX-compatible format for Docker volume mount (e.g. /c/path/to/dir)
    """
    path_str = os.path.abspath(path_str)
    import re
    match = re.match(r'^([a-zA-Z]):(.*)', path_str)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2).replace('\\', '/')
        return f"/{drive}{rest}"
    return path_str.replace('\\', '/')

def _classify_docker_error(returncode: int, stdout: str, stderr: str) -> ExecutionResult:
    stderr_lower = stderr.lower()
    if "cannot connect to the docker daemon" in stderr_lower or "docker daemon is not running" in stderr_lower:
        return ExecutionResult(stdout=stdout, stderr=f"DockerDaemonError: {stderr.strip()}", returncode=-3)
    if "unknown runtime" in stderr_lower:
        return ExecutionResult(stdout=stdout, stderr=f"DockerRuntimeError: {stderr.strip()}", returncode=-3)
    if "unable to find image" in stderr_lower or "repository does not exist" in stderr_lower or "pull access denied" in stderr_lower:
        return ExecutionResult(stdout=stdout, stderr=f"DockerImageError: {stderr.strip()}", returncode=-3)
    if "permission denied" in stderr_lower:
        return ExecutionResult(stdout=stdout, stderr=f"DockerPermissionError: {stderr.strip()}", returncode=-3)
    
    if returncode in {125, 126, 127}:
        return ExecutionResult(stdout=stdout, stderr=f"DockerEngineError: {stderr.strip()}", returncode=-3)
        
    return ExecutionResult(stdout=stdout, stderr=stderr, returncode=returncode)

class SandboxExecutor:
    def __init__(self, task_id: str, state_dir: Path, project_id: Optional[str] = None):
        self.task_id = task_id
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.project_id = project_id

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

        if settings.SANDBOX_RUNTIME == "docker":
            # Pre-flight check: Docker daemon online and runtime registration
            try:
                proc_info = await asyncio.create_subprocess_exec(
                    "docker", "info", "--format", "{{json .Runtimes}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_info, stderr_info = await proc_info.communicate()
                if proc_info.returncode != 0:
                    err_msg = stderr_info.decode().strip()
                    logger.error(f"Docker is not running or available: {err_msg}")
                    return ExecutionResult(
                        stdout="",
                        stderr=f"DockerDaemonError: Cannot connect to the Docker daemon. Detail: {err_msg}",
                        returncode=-3
                    )
                # Verify runtime if configured
                if settings.SANDBOX_DOCKER_RUNTIME:
                    import json
                    runtimes = {}
                    try:
                        runtimes = json.loads(stdout_info.decode().strip())
                    except Exception:
                        stdout_str = stdout_info.decode().strip()
                        if settings.SANDBOX_DOCKER_RUNTIME not in stdout_str:
                            return ExecutionResult(
                                stdout="",
                                stderr=f"DockerRuntimeError: Docker runtime '{settings.SANDBOX_DOCKER_RUNTIME}' is not configured in Docker daemon.",
                                returncode=-3
                            )
                    if settings.SANDBOX_DOCKER_RUNTIME and settings.SANDBOX_DOCKER_RUNTIME not in runtimes:
                        return ExecutionResult(
                            stdout="",
                            stderr=f"DockerRuntimeError: Docker runtime '{settings.SANDBOX_DOCKER_RUNTIME}' is not configured in Docker daemon. Available: {list(runtimes.keys())}",
                            returncode=-3
                        )
            except FileNotFoundError:
                return ExecutionResult(
                    stdout="",
                    stderr="DockerCLIError: 'docker' command line tool not found in host PATH.",
                    returncode=-3
                )

            # Write script to state_dir so it is accessible inside container mount
            import uuid
            script_filename = f"script_{uuid.uuid4().hex}.py"
            script_path = self.state_dir / script_filename
            try:
                script_path.write_text(wrapped_code, encoding="utf-8")

                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                project_root_posix = to_posix_mount_path(project_root)
                state_dir_posix = to_posix_mount_path(self.state_dir)
                script_path_posix = f"/workspace/{script_filename}"

                docker_args = [
                    "run", "--rm",
                    "--network", settings.SANDBOX_DOCKER_NETWORK,
                    "--memory", settings.SANDBOX_MEMORY,
                    "--cpus", str(settings.SANDBOX_CPU),
                    "--user", settings.SANDBOX_USER,
                    "--read-only",
                    "--tmpfs", "/tmp",
                    "--cap-drop=ALL",
                    "--security-opt", "no-new-privileges:true",
                    "--pids-limit", "50",
                    "-v", f"{project_root_posix}:/app:ro",
                    "-v", f"{state_dir_posix}:/workspace:rw,noexec",
                    "-w", "/app",
                    "-e", "PYTHONPATH=/app",
                    "-e", "STATE_DIR=/workspace",
                    "-e", f"TASK_ID={self.task_id}",
                    "-e", f"TURN_NUMBER={turn_number}",
                    "-e", f"PROJECT_ID={self.project_id or ''}",
                ]
                if settings.SANDBOX_DOCKER_RUNTIME:
                    docker_args.extend(["--runtime", settings.SANDBOX_DOCKER_RUNTIME])

                docker_args.extend([
                    settings.SANDBOX_DOCKER_IMAGE,
                    "python", script_path_posix
                ])

                logger.info(f"Running sandbox in Docker: docker {' '.join(docker_args)}")
                
                # Execute asynchronously
                proc = await asyncio.create_subprocess_exec(
                    "docker", *docker_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=settings.SANDBOX_DOCKER_TIMEOUT
                    )
                    stdout_str = stdout_bytes.decode(errors="replace")
                    stderr_str = stderr_bytes.decode(errors="replace")
                    returncode = proc.returncode
                    
                    return _classify_docker_error(returncode, stdout_str, stderr_str)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return ExecutionResult(
                        stdout="",
                        stderr=f"TimeoutExpired: Sandbox container execution timed out after {settings.SANDBOX_DOCKER_TIMEOUT} seconds",
                        returncode=-1
                    )
            finally:
                if script_path.exists():
                    try:
                        script_path.unlink()
                    except Exception:
                        pass
        else:
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
                            "PROJECT_ID": self.project_id or "",
                        })
                        return subprocess.run(
                            [sys.executable, script_path],
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                            env=custom_env
                        )
                    except subprocess.TimeoutExpired as e:
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
                try:
                    os.unlink(script_path)
                except Exception:
                    pass

    def _wrap_with_sdk(self, code: str) -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        indented_code = "\n".join("    " + line for line in code.splitlines())
        return f"""
import sys
import os
import asyncio

if os.path.exists("/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, r"{project_root}")

try:
    from app.sdk import sdk
except ImportError:
    sdk = None

from pathlib import Path
import json

STATE_DIR = Path(os.environ.get("STATE_DIR", r"{self.state_dir}"))

async def __async_sandbox_main():
{indented_code}

if __name__ == "__main__":
    asyncio.run(__async_sandbox_main())
"""
