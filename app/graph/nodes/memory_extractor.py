import json
import logging
import uuid
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.core.llm_factory import get_llm_client
from app.config.settings import settings
from app.core.database import SessionLocal
from app.graph.state.agent_state import AgentState
from app.services.agent.memory_service import MemoryService
from app.shared.enums import MemoryType

logger = logging.getLogger(__name__)

async def memory_extractor_node(state: AgentState, config: dict = None) -> dict:
    """
    Memory Extractor Node: Analyzes the execution turns history to extract
    permanent facts and user preferences, then stores them in LTM.
    Runs as the final stage of the LangGraph execution loop before END.
    """
    user_id = state.get("user_id")
    if not user_id:
        logger.info("No user_id found in AgentState. Skipping memory extraction.")
        return {}

    turn_summaries = state.get("turn_summaries", [])
    if not turn_summaries:
        logger.info("No execution turns recorded. Skipping memory extraction.")
        return {}

    # 1. Compile summary history for LLM context
    history_lines = []
    for ts in turn_summaries:
        history_lines.append(f"Turn {ts['turn']}:")
        history_lines.append(f"  Action: {ts['action']}")
        history_lines.append(f"  Outcome: {ts['outcome']}")
    history_text = "\n".join(history_lines)

    # 2. System prompt and human instructions for extraction
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

    # 3. Call LLM to extract memories
    llm = get_llm_client(config, streaming=False)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    extracted_memories: List[str] = []
    try:
        response = await llm.ainvoke(messages)
        content = (response.content or "").strip()
        # Clean any accidental markdown fences
        clean_content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if clean_content:
            parsed = json.loads(clean_content)
            if isinstance(parsed, list):
                extracted_memories = [str(item) for item in parsed]
    except Exception as e:
        logger.error("Failed to extract memory via LLM: %s", str(e), exc_info=True)

    # 4. Save extracted memories to PostgreSQL & Qdrant
    if extracted_memories:
        logger.info("Extracted %d new memories for user %s", len(extracted_memories), user_id)
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
            logger.error("Failed to save extracted memories to DB: %s", str(e), exc_info=True)
            db.rollback()
        finally:
            db.close()
    else:
        logger.info("No new memories extracted for user %s", user_id)

    return {}
