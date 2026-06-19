import json
import logging
import uuid
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.config.settings import settings
from app.core.database import SessionLocal
from app.graph.state.agent_state import AgentState
from app.services.agent.memory_service import MemoryService
from app.shared.enums import MemoryType

logger = logging.getLogger(__name__)

async def extractor_node(state: AgentState) -> dict:
    """
    Node Extractor: Đánh giá các vòng thực thi để trích xuất các sự kiện vĩnh cửu,
    sở thích người dùng, và lưu chúng vào Bộ nhớ dài hạn (LTM).
    Chạy như giai đoạn cuối cùng của vòng lặp LangGraph trước END.
    """
    user_id = state.get("user_id")
    if not user_id:
        logger.info("Không tìm thấy user_id trong AgentState. Bỏ qua trích xuất bộ nhớ.")
        return {}

    turn_summaries = state.get("turn_summaries", [])
    if not turn_summaries:
        logger.info("Không có vòng thực thi nào được ghi lại. Bỏ qua trích xuất bộ nhớ.")
        return {}

    # 1. Biên dịch lịch sử tóm tắt cho ngữ cảnh LLM
    history_lines = []
    for ts in turn_summaries:
        history_lines.append(f"Turn {ts['turn']}:")
        history_lines.append(f"  Action: {ts['action']}")
        history_lines.append(f"  Outcome: {ts['outcome']}")
    history_text = "\n".join(history_lines)

    # 2. System prompt và hướng dẫn con người để trích xuất
    system_prompt = (
        "You are an AI Memory Extractor. Your role is to analyze the execution history of a "
        "Search-as-Code agent and extract permanent facts or user preferences that should be "
        "remembered for future, unrelated tasks.\n\n"
        "Guidelines:\n"
        "- Extract user coding style preferences (e.g. preferences for standard libraries, preferred variable patterns, naming conventions).\n"
        "- Extract structural environmental facts (e.g. server ports, local paths, credentials prefixes, configuration keys).\n"
        "- Do NOT extract temporary task results, ephemeral runtime values, or transient search hits (e.g., actual vulnerability lists or temporary bug outputs).\n"
        "- Respond ONLY with a valid JSON array of strings containing the memories. If nothing permanent is found, respond with []. Do not include markdown code block fences."
    )

    human_prompt = f"""
User ID: {user_id}
Original Directive: {state.get('directive', '')}

Execution History:
{history_text}

Extract any permanent facts or preferences as a JSON list of strings.
Example output format:
["User prefers using pure python urllib rather than third-party requests library.", "The development API endpoint is configured on port 8000."]
"""

    # 3. Gọi LLM để trích xuất bộ nhớ
    llm = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model=settings.CHAT_MODEL_NAME,
        temperature=0.0
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    extracted_memories: List[str] = []
    try:
        response = await llm.ainvoke(messages)
        content = (response.content or "").strip()
        # Xóa các markdown code fence vô tình
        clean_content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if clean_content:
            parsed = json.loads(clean_content)
            if isinstance(parsed, list):
                extracted_memories = [str(item) for item in parsed]
    except Exception as e:
        logger.error("Không thể trích xuất bộ nhớ bằng LLM: %s", str(e), exc_info=True)

    # 4. Lưu bộ nhớ đã trích xuất vào PostgreSQL & Qdrant
    if extracted_memories:
        logger.info("Đã trích xuất %d bộ nhớ mới cho người dùng %s", len(extracted_memories), user_id)
        db = SessionLocal()
        try:
            user_uuid = uuid.UUID(str(user_id))
            for memory_text in extracted_memories:
                await MemoryService.save_memory(
                    db=db,
                    user_id=user_uuid,
                    content=memory_text,
                    memory_type=MemoryType.FACT
                )
            db.commit()
        except Exception as e:
            logger.error("Không thể lưu bộ nhớ đã trích xuất vào cơ sở dữ liệu: %s", str(e), exc_info=True)
            db.rollback()
        finally:
            db.close()
    else:
        logger.info("Không có bộ nhớ mới nào được trích xuất cho người dùng %s", user_id)

    return {}
