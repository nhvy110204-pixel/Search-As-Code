import tempfile
import logging
import uuid
from pathlib import Path
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage
from app.graph.state.agent_state import AgentState
from app.core.database import SessionLocal
from app.services.agent.memory_service import MemoryService

logger = logging.getLogger(__name__)

async def planner_node(state: AgentState) -> dict:
    """
    Planner Node: Entry point of the Search-as-Code execution graph.
    Initializes execution variables, prepares the local workspace directory,
    and sets up system prompts with available SDK primitive instructions.
    """
    # 1. Ensure/Generate state_dir for the task
    task_id = state.get("task_id")
    if not task_id:
        raise ValueError("task_id is required in AgentState")

    # Use a system-independent temporary directory for cross-platform support
    state_dir_path = Path(tempfile.gettempdir()) / "sac_states" / str(task_id)
    state_dir_path.mkdir(parents=True, exist_ok=True)
    state_dir = str(state_dir_path)

    # 2. Compile standard system instructions detailing the SaC SDK primitives
    system_prompt = (
        "You are a Search-as-Code (SaC) Agent executor. Your goal is to solve the user's directive "
        "by writing structured Python scripts that make use of the provided `sdk` primitives.\n\n"
        "### Available SDK Primitives:\n"
        "You can import `sdk` using:\n"
        "```python\n"
        "from app.sdk import sdk\n"
        "```\n\n"
        "Here are the methods available on the `sdk` object:\n"
        "1. High-Level Search:\n"
        "   - `await sdk.search.web_many(queries: List[Dict], limit_per_query: int = 8, concurrency: int = 12) -> List[List[SearchHit]]` (execute multiple search queries in parallel. Example of query: `{'query': 'search term'}`)\n"
        "   - `await sdk.search.deep_search(query: str, depth: int = 3, strategy: str = 'breadth_first') -> List[SearchHit]` (multi-hop iterative search)\n"
        "2. High-Level LLM:\n"
        "   - `await sdk.llm.extract_many(items: List[Dict], instruction: str, schema: Dict[str, Any], concurrency: int = 5) -> List[Dict]` (parallel structured extraction)\n"
        "   - `await sdk.llm.query_llm(prompt: str) -> str` (single LLM reasoning query)\n"
        "   - `sdk.llm.parse_jsonl(text: str) -> list` (parse JSONL from LLM output)\n"
        "3. Low-Level Database/Vector Primitives:\n"
        "   - `await sdk.retrieve(query: str, source: str = 'web', limit: int = 10, **kwargs) -> List[SearchHit]`\n"
        "   - `await sdk.fanout(queries: List[str], source: str = 'web', limit_per_query: int = 5) -> List[List[SearchHit]]`\n"
        "   - `sdk.rank(hits: List[SearchHit], query: str, top_n: int = 5) -> List[SearchHit]`\n"
        "   - `sdk.dedupe(hits: List[SearchHit]) -> List[SearchHit]`\n"
        "   - `await sdk.embed(texts: List[str]) -> List[List[float]]`\n"
        "   - `sdk.cluster(hits: List[SearchHit], num_clusters: int = 3) -> Dict[int, List[SearchHit]]`\n"
        "   - `sdk.chunk(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]`\n"
        "   - `sdk.parse_field(hits: List[SearchHit], field: str) -> List[str]`\n"
        "4. Utilities:\n"
        "   - `sdk.join_result_fields(hits: List[SearchHit], field: str = 'content', separator: str = '\\n') -> str`\n"
        "   - `sdk.flatten(list_of_lists: List[List[Any]]) -> List[Any]`\n"
        "   - `sdk.unique(items: List[Any]) -> List[Any]`\n"
        "   - `sdk.summarize(texts: List[str], max_words: int = 100) -> str`\n"
        "   - `sdk.infer_vendor(text: str) -> str`\n"
        "   - `sdk.official_vendor_advisory(vendor: str) -> str`\n\n"
        "### Types:\n"
        "All hits are `SearchHit` instances with fields: `id`, `title`, `content`, `url`, `score`, and `metadata`.\n\n"
        "### Sandbox Rules & Workspace Isolation:\n"
        "- The workspace path is exposed in the environment variable `STATE_DIR`.\n"
        "- All intermediate results MUST be serialized to the workspace as JSON files inside `STATE_DIR`. "
        "You must load prior JSONs and write updated JSONs there. DO NOT use raw `open` function. Instead, "
        "read/write using `Path(os.environ['STATE_DIR']) / 'filename.json'` via the allowed `pathlib` and `json` modules.\n"
        "- Code execution is sandbox-validated. Bare `open`, `eval`, `exec`, `os`, `sys`, and `subprocess` imports are BLOCKED. "
        "You must ONLY write Python code that imports allowed modules: `json`, `re`, `math`, `datetime`, `collections`, `itertools`, "
        "`functools`, `pathlib`, `typing`, `asyncio`, and `app.sdk`.\n"
        "- Ensure you write code inside standard Python markdown fences like:\n"
        "```python\n"
        "# Your code here\n"
        "```\n\n"
        "Think step-by-step. Break the problem into incremental turns. "
        "At each turn, execute code, observe results from the output files in `STATE_DIR`, and refine your strategy."
    )

    # 3. Recall Long-Term Memories (LTM) based on User Directive
    directive = state.get("directive", "")
    domain_context = state.get("domain_context", "")
    constraints = state.get("constraints", [])
    user_id = state.get("user_id")
    recalled_memories = []
    db = SessionLocal()
    try:
        user_uuid = uuid.UUID(str(user_id)) if user_id else uuid.UUID("00000000-0000-0000-0000-000000000000")
        recalled_memories = await MemoryService.recall_memories(
            db=db,
            user_id=user_uuid,
            query=directive,
            limit=3
        )
    except Exception as e:
        logger.warning("Failed to recall long-term memories: %s", str(e), exc_info=True)
    finally:
        db.close()

    # 4. Compile Human directive message
    human_prompt = f"Directive: {directive}\n"
    if domain_context:
        human_prompt += f"Domain Context: {domain_context}\n"
    if constraints:
        human_prompt += "Constraints:\n" + "\n".join(f"- {c}" for c in constraints) + "\n"
    
    # Inject LTM into human prompt context if found
    if recalled_memories:
        human_prompt += "\n### Relevant User Preferences & Past Facts (Long-Term Memory):\n"
        for m in recalled_memories:
            human_prompt += f"- {m}\n"

    # 5. Construct messages payload
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    # Return state updates
    return {
        "turns": state.get("turns") or [],
        "current_turn": 0,
        "max_turns": state.get("max_turns") or 10,
        "state_dir": state_dir,
        "state_files": state.get("state_files") or [],
        "turn_summaries": state.get("turn_summaries") or [],
        "coverage_score": state.get("coverage_score") or 0.0,
        "confidence_score": state.get("confidence_score") or 0.0,
        "total_sdk_calls": state.get("total_sdk_calls") or 0,
        "total_tokens": state.get("total_tokens") or 0,
        "cost_usd": state.get("cost_usd") or 0.0,
        "is_complete": state.get("is_complete") or False,
        "_pending_code": None,
        "messages": messages,
        "user_id": str(user_id) if user_id else None
    }
