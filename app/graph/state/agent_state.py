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
    state_files: List[str]   # files serialized to filesystem
    action_summary: str      # 1 line summary of action (for working memory)
    outcome_summary: str     # 1 line summary of outcome (for working memory)

class TurnSummary(TypedDict):
    """Compact summary of a turn — only keeps action + outcome for working memory."""
    turn: int
    action: str
    outcome: str

class AgentState(TypedDict):
    # --- Task context ---
    task_id: str
    directive: str                          # Original task directive
    domain_context: Optional[str]           # Domain knowledge
    constraints: List[str]                  # Task constraints

    # --- Conversation history ---
    messages: Annotated[List[BaseMessage], add_messages]

    # --- Execution state ---
    turns: Annotated[List[TurnRecord], operator.add]  # Append-only
    current_turn: int
    max_turns: int                          # Hard limit (default: 10)

    # --- Sandbox state ---
    state_dir: str                          # Path to filesystem state directory
    state_files: List[str]                  # Files in state_dir

    # --- Working memory ---
    turn_summaries: List[TurnSummary]       # Compact summaries from EXECUTOR
    last_coverage_summary: Optional[str]    # OBSERVER updates (sdk.summarize output)
    last_error: Optional[str]               # EXECUTOR writes when returncode != 0

    # --- Score-based stopping ---
    coverage_score: float                   # verified_targets / total_targets (0.0–1.0)
    confidence_score: float                 # mean confidence score (0.0–1.0)

    # --- Results ---
    results: Optional[List[Any]]            # Final results
    is_complete: bool
    stop_reason: Optional[str]              # "success" | "max_turns" | "error"

    # --- Metrics ---
    total_sdk_calls: int
    total_tokens: int
    cost_usd: float

    # --- Control flags ---
    _pending_code: Optional[str]            # Passes code from REASONER to EXECUTOR
