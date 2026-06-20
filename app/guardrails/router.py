import re
import logging
import math
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

from app.config.settings import settings
from app.core.database import SessionLocal
from app.models.project import Project
from app.rag.embeddings.manager import EmbeddingManager
from app.core.qdrant import qdrant_manager

logger = logging.getLogger(__name__)

# Basic regex-based prompt injection/toxicity patterns
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:any|previous|the)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt\s*(?:disclosure|leak|show|print)", re.IGNORECASE),
    re.compile(r"override\s+(?:developer|system|filter)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"forget\s+(?:your\s+)?(?:rules|instructions)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a\s+helpful\s+assistant\s+without\s+restrictions", re.IGNORECASE),
]

def detect_prompt_injection(query: str) -> bool:
    """Check if query matches common prompt injection patterns."""
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(query):
            logger.warning("Prompt injection pattern detected: %s", pattern.pattern)
            return True
    return False

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)

async def check_query_relevance(query: str, project_files: List[str], project_id: Optional[str] = None) -> bool:
    """
    Production-grade hybrid relevance router.
    Returns:
        True if the query is in-scope or classification fails (fail-open).
        False if the query is out-of-scope or unsafe.
    """
    # 1. Safety Guard: Check Prompt Injection
    if detect_prompt_injection(query):
        logger.warning("Query rejected by safety guard (prompt injection suspicion). Query: '%s'", query)
        return False

    # Rule 0: If no files exist in project, any document query is out-of-scope
    if not project_files:
        logger.info("Project has no files. Routing query as out-of-scope.")
        return False

    q_clean = query.strip().lower()
    if not q_clean:
        return False
        
    # Standard greetings/thanks don't require full RAG retrieval
    if q_clean in {"hello", "hi", "hey", "thank you", "thanks", "bye", "goodbye", "chào", "cảm ơn"}:
        logger.info("Local filter caught general greeting/thanks. Routing as out-of-scope.")
        return False

    # 2. Compute semantic features (Max Chunk Similarity & Project Summary Similarity)
    max_doc_similarity = 0.0
    project_similarity = 0.0
    
    try:
        # Embed the query
        provider = EmbeddingManager.get_provider(async_mode=False)
        query_vector = provider.embed_text(query)
        
        # A. Query Qdrant for max chunk similarity
        query_filter = None
        if project_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="project_id",
                        match=MatchValue(value=str(project_id))
                    )
                ]
            )
            
        results = qdrant_manager.search_vectors(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            query_vector=query_vector,
            limit=1,
            score_threshold=0.0,
            query_filter=query_filter
        )
        if results:
            max_doc_similarity = float(results[0].get("score", 0.0))
            
        # B. Get Project Summary similarity
        if project_id:
            db = SessionLocal()
            try:
                project = db.query(Project).filter(Project.id == project_id).first()
                if project:
                    project_summary = f"{project.name}: {project.description or ''}"
                    project_vector = provider.embed_text(project_summary)
                    project_similarity = cosine_similarity(query_vector, project_vector)
            except Exception as e:
                logger.warning("Failed to fetch project for similarity check: %s", e)
            finally:
                db.close()
                
    except Exception as e:
        logger.warning("Failed to compute semantic similarity features: %s", e, exc_info=True)

    # 3. LLM-based classification with confidence score
    llm_oos = 1.0  # Default to out-of-scope score 1.0 if LLM fails
    
    try:
        llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model="gpt-4o-mini",
            temperature=0.0,
            max_tokens=20,
            request_timeout=2.0,
        )
        
        files_list = "\n".join(f"- {f}" for f in project_files)
        
        system_prompt = (
            "You are a fast query relevance classifier. Your task is to decide if the user's query "
            "is related to the uploaded project documents or is asking about topics likely to be "
            "found within them.\n"
            f"Here is the list of documents uploaded in this project:\n{files_list}\n\n"
            "Format your response exactly as one of these two options:\n"
            "- IN_SCOPE (confidence_score)\n"
            "- OUT_SCOPE (confidence_score)\n"
            "Where confidence_score is a decimal between 0.0 and 1.0. Example: OUT_SCOPE (0.95)"
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"User Query: {query}")
        ]
        
        response = await llm.ainvoke(messages)
        result_text = (response.content or "").strip()
        
        # Parse output like OUT_SCOPE (0.95)
        match = re.search(r"(IN_SCOPE|OUT_SCOPE)\s*\(\s*([0-9\.]+)\s*\)", result_text, re.IGNORECASE)
        if match:
            label = match.group(1).upper()
            conf = float(match.group(2))
            if label == "IN_SCOPE":
                llm_oos = 1.0 - conf
            else:
                llm_oos = conf
        else:
            # Fallback if parsing fails
            if "IN_SCOPE" in result_text.upper():
                llm_oos = 0.1
            elif "OUT_SCOPE" in result_text.upper():
                llm_oos = 0.9
                
    except Exception as e:
        logger.warning("LLM-based classifier query relevance check failed: %s", e, exc_info=True)
        # Fail-open: if LLM fails, we set llm_oos low so we don't accidentally reject
        llm_oos = 0.0

    # 4. Compute hybrid OOS score
    # Formula: final_score = 0.4 * llm_oos + 0.3 * (1.0 - max_doc_similarity) + 0.3 * (1.0 - project_similarity)
    final_oos_score = (
        0.4 * llm_oos + 
        0.3 * (1.0 - max_doc_similarity) + 
        0.3 * (1.0 - project_similarity)
    )
    
    logger.info(
        "Hybrid Router: LLM_OOS=%.2f, Max_Doc_Sim=%.2f, Proj_Sim=%.2f -> Final_OOS=%.2f (Query: '%s')",
        llm_oos, max_doc_similarity, project_similarity, final_oos_score, query
    )
    
    # Reject ONLY if OOS confidence is extremely high (> 0.95)
    if final_oos_score > 0.95:
        logger.info("Query rejected by hybrid router (final score %.2f > 0.95)", final_oos_score)
        return False
        
    return True
