import re
import logging
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from app.config.settings import settings
from app.graph.state.agent_state import AgentState

logger = logging.getLogger(__name__)

def build_working_memory(state: AgentState) -> str:
    """
    Biên dịch tóm tắt ngắn gọn của trạng thái thực thi hiện tại.
    Ngăn chặn phình token bằng cách thay thế các bản ghi stdout/stderr đầy đủ
    bằng các tóm tắt hành động-kết quả và danh sách các file trạng thái có sẵn.
    """
    current_turn = state.get("current_turn", 0)
    max_turns = state.get("max_turns", 10)
    constraints = state.get("constraints", [])
    turn_summaries = state.get("turn_summaries", [])
    state_files = state.get("state_files", [])
    last_error = state.get("last_error")

    memory_lines = [
        f"--- WORKING MEMORY (Turn {current_turn + 1}/{max_turns}) ---",
        f"Original User Directive: {state.get('directive', '')}",
    ]

    if constraints:
        memory_lines.append("Constraints:")
        for c in constraints:
            memory_lines.append(f"  - {c}")

    if turn_summaries:
        memory_lines.append("\nPrevious Turns History:")
        for ts in turn_summaries:
            memory_lines.append(f"  Turn {ts['turn']}:")
            memory_lines.append(f"    Action: {ts['action']}")
            memory_lines.append(f"    Outcome: {ts['outcome']}")
    else:
        memory_lines.append("\nNo previous turns executed yet. This is Turn 1.")

    memory_lines.append(f"\nFiles currently in workspace (STATE_DIR): {state_files}")
    memory_lines.append("To access the contents of these files, write Python code to load them (using pathlib and json).")

    if last_error:
        memory_lines.append(f"\n[WARNING] Last execution encountered an error:")
        memory_lines.append(f"  {last_error}")

    memory_lines.append(
        "\nBased on this history, write the next Python code block to execute.\n"
        "Remember to wrap your Python code in a ```python ... ``` block, "
        "and serialize any new outputs/data into STATE_DIR."
    )

    return "\n".join(memory_lines)


def _extract_code_block(text: str) -> Optional[str]:
    """
    Trích xuất code Python từ Markdown code fences.
    Hỗ trợ ```python ... ``` và dự phòng ``` ... ```.
    """
    pattern = r"```python\s+(.*?)\s+```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    pattern_fallback = r"```\s+(.*?)\s+```"
    match_fallback = re.search(pattern_fallback, text, re.DOTALL)
    if match_fallback:
        return match_fallback.group(1).strip()

    return None


async def reasoner_node(state: AgentState) -> dict:
    """
    Node Reasoner: Node tư duy nhận thức của agent SaC.
    Tạo bộ nhớ làm việc ngắn gọn, gọi LLM, trích xuất code Python
    từ phản hồi, và lưu nó vào `_pending_code` cho Executor.
    """
    # 1. Lấy SystemMessage chứa các quy tắc SDK SaC
    # Nó nên là tin nhắn đầu tiên trong lịch sử được khởi tạo bởi Planner
    system_message = None
    for msg in state.get("messages", []):
        if isinstance(msg, SystemMessage):
            system_message = msg
            break

    if not system_message:
        raise ValueError("Không tìm thấy SystemMessage trong state['messages']. Node Planner đã chạy chưa?")

    # 2. Biên dịch prompt bộ nhớ làm việc ngắn gọn
    working_memory = build_working_memory(state)

    # 3. Khởi tạo mô hình ChatOpenAI
    llm = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model=settings.CHAT_MODEL_NAME,
        temperature=0.0
    )

    # 4. Gọi LLM chỉ với system prompt và bộ nhớ làm việc
    # Điều này giữ cửa sổ ngữ cảnh nhỏ và ngăn chặn phình token.
    messages_payload = [
        system_message,
        HumanMessage(content=working_memory)
    ]

    try:
        response = await llm.ainvoke(messages_payload)
        response_text = response.content or ""
    except Exception as e:
        response_text = f"LLM error: {str(e)}"
        logger.error("Lỗi khi gọi mô hình ChatOpenAI: %s", str(e), exc_info=True)

    # 5. Trích xuất code block
    code = _extract_code_block(response_text)

    # 6. Xây dựng AIMessage để ghi log lịch sử
    ai_message = AIMessage(content=response_text)

    return {
        "_pending_code": code,
        "messages": [ai_message],
    }
