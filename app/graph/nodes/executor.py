from typing import Any
from langchain_core.messages import HumanMessage
from app.graph.state.agent_state import AgentState, TurnRecord, TurnSummary
from app.guardrails.sandbox import SandboxExecutor, validate_code
from app.core.database import SessionLocal
from app.models.sdk_operation import SDKOperation
from sqlalchemy import select, func
from pathlib import Path
import os

async def executor_node(state: AgentState) -> dict:
    """
    Node ACT: AST-validate rồi execute model-generated code trong sandbox.
    Build compact TurnSummary để REASONER dùng làm working memory.
    """
    code = state.get("_pending_code", "") or ""
    if not code:
        # Reasoner did not generate code, meaning it wants to finish.
        # Pass through without incrementing current_turn.
        return {
            "is_complete": True,
            "_pending_code": None
        }
        
    turn_num = state.get("current_turn", 0) + 1
    state_dir = Path(state["state_dir"])

    # AST validation trước khi chạm tới subprocess
    validation_errors = validate_code(code)
    if validation_errors:
        error_msg = "AST validation failed:\n" + "\n".join(validation_errors)
        turn_summary = TurnSummary(
            turn=turn_num,
            action="(code rejected before execution)",
            outcome=f"Validation error: {validation_errors[0]}",
        )
        turn_record = TurnRecord(
            turn_number=turn_num,
            generated_code=code,
            stdout="",
            stderr=error_msg,
            returncode=2,
            sdk_calls=0,
            state_files=state.get("state_files", []),
            action_summary="(rejected)",
            outcome_summary=validation_errors[0],
        )
        return {
            **state,
            "turns": state.get("turns", []) + [turn_record],
            "current_turn": turn_num,
            "turn_summaries": state.get("turn_summaries", []) + [turn_summary],
            "last_error": error_msg,
            "messages": [HumanMessage(content=f"=== TURN {turn_num}: VALIDATION ERROR ===\n{error_msg}\n\nFix the code and try again.")],
            "_pending_code": None,
        }

    # Execute trong sandbox
    executor = SandboxExecutor(
        task_id=state["task_id"],
        state_dir=state_dir,
        project_id=state.get("project_id"),
    )
    # Run execution with turn_number propagated
    result = await executor.execute(code, timeout=120, turn_number=turn_num)

    # Query the database to get actual SDK call count logged during execution
    import sys
    from app.config.settings import settings
    if "pytest" in sys.modules or settings.APP_ENV == "test" or os.environ.get("APP_ENV") == "test":
        sdk_calls_count = 0
    else:
        db = SessionLocal()
        try:
            query = select(func.count(SDKOperation.id)).where(
                SDKOperation.task_id == uuid_from_str(state["task_id"]),
                SDKOperation.turn_number == turn_num
            )
            sdk_calls_count = db.scalar(query) or 0
        except Exception:
            sdk_calls_count = 0
        finally:
            db.close()

    # List state files after execution
    state_files = []
    if state_dir.exists():
        state_files = [
            f.name for f in state_dir.iterdir()
            if f.is_file() and f.suffix == ".json"
        ]

    # Build compact TurnSummary for working memory
    action_summary = _summarize_action(code)
    outcome_summary = _summarize_outcome(result)
    turn_summary = TurnSummary(
        turn=turn_num,
        action=action_summary,
        outcome=outcome_summary,
    )

    # Create TurnRecord (full record for checkpointing)
    turn_record = TurnRecord(
        turn_number=turn_num,
        generated_code=code,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        sdk_calls=sdk_calls_count,
        state_files=state_files,
        action_summary=action_summary,
        outcome_summary=outcome_summary,
    )

    # Build observation message to feed back to REASONER
    obs_content = _build_observation(result, state_files, turn_num)
    observation_msg = HumanMessage(content=obs_content)

    last_error = result.stderr[:500] if result.returncode != 0 else None

    return {
        **state,
        "turns": state.get("turns", []) + [turn_record],
        "current_turn": turn_num,
        "state_files": state_files,
        "total_sdk_calls": state.get("total_sdk_calls", 0) + sdk_calls_count,
        "turn_summaries": state.get("turn_summaries", []) + [turn_summary],
        "last_error": last_error,
        "messages": [observation_msg],
        "_pending_code": None,
    }


def _summarize_action(code: str) -> str:
    """Summarize action line from code — use the first line containing sdk."""
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("sdk.") or "sdk." in line:
            return line[:120]
    # Fallback: first non-blank non-comment line
    for line in code.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:120]
    return "(no action)"


def _summarize_outcome(result) -> str:
    """Summarize outcome line from stdout/stderr."""
    if result.returncode != 0:
        first_err = (result.stderr or "").splitlines()[0] if result.stderr else "error"
        return f"FAILED: {first_err[:120]}"
    # Get last non-empty line of stdout
    lines = [l for l in (result.stdout or "").splitlines() if l.strip()]
    return lines[-1][:120] if lines else "OK (no output)"


def _build_observation(result, state_files: list, turn_num: int) -> str:
    status = "✓ Success" if result.returncode == 0 else "✗ Error"
    return f"""
=== EXECUTION RESULT (Turn {turn_num}) ===
Status: {status}
Return code: {result.returncode}

STDOUT:
{result.stdout[:3000] if result.stdout else "(empty)"}

{f"STDERR:{chr(10)}{result.stderr[:1000]}" if result.stderr else ""}

State files available: {state_files}
""".strip()


def uuid_from_str(val: Any) -> Any:
    import uuid
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return val
