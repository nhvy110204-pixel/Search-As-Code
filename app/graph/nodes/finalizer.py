import json
import logging
import uuid
from typing import Optional
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.config.settings import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.graph.state.agent_state import AgentState
from app.shared.enums import StopReason
from app.guardrails.alignment import build_proactive_refusal
from app.core.llm_factory import get_llm_client

logger = logging.getLogger(__name__)

async def finalizer_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """
    Finalizer Node: Generates the final grounded answer with citations,
    handles self-correction loops for invalid citations, or falls back to
    a proactive refusal listing project files if evidence is insufficient or citation fails.
    """
    project_id = state.get("project_id")
    state_dir = state.get("state_dir")
    stop_reason = state.get("stop_reason")
    directive = state.get("directive", "")
    unverified_claims = state.get("unverified_claims")
    
    # 1. Fetch available project files for refusal guidance
    project_files = []
    if project_id:
        from app.services.core.redis_service import redis_cache_service
        cache_key = f"project:{project_id}:documents_metadata"
        cache_hit = False
        
        try:
            r = redis_cache_service.redis
            if r:
                data = r.get(cache_key)
                if data is not None:
                    cached_docs = json.loads(data)
                    project_files = [doc["file_name"] for doc in cached_docs]
                    cache_hit = True
                    logger.info(f"Cache HIT for project documents metadata: project_id={project_id}, count={len(project_files)}")
        except Exception as e:
            logger.warning(f"Failed to check/read project documents metadata cache: {e}")
            
        if not cache_hit:
            db = SessionLocal()
            try:
                docs = db.query(Document).filter(
                    Document.project_id == uuid.UUID(project_id),
                    Document.is_deleted.is_(False)
                ).all()
                
                cached_metadata = []
                for d in docs:
                    status_val = d.status.value if hasattr(d.status, "value") else str(d.status)
                    summary_val = d.processing_metadata.get("global_summary") if d.processing_metadata else None
                    cached_metadata.append({
                        "id": str(d.id),
                        "file_name": d.file_name,
                        "description": d.description,
                        "status": status_val,
                        "chunk_count": d.chunk_count,
                        "global_summary": summary_val,
                        "created_at": d.created_at.isoformat() if d.created_at else None
                    })
                
                project_files = [doc["file_name"] for doc in cached_metadata]
                logger.info(f"Cache MISS for project documents metadata: project_id={project_id}, queried {len(project_files)} from DB")
                
                # Write to Redis
                r = redis_cache_service.redis
                if r:
                    r.setex(cache_key, 3600, json.dumps(cached_metadata))
                    logger.info(f"Cached project documents metadata for project_id={project_id}")
            except Exception as e:
                logger.error("Failed to query/cache project files in finalizer: %s", e)
            finally:
                db.close()
            
    # 2. Check if we need to fail-fast with a refusal
    refusal_reasons = {
        StopReason.INSUFFICIENT_EVIDENCE,
        StopReason.STAGNATED,
        StopReason.REPEATED_TOOL_FAILURES,
        StopReason.MAX_TURNS_REACHED,
        StopReason.CITATION_VALIDATION_FAILED
    }
    
    if stop_reason in refusal_reasons:
        logger.info("Finalizer triggering proactive refusal due to stop_reason: %s", stop_reason)
        refusal_msg = build_proactive_refusal(project_files)
        return {
            "final_answer": refusal_msg,
            "results": [refusal_msg]
        }
        
    # 3. Read final evidence
    evidence_hits = []
    if state_dir:
        results_file = Path(state_dir) / "final_results.json"
        if results_file.exists():
            try:
                results_data = json.loads(results_file.read_text())
                evidence_hits = results_data.get("evidence", [])
            except Exception as e:
                logger.error("Failed to read final_results.json: %s", e)
                
    if not evidence_hits:
        logger.warning("No evidence found in final_results.json. Falling back to refusal.")
        refusal_msg = build_proactive_refusal(project_files)
        return {
            "final_answer": refusal_msg,
            "results": [refusal_msg],
            "stop_reason": StopReason.INSUFFICIENT_EVIDENCE
        }
        
    # 4. Compile evidence string for LLM
    evidence_str = ""
    for i, hit in enumerate(evidence_hits, 1):
        title = hit.get("title", "Document")
        content = hit.get("content", "")
        page = hit.get("metadata", {}).get("page_number", "N/A")
        evidence_str += f"[{i}] Source: {title} (Page: {page})\nContent: {content}\n\n"
        
    # 5. Generate or correct grounded answer via LLM
    try:
        llm = get_llm_client(config, streaming=True)
        
        # Self-correction check: if unverified_claims exist, we prompt for correction
        if unverified_claims:
            logger.info("Finalizer running in citation self-correction path. Unverified claims: %s", unverified_claims)
            system_prompt = (
                "You are a helpful assistant. You previously generated an answer to the user's question, "
                "but it contained invalid/fabricated citation markers that do NOT match the provided evidence.\n"
                "Your task is to rewrite the answer. Ensure that EVERY factual claim has a valid citation from "
                "the list below (e.g. [1], [2]). Do NOT use or fabricate any other citations. Do NOT cite sources "
                "that do not support the claim."
            )
            human_prompt = (
                f"User's Question: {directive}\n\n"
                f"Your previous draft (with invalid citations): {state.get('final_answer')}\n\n"
                f"The following citation markers were detected as invalid/unsupported: {unverified_claims}\n\n"
                f"Here is the valid Retrieved Evidence you MUST use:\n{evidence_str}"
            )
        else:
            system_prompt = (
                "You are a helpful assistant. Generate a clear answer to the user's question "
                "based ONLY on the provided evidence. Cite sources using markdown format like [1], [2]. "
                "Every factual claim must include a citation. Do not mention or use any other external facts "
                "not found in the evidence."
            )
            human_prompt = (
                f"Question: {directive}\n\n"
                f"Retrieved Evidence:\n{evidence_str}"
            )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        final_answer = response.content or ""
        
        logger.info("Grounded answer successfully generated by finalizer.")
        return {
            "final_answer": final_answer,
            "results": [final_answer]
        }
        
    except Exception as e:
        logger.error("Failed to generate grounded answer in finalizer: %s", e, exc_info=True)
        refusal_msg = build_proactive_refusal(project_files)
        return {
            "final_answer": refusal_msg,
            "results": [refusal_msg],
            "stop_reason": StopReason.INTERNAL_ERROR
        }
