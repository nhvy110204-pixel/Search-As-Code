# LangGraph ReAct Loop — Search as Code (SaC)

> File này là companion spec cho `search-as-code-backend-spec.md`.
> Mô tả chi tiết cách implement ReAct loop bằng LangGraph để orchestrate toàn bộ SaC pipeline.

---

## 1. Tại Sao LangGraph Phù Hợp Với SaC

ReAct (Reasoning + Acting) là pattern mà SaC paper mô tả chính xác:

```
Reason  →  Generate Code (Act)  →  Execute in Sandbox  →  Observe Results
   ↑                                                              │
   └──────────────────────────────────────────────────────────────┘
                    (loop until task complete)
```

LangGraph phù hợp vì:
- **Stateful graph**: Quản lý multi-turn state một cách tường minh — đúng với filesystem-based serde pattern
- **Conditional edges**: Quyết định tiếp tục loop hay kết thúc dựa trên observation
- **Human-in-the-loop**: Có thể pause giữa turns để inspect
- **Persistence**: Built-in checkpointing tích hợp với PostgreSQL (đúng tech stack)
- **Streaming**: Stream từng bước về client trong real-time

---

## 2. Graph Tổng Quan

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │ task directive
                    ┌──────▼──────┐
                    │   PLANNER   │  ← Phân tích task, khởi tạo state
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │        REASONER         │  ← Nhìn vào state hiện tại,
              │  (Think + Generate Code)│    quyết định bước tiếp theo
              └────────────┬────────────┘
                           │ generated Python code
              ┌────────────▼────────────┐
              │        EXECUTOR         │  ← Chạy code trong sandbox
              │   (Sandbox + SDK calls) │    Ghi state ra filesystem
              └────────────┬────────────┘
                           │ execution result (stdout/stderr)
              ┌────────────▼────────────┐
              │        OBSERVER         │  ← Parse kết quả, cập nhật state
              │   (Parse + Evaluate)    │    Quyết định có đủ kết quả chưa
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │  CONTINUE?  │  ← Conditional edge
                    └──────┬──────┘
                   yes /       \ no
          ┌────────▼───┐   ┌───▼────────┐
          │  REASONER  │   │ FINALIZER  │  ← Format output cuối
          │  (loop)    │   │            │
          └────────────┘   └─────┬──────┘
                                 │
                           ┌─────▼──────┐
                           │    END     │
                           └────────────┘
```

---

## 3. State Schema

LangGraph yêu cầu define state rõ ràng. Đây là `AgentState` cho SaC:

```python
# app/graph/state.py

from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
import operator

class TurnRecord(TypedDict):
    turn_number: int
    generated_code: str
    stdout: str
    stderr: str
    returncode: int
    sdk_calls: int
    state_files: List[str]   # files được serialize ra filesystem
    action_summary: str      # 1 dòng tóm tắt action (cho working memory)
    outcome_summary: str     # 1 dòng tóm tắt outcome (cho working memory)

class TurnSummary(TypedDict):
    """Compact summary của một turn — chỉ giữ action + outcome, không giữ full code/stdout."""
    turn: int
    action: str
    outcome: str

class AgentState(TypedDict):
    # --- Task context ---
    task_id: str
    directive: str                          # Task gốc từ user/parent agent
    domain_context: Optional[str]           # Domain knowledge nếu có
    constraints: List[str]                  # Ràng buộc của task

    # --- Conversation history (chỉ dùng trong PLANNER, không truyền vào REASONER) ---
    messages: Annotated[List[BaseMessage], add_messages]

    # --- Execution state ---
    turns: Annotated[List[TurnRecord], operator.add]  # Append-only
    current_turn: int
    max_turns: int                          # Hard limit (default: 10)

    # --- Sandbox state ---
    state_dir: str                          # Đường dẫn filesystem state
    state_files: List[str]                  # Files đang có trong state_dir

    # --- Working memory (P1) — REASONER đọc cái này, không đọc messages ---
    turn_summaries: List[TurnSummary]       # Compact summaries từ EXECUTOR mỗi turn
    last_coverage_summary: Optional[str]    # OBSERVER cập nhật (sdk.summarize output)
    last_error: Optional[str]               # EXECUTOR ghi khi returncode != 0

    # --- Score-based stopping (P2) — OBSERVER evaluate, should_continue kiểm tra ---
    coverage_score: float                   # verified_targets / total_targets (0.0–1.0)
    confidence_score: float                 # mean(ExtractionResult.confidence) (0.0–1.0)

    # --- Kết quả ---
    results: Optional[List[Any]]            # Final results sau khi done
    is_complete: bool
    stop_reason: Optional[str]              # "success" | "max_turns" | "error"

    # --- Metrics ---
    total_sdk_calls: int
    total_tokens: int
    cost_usd: float
```

---

## 4. Các Node Chi Tiết

### 4.1 Node: PLANNER

```python
# app/graph/nodes/planner.py

from langchain_core.messages import SystemMessage, HumanMessage
from ..state import AgentState
import uuid, os
from pathlib import Path

async def planner_node(state: AgentState) -> AgentState:
    """
    Node đầu tiên: Khởi tạo sandbox state dir, phân tích task,
    chuẩn bị system context cho REASONER.
    Chỉ chạy 1 lần duy nhất khi bắt đầu task.
    """
    task_id = state["task_id"]

    # Tạo dedicated state dir cho task này
    state_dir = Path(f"/tmp/sac_states/{task_id}")
    state_dir.mkdir(parents=True, exist_ok=True)

    # Build system message mô tả SDK cho model
    system_msg = SystemMessage(content=_build_system_prompt(state))

    # Build initial human message
    human_msg = HumanMessage(content=f"""
Task: {state['directive']}

{f"Domain context: {state['domain_context']}" if state.get('domain_context') else ""}
{f"Constraints: {chr(10).join(state['constraints'])}" if state.get('constraints') else ""}

State directory: {state_dir}
Generate Python code to begin retrieving information for this task.
""")

    return {
        **state,
        "state_dir": str(state_dir),
        "state_files": [],
        "current_turn": 0,
        "turns": [],
        "is_complete": False,
        "total_sdk_calls": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "messages": [system_msg, human_msg],
        # Working memory fields (P1)
        "turn_summaries": [],
        "last_coverage_summary": None,
        "last_error": None,
        # Score fields (P2)
        "coverage_score": 0.0,
        "confidence_score": 0.0,
    }


def _build_system_prompt(state: AgentState) -> str:
    return """
You are a Search as Code (SaC) agent. You solve knowledge-intensive tasks
by generating Python code that orchestrates search and LLM primitives.

=== AGENTIC SEARCH SDK ===

import json
from pathlib import Path

# Search primitives
results = sdk.search.web_many(
    queries=[{"vendor": str, "query": str}, ...],
    limit_per_query=8,      # results per query
    concurrency=12          # parallel requests
)  # → List[List[SearchHit]]

result = sdk.search.web_search(query: str, limit: int)  # → List[SearchHit]

# LLM primitives
extracted = sdk.llm.extract_many(
    items=[{"url": str, "text": str, ...}],
    instruction="...",
    schema={"field": type, ...}
)  # → List[Dict]

answer = sdk.llm.query_llm(prompt: str)  # → str (for planning sub-calls)
rows = sdk.llm.parse_jsonl(text: str)    # → List[Dict]

# Utility primitives
deduped = sdk.dedupe_by_url(items)           # → List
deduped = sdk.dedupe_by(items, key="cve")    # → List
text = sdk.join_result_fields(hit)           # → str
flat = sdk.flatten(list_of_lists)            # → List

# SearchHit fields: .url, .title, .snippet, .text

=== STATE MANAGEMENT ===
STATE_DIR is available as a Path object.
ALWAYS serialize intermediate results to STATE_DIR:

  with open(STATE_DIR / "step1_hits.json", "w") as f:
      json.dump([h.__dict__ for h in hits], f)

At the start of each turn, load state from previous turns:

  with open(STATE_DIR / "step1_hits.json") as f:
      hits = json.load(f)

Write final results to STATE_DIR / "final_results.json" when done.

=== PRINCIPLES ===
- Fan out queries in parallel for broad coverage
- Use site-scoped queries for source precision
- Verify with llm.extract_many before finalizing
- Filter by confidence >= 0.75
- Deduplicate aggressively
- If coverage is insufficient, refine queries in next turn
""".strip()
```

### 4.2 Node: REASONER

```python
# app/graph/nodes/reasoner.py

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from ..state import AgentState

# Model cho control plane
llm = ChatAnthropic(
    model="claude-opus-4-6",
    max_tokens=4096,
    temperature=0,
)

def build_working_memory(state: AgentState) -> str:
    """
    Tổng hợp trạng thái hiện tại thành một string compact để inject vào prompt.
    Reasoner chỉ cần biết: đang ở đâu, đã có gì, cần làm gì tiếp.
    Không truyền toàn bộ messages — tránh context bloat sau 5–10 turns.
    """
    lines = [
        f"## Task\n{state['directive']}",
        f"## Turn\n{state['current_turn'] + 1} / {state['max_turns']}",
    ]

    if state.get("domain_context"):
        lines.append(f"## Domain context\n{state['domain_context']}")

    if state.get("constraints"):
        lines.append("## Constraints\n" + "\n".join(f"- {c}" for c in state["constraints"]))

    # Compact summaries của các turns trước (không phải full code/stdout)
    if state.get("turn_summaries"):
        lines.append("## Previous turns")
        for s in state["turn_summaries"]:
            lines.append(f"- Turn {s['turn']}: {s['action']} → {s['outcome']}")

    # State files có thể load
    if state.get("state_files"):
        lines.append("## Available state files (load at start of your code)")
        for f in state["state_files"]:
            lines.append(f"  - {f}")

    # Coverage snapshot gần nhất
    if state.get("last_coverage_summary"):
        lines.append(f"## Coverage so far\n{state['last_coverage_summary']}")

    # Lỗi gần nhất để model tự sửa
    if state.get("last_error"):
        lines.append(f"## Last error (fix this)\n{state['last_error']}")

    lines.append("Generate Python code for the next step.")
    return "\n\n".join(lines)


async def reasoner_node(state: AgentState) -> AgentState:
    """
    Node THINK: Build working memory từ state hiện tại, gọi LLM một lần,
    extract code. Không truyền toàn bộ message history vào LLM.
    """
    working_memory = build_working_memory(state)

    # Chỉ gồm system prompt + working memory snapshot — O(1) tokens, không phải O(turns)
    messages = [
        SystemMessage(content=state["messages"][0].content),  # System prompt từ PLANNER
        HumanMessage(content=working_memory),
    ]
    response = await llm.ainvoke(messages)

    # Extract generated code từ response
    code = _extract_code_block(response.content)

    return {
        **state,
        # Vẫn append vào messages để LangGraph checkpointing hoạt động bình thường
        "messages": [response],    # add_messages reducer sẽ append
        "_pending_code": code,     # Pass sang EXECUTOR node
    }


def _extract_code_block(content: str) -> str:
    """Extract Python code từ markdown code block hoặc raw text."""
    if "```python" in content:
        start = content.index("```python") + 9
        end = content.index("```", start)
        return content[start:end].strip()
    elif "```" in content:
        start = content.index("```") + 3
        end = content.index("```", start)
        return content[start:end].strip()
    # Fallback: assume toàn bộ content là code
    return content.strip()
```

### 4.3 Node: EXECUTOR

```python
# app/graph/nodes/executor.py

from langchain_core.messages import HumanMessage
from ..state import AgentState, TurnRecord, TurnSummary
from app.core.sandbox import SandboxExecutor, validate_code
from pathlib import Path
import os

async def executor_node(state: AgentState) -> AgentState:
    """
    Node ACT: AST-validate rồi execute model-generated code trong sandbox.
    Build compact TurnSummary để REASONER dùng làm working memory.
    """
    code = state.get("_pending_code", "")
    turn_num = state["current_turn"] + 1
    state_dir = Path(state["state_dir"])

    # P3: AST validation trước khi chạm tới subprocess
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
            "turns": [turn_record],
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
    )
    result = await executor.execute(code, timeout=120)

    # Liệt kê state files sau execution
    state_files = [
        f.name for f in state_dir.iterdir()
        if f.is_file() and f.suffix == ".json"
    ]

    # P1: Build compact TurnSummary cho working memory
    action_summary = _summarize_action(code)
    outcome_summary = _summarize_outcome(result)
    turn_summary = TurnSummary(
        turn=turn_num,
        action=action_summary,
        outcome=outcome_summary,
    )

    # Tạo TurnRecord (full record cho checkpointing)
    turn_record = TurnRecord(
        turn_number=turn_num,
        generated_code=code,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        sdk_calls=result.sdk_calls_count,
        state_files=state_files,
        action_summary=action_summary,
        outcome_summary=outcome_summary,
    )

    # Build observation message để feed lại cho REASONER (qua checkpointing)
    obs_content = _build_observation(result, state_files, turn_num)
    observation_msg = HumanMessage(content=obs_content)

    last_error = result.stderr[:500] if result.returncode != 0 else None

    return {
        **state,
        "turns": [turn_record],
        "current_turn": turn_num,
        "state_files": state_files,
        "total_sdk_calls": state["total_sdk_calls"] + result.sdk_calls_count,
        "turn_summaries": state.get("turn_summaries", []) + [turn_summary],
        "last_error": last_error,
        "messages": [observation_msg],  # add_messages sẽ append
        "_pending_code": None,
    }


def _summarize_action(code: str) -> str:
    """Tóm tắt 1 dòng action từ code — dùng dòng đầu tiên có sdk. call."""
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("sdk.") or "sdk." in line:
            return line[:120]
    # Fallback: dòng đầu không phải comment/blank
    for line in code.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:120]
    return "(no action)"


def _summarize_outcome(result) -> str:
    """Tóm tắt 1 dòng outcome từ stdout."""
    if result.returncode != 0:
        first_err = (result.stderr or "").splitlines()[0] if result.stderr else "error"
        return f"FAILED: {first_err[:120]}"
    # Lấy dòng stdout cuối cùng có nội dung (thường là tóm tắt)
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
```

### 4.4 Node: OBSERVER

```python
# app/graph/nodes/observer.py

from ..state import AgentState
from pathlib import Path
import json

# Định nghĩa rõ ràng — không phải con số tùy tiện:
# coverage_score = verified_targets / total_targets (e.g. 18/20 vendor-year pairs đã có hit)
# confidence_score = mean(ExtractionResult.confidence) trên tất cả final records
COVERAGE_THRESHOLD = 0.9
CONFIDENCE_THRESHOLD = 0.8

async def observer_node(state: AgentState) -> AgentState:
    """
    Node OBSERVE: Evaluate coverage_score + confidence_score từ completion_signal.json.
    Score-based là primary stop mechanism. TASK_COMPLETE print là fallback.
    """
    state_dir = Path(state["state_dir"])

    coverage_score = state.get("coverage_score", 0.0)
    confidence_score = state.get("confidence_score", 0.0)
    is_complete = False
    results = state.get("results")

    # --- Primary: đọc completion_signal.json do model write ---
    signal_path = state_dir / "completion_signal.json"
    if signal_path.exists():
        try:
            signal = json.loads(signal_path.read_text())
            coverage_score = float(signal.get("coverage_score", 0.0))
            confidence_score = float(signal.get("confidence_score", 0.0))
            if coverage_score > COVERAGE_THRESHOLD and confidence_score > CONFIDENCE_THRESHOLD:
                is_complete = True
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # Malformed signal → tiếp tục vòng lặp, không crash

    # --- Fallback: TASK_COMPLETE print từ model ---
    if not is_complete:
        last_stdout = ""
        for turn in reversed(state.get("turns", [])):
            if turn.get("stdout"):
                last_stdout = turn["stdout"]
                break
        if "TASK_COMPLETE" in last_stdout:
            is_complete = True

    # --- Load final results nếu complete ---
    if is_complete:
        final_path = state_dir / "final_results.json"
        if final_path.exists():
            try:
                results = json.loads(final_path.read_text())
            except Exception:
                pass

    # --- Cập nhật coverage summary vào state cho working memory REASONER ---
    coverage_summary = state.get("last_coverage_summary")
    summary_path = state_dir / "coverage_summary.txt"
    if summary_path.exists():
        try:
            coverage_summary = summary_path.read_text()
        except Exception:
            pass

    # --- Determine stop reason ---
    if state["current_turn"] >= state["max_turns"]:
        is_complete = True
        stop_reason = "max_turns"
    elif is_complete:
        stop_reason = "success"
    else:
        stop_reason = None

    return {
        **state,
        "coverage_score": coverage_score,
        "confidence_score": confidence_score,
        "is_complete": is_complete,
        "stop_reason": stop_reason,
        "results": results,
        "last_coverage_summary": coverage_summary,
    }
```

### 4.5 Node: FINALIZER

```python
# app/graph/nodes/finalizer.py

from ..state import AgentState
from pathlib import Path
import json

async def finalizer_node(state: AgentState) -> AgentState:
    """
    Node cuối: Format output, tính metrics tổng hợp, cleanup.
    """
    # Load results nếu chưa có
    results = state.get("results")
    if not results:
        final_path = Path(state["state_dir"]) / "final_results.json"
        if final_path.exists():
            with open(final_path) as f:
                results = json.load(f)

    # Tính tổng metrics
    total_sdk_calls = sum(t["sdk_calls"] for t in state["turns"])

    return {
        **state,
        "results": results,
        "total_sdk_calls": total_sdk_calls,
        "is_complete": True,
        "stop_reason": state.get("stop_reason", "success"),
    }
```

---

## 5. Conditional Edge — Tiếp Tục Hay Kết Thúc?

```python
# app/graph/edges.py

from .state import AgentState
from .nodes.observer import COVERAGE_THRESHOLD, CONFIDENCE_THRESHOLD

def should_continue(state: AgentState) -> str:
    """
    Conditional edge sau OBSERVER.
    Stop conditions (ưu tiên theo thứ tự):
      1. Score-based: coverage_score > 0.9 AND confidence_score > 0.8 (primary)
      2. is_complete = True (bao gồm TASK_COMPLETE fallback và file-based)
      3. max_turns đạt
      4. 3 lần lỗi liên tiếp
    """
    # Score-based stop (P2 primary)
    if (state.get("coverage_score", 0.0) > COVERAGE_THRESHOLD
            and state.get("confidence_score", 0.0) > CONFIDENCE_THRESHOLD):
        return "finalizer"

    if state["is_complete"]:
        return "finalizer"

    if state["current_turn"] >= state["max_turns"]:
        return "finalizer"

    # Nếu execution bị lỗi quá nhiều lần liên tiếp → abort
    recent_turns = state["turns"][-3:]
    if len(recent_turns) >= 3:
        all_failed = all(t["returncode"] != 0 for t in recent_turns)
        if all_failed:
            return "finalizer"

    return "reasoner"  # Tiếp tục loop
```

---

## 6. Xây Dựng Graph

```python
# app/graph/builder.py

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from .state import AgentState
from .nodes.planner import planner_node
from .nodes.reasoner import reasoner_node
from .nodes.executor import executor_node
from .nodes.observer import observer_node
from .nodes.finalizer import finalizer_node
from .edges import should_continue


def build_sac_graph(checkpointer=None) -> StateGraph:
    """
    Xây dựng LangGraph StateGraph cho SaC ReAct loop.
    """
    graph = StateGraph(AgentState)

    # Thêm các nodes
    graph.add_node("planner",  planner_node)
    graph.add_node("reasoner", reasoner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("observer", observer_node)
    graph.add_node("finalizer", finalizer_node)

    # Entry point
    graph.set_entry_point("planner")

    # Edges cố định
    graph.add_edge("planner",  "reasoner")
    graph.add_edge("reasoner", "executor")
    graph.add_edge("executor", "observer")
    graph.add_edge("finalizer", END)

    # Conditional edge: observer → (reasoner | finalizer)
    graph.add_conditional_edges(
        "observer",
        should_continue,
        {
            "reasoner":  "reasoner",
            "finalizer": "finalizer",
        }
    )

    # Compile với checkpointer (PostgreSQL persistence)
    return graph.compile(checkpointer=checkpointer)


async def get_compiled_graph():
    """Factory function — dùng trong FastAPI dependency injection."""
    from app.db.session import get_pg_connection_string
    async with AsyncPostgresSaver.from_conn_string(
        get_pg_connection_string()
    ) as checkpointer:
        await checkpointer.setup()
        return build_sac_graph(checkpointer=checkpointer)
```

---

## 7. Tích Hợp Vào FastAPI

### 7.1 Sync endpoint (chờ kết quả)

```python
# app/api/routes/search.py

from fastapi import APIRouter, Depends
from app.graph.builder import get_compiled_graph
from app.graph.state import AgentState
import uuid

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("/")
async def run_search(request: SearchRequest):
    """
    Chạy SaC ReAct loop đồng bộ, chờ kết quả.
    Phù hợp cho tasks < 30 giây.
    """
    task_id = str(uuid.uuid4())
    graph = await get_compiled_graph()

    initial_state: AgentState = {
        "task_id": task_id,
        "directive": request.directive,
        "domain_context": request.context.get("domain_knowledge"),
        "constraints": request.context.get("constraints", []),
        "messages": [],
        "turns": [],
        "current_turn": 0,
        "max_turns": request.config.get("max_turns", 10),
        "state_dir": "",
        "state_files": [],
        # Working memory (P1)
        "turn_summaries": [],
        "last_coverage_summary": None,
        "last_error": None,
        # Scores (P2)
        "coverage_score": 0.0,
        "confidence_score": 0.0,
        "results": None,
        "is_complete": False,
        "stop_reason": None,
        "total_sdk_calls": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }

    # Config cho LangGraph checkpointing
    config = {"configurable": {"thread_id": task_id}}

    # Invoke graph — blocks cho đến khi END
    final_state = await graph.ainvoke(initial_state, config=config)

    return {
        "task_id": task_id,
        "status": "completed",
        "results": final_state["results"],
        "metadata": {
            "turns": final_state["current_turn"],
            "total_sdk_calls": final_state["total_sdk_calls"],
            "stop_reason": final_state["stop_reason"],
        }
    }
```

### 7.2 Streaming endpoint (real-time updates)

```python
@router.post("/stream")
async def stream_search(request: SearchRequest):
    """
    Stream từng bước của ReAct loop về client.
    Client nhận Server-Sent Events (SSE).
    """
    from fastapi.responses import StreamingResponse
    import json

    task_id = str(uuid.uuid4())
    graph = await get_compiled_graph()

    initial_state: AgentState = { ... }  # như trên
    config = {"configurable": {"thread_id": task_id}}

    async def event_generator():
        async for event in graph.astream_events(
            initial_state,
            config=config,
            version="v2"
        ):
            event_type = event["event"]
            node_name = event.get("name", "")

            # Emit khi một node bắt đầu
            if event_type == "on_chain_start" and node_name in [
                "reasoner", "executor", "observer"
            ]:
                yield f"data: {json.dumps({'type': 'node_start', 'node': node_name})}\n\n"

            # Emit khi executor xong — có execution result
            if event_type == "on_chain_end" and node_name == "executor":
                output = event.get("data", {}).get("output", {})
                yield f"data: {json.dumps({'type': 'turn_complete', 'turn': output.get('current_turn'), 'sdk_calls': output.get('total_sdk_calls')})}\n\n"

            # Emit final khi graph kết thúc
            if event_type == "on_chain_end" and node_name == "LangGraph":
                output = event.get("data", {}).get("output", {})
                yield f"data: {json.dumps({'type': 'complete', 'results': output.get('results'), 'stop_reason': output.get('stop_reason')})}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"}
    )
```

### 7.3 Async job endpoint (fire-and-forget)

```python
@router.post("/async")
async def submit_search(request: SearchRequest, background_tasks: BackgroundTasks):
    """
    Submit task, nhận task_id ngay, poll sau.
    Dùng cho long-running tasks (> 30 giây).
    """
    task_id = str(uuid.uuid4())

    # Lưu task vào DB với status pending
    await db.tasks.create(task_id=task_id, directive=request.directive)

    # Chạy background
    background_tasks.add_task(_run_graph_background, task_id, request)

    return {"task_id": task_id, "status": "pending"}


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    """Poll task status."""
    task = await db.tasks.get(task_id)
    if not task:
        raise HTTPException(404)

    # Lấy state từ LangGraph checkpointer
    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": task_id}}
    state = await graph.aget_state(config)

    return {
        "task_id": task_id,
        "status": task.status,
        "results": state.values.get("results") if state else None,
        "current_turn": state.values.get("current_turn", 0) if state else 0,
    }
```

---

## 8. Checkpoint Persistence — PostgreSQL

LangGraph's `AsyncPostgresSaver` tự động tạo bảng cần thiết.
Tuy nhiên, cần thêm migration để track ở app level:

```sql
-- migrations: task status tracking
CREATE TABLE sac_tasks (
    thread_id   VARCHAR(36) PRIMARY KEY,  -- = task_id = LangGraph thread_id
    directive   TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- LangGraph tự tạo các bảng này (qua checkpointer.setup()):
-- checkpoints          → full state snapshots
-- checkpoint_blobs     → large blobs (messages, results)
-- checkpoint_writes    → pending writes
```

---

## 9. Cấu Trúc Thư Mục (bổ sung vào project gốc)

```
sac-backend/
└── app/
    ├── graph/                         # ← THÊM MỚI
    │   ├── __init__.py
    │   ├── builder.py                 # build_sac_graph(), get_compiled_graph()
    │   ├── state.py                   # AgentState TypedDict
    │   ├── edges.py                   # should_continue() conditional edge
    │   └── nodes/
    │       ├── __init__.py
    │       ├── planner.py             # Init state (incl. working memory + score fields)
    │       ├── reasoner.py            # build_working_memory() → LLM call → generate code
    │       ├── executor.py            # AST validation → SandboxExecutor → TurnSummary
    │       ├── observer.py            # Score-based stop (primary) + TASK_COMPLETE (fallback)
    │       └── finalizer.py          # Format final output
    │
    └── api/
        └── routes/
            └── search.py              # Sync, stream, async endpoints
```

---

## 10. Dependencies

```toml
# pyproject.toml — thêm vào [dependencies]

[tool.poetry.dependencies]
python = "^3.11"

# LangGraph + LangChain
langgraph = "^0.2"
langgraph-checkpoint-postgres = "^0.1"
langchain-core = "^0.3"
langchain-anthropic = "^0.3"
langchain-openai = "^0.2"         # optional, nếu dùng GPT

# FastAPI stack
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.32"}
pydantic = "^2.9"
pydantic-settings = "^2.6"

# Database
sqlalchemy = {extras = ["asyncio"], version = "^2.0"}
asyncpg = "^0.30"
alembic = "^1.14"
psycopg = {extras = ["binary", "pool"], version = "^3.2"}  # cho LangGraph checkpointer

# Task queue
arq = "^0.26"

# HTTP client (SDK calls)
httpx = "^0.27"

# Redis
redis = {extras = ["hiredis"], version = "^5.1"}
```

---

## 11. Luồng Dữ Liệu Qua Graph (Ví Dụ CVE Task)

```
START
  │
  ▼
PLANNER
  • task_id = "abc-123"
  • state_dir = "/tmp/sac_states/abc-123/"
  • messages = [SystemMessage(sdk_docs), HumanMessage(directive)]
  │
  ▼
REASONER (Turn 1)
  • Đọc working memory: directive + turn 1/10 (không có turn_summaries nào)
  • Generate code: fan-out CVE queries cho 5 vendors × 3 years
  • messages += [AIMessage(code)]
  │
  ▼
EXECUTOR (Turn 1)
  • Chạy code trong sandbox
  • sdk.search.web_many(150 queries, concurrency=12)
  • Serialize → state_dir/seed_hits.json (1,200 hits)
  • stdout: "Collected 1,247 hits from 150 queries"
  • messages += [HumanMessage(observation)]
  │
  ▼
OBSERVER (Turn 1)
  • Không có completion_signal.json → coverage_score = 0.0
  • is_complete = False
  • Cập nhật last_coverage_summary từ coverage_summary.txt (nếu có)
  • current_turn = 1
  │
  ▼ (should_continue → "reasoner")
  │
REASONER (Turn 2)
  • Đọc working memory: turn_summaries[0] = "sdk.search.web_many(150 queries) → 1,247 hits collected"
  • last_coverage_summary: "Jenkins/Android/2025: 0 pages — sparse"
  • state_files: ["seed_hits.json"]
  • Generate code: summarize coverage → query_llm() → expanded queries
  • messages += [AIMessage(code)]
  │
  ▼
EXECUTOR (Turn 2)
  • Load seed_hits.json
  • query_llm() để lấy refined queries
  • sdk.search.web_many(expanded_queries)
  • Serialize → state_dir/expanded_hits.json
  │
  ▼
OBSERVER (Turn 2)
  • Không có completion_signal.json → coverage_score = 0.0
  • is_complete = False
  │
  ▼ (should_continue → "reasoner")
  │
REASONER (Turn 3)
  • Generate code: dedupe + llm.extract_many() + filter + finalize
  │
  ▼
EXECUTOR (Turn 3)
  • Load seed + expanded hits
  • sdk.dedupe_by_url() → 847 unique
  • sdk.llm.extract_many(schema={cve, vendor, fix_version, ...})
  • Filter: confidence > 0.75 AND version_bound_to_cve
  • Dedupe by CVE → 234 records
  • Write → state_dir/final_results.json
  • Write → state_dir/completion_signal.json
    {"coverage_score": 0.95, "confidence_score": 0.91, "reason": "234 CVE records verified"}
  • stdout: "234 CVE records written."
  │
  ▼
OBSERVER (Turn 3)
  • Đọc completion_signal.json → coverage_score=0.95 > 0.9, confidence_score=0.91 > 0.8
  • Primary score-based stop triggered
  • Load final_results.json → 234 records
  • is_complete = True, stop_reason = "success"
  │
  ▼ (should_continue → "finalizer")
  │
FINALIZER
  • results = 234 CVE records
  • total_sdk_calls = 312
  • total_turns = 3
  │
  ▼
END → Response về API
```

---

## 12. Lưu Ý Quan Trọng Khi Implement

### Thread ID = Task ID
LangGraph dùng `thread_id` để nhóm các checkpoint. Dùng `task_id` làm `thread_id` để đồng nhất giữa DB và LangGraph state.

```python
config = {"configurable": {"thread_id": task_id}}
```

### Message History Management
`add_messages` reducer **append-only** — messages tích lũy qua turns và được lưu đầy đủ vào LangGraph checkpoints (cần thiết cho persistence và replay). Tuy nhiên, REASONER **không đọc `state["messages"]` trực tiếp** — thay vào đó dùng `build_working_memory()` để tổng hợp một prompt compact O(1 turn) thay vì O(n turns).

Việc này tránh hoàn toàn context bloat mà không cần trim — messages vẫn nguyên vẹn trong checkpoint, chỉ là REASONER không nhìn vào.

```python
# KHÔNG dùng cách này nữa (trim_messages):
# trimmed = trim_messages(state["messages"], max_tokens=12000, ...)
# response = await llm.ainvoke(trimmed)

# DÙNG cách này (working memory):
working_memory = build_working_memory(state)   # compact, O(1)
messages = [SystemMessage(...), HumanMessage(content=working_memory)]
response = await llm.ainvoke(messages)
```

### Score-Based Stopping
OBSERVER đọc `completion_signal.json` mà model write vào `STATE_DIR`. File này cần có `coverage_score` và `confidence_score` — hai giá trị phải được define rõ trong SKILL.md để model không tự tiện đặt số:
- `coverage_score = verified_targets / total_targets` (e.g. 18/20 CVE vendor-year pairs)
- `confidence_score = mean(ExtractionResult.confidence)` của tất cả final records

`TASK_COMPLETE` print vẫn giữ lại làm fallback — nếu model không write signal file thì loop vẫn dừng được.

### Sandbox Security
Model-generated code phải qua **AST validation trước** khi chạm tới subprocess. `validate_code()` trong `app/core/sandbox.py` parse toàn bộ AST tree, reject nếu có import hoặc call nằm ngoài `ALLOWED_IMPORTS` / `BLOCKED_CALLS`. Không bao giờ dùng `exec()` trực tiếp trong process chính. Luôn dùng subprocess với:
- AST validation trước (returncode=2 nếu fail)
- `PYTHONPATH` giới hạn
- Không có network access ngoài SDK
- CPU/memory limits qua `resource` module hoặc Docker

### State Dir Cleanup
Sau khi task hoàn thành, schedule cleanup state dir để tránh disk bloat:

```python
# Sau FINALIZER, schedule background cleanup
import shutil
async def cleanup_state(state_dir: str, delay_seconds: int = 3600):
    await asyncio.sleep(delay_seconds)
    shutil.rmtree(state_dir, ignore_errors=True)
```
