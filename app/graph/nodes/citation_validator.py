import re
import json
import logging
from pathlib import Path
from app.graph.state.agent_state import AgentState
from app.shared.enums import StopReason

logger = logging.getLogger(__name__)

async def citation_validator_node(state: AgentState) -> dict:
    """
    Citation Validator Node: Verifies that all citations in the final answer
    refer to valid retrieved evidence chunks. Updates state retry counter and
    unverified claims, delegating text generation to the finalizer.
    """
    final_answer = state.get("final_answer", "") or ""
    state_dir = state.get("state_dir")
    stop_reason = state.get("stop_reason")
    
    # 1. Skip if already in a failure/terminal state
    refusal_reasons = {
        StopReason.INSUFFICIENT_EVIDENCE,
        StopReason.STAGNATED,
        StopReason.REPEATED_TOOL_FAILURES,
        StopReason.CITATION_VALIDATION_FAILED,
        StopReason.MAX_TURNS_REACHED
    }
    if stop_reason in refusal_reasons:
        return {
            "unverified_claims": None
        }

    # 2. Extract citations like [1], [2] from text
    citations = re.findall(r"\[([0-9]+)\]", final_answer)
    if not citations:
        logger.info("No citation markers found in final answer.")
        return {
            "unverified_claims": None
        }

    # 3. Read final results to verify indices
    evidence_hits = []
    if state_dir:
        results_file = Path(state_dir) / "final_results.json"
        if results_file.exists():
            try:
                results_data = json.loads(results_file.read_text())
                evidence_hits = results_data.get("evidence", [])
            except Exception as e:
                logger.error("Failed to read final_results.json: %s", e)

    # 4. Perform deterministic validation
    evidence_len = len(evidence_hits)
    invalid_indices = []
    
    for cit in citations:
        idx = int(cit)
        if idx <= 0 or idx > evidence_len:
            logger.warning("Unverified citation index detected: [%d] (Total evidence chunks: %d)", idx, evidence_len)
            invalid_indices.append(cit)
            
    # 5. Update state and handle retries
    if invalid_indices:
        retry_count = state.get("citation_retry_counter", 0) + 1
        logger.warning(
            "Fabricated/unverified citation indices found: %s. Incrementing citation_retry_counter to %d.",
            invalid_indices, retry_count
        )
        
        target_stop_reason = stop_reason
        if retry_count >= 2:
            logger.warning("Max citation retry attempts reached. Mark stop reason as CITATION_VALIDATION_FAILED.")
            target_stop_reason = StopReason.CITATION_VALIDATION_FAILED
            
        return {
            "unverified_claims": invalid_indices,
            "citation_retry_counter": retry_count,
            "stop_reason": target_stop_reason
        }
        
    logger.info("All citations successfully verified by citation validator.")
    return {
        "unverified_claims": None
    }
