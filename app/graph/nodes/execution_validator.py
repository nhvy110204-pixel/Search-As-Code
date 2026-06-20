import json
import logging
from pathlib import Path
from app.graph.state.agent_state import AgentState
from app.shared.enums import StopReason

logger = logging.getLogger(__name__)

async def execution_validator_node(state: AgentState) -> dict:
    """
    Execution Validator Node: Analyzes the search hits and completion signal for successful executions.
    Updates the state with evidence_count, retrieval_score, coverage_score, and confidence_score.
    Calculates the stagnation counter by checking if coverage has improved.
    Decides if execution should stop early due to poor search results (after 2 tries).
    """
    current_turn = state.get("current_turn", 0)
    turns = state.get("turns", [])
    
    # 1. If sandbox code execution failed, bypass metric checking and pass through.
    if turns and turns[-1].get("returncode", 0) != 0:
        logger.info("Sandbox execution failed in Turn %d. Bypassing metric checks.", current_turn)
        return {}

    # 2. If the Reasoner did not propose any code, it wants to finalize the graph run.
    if turns and not turns[-1].get("generated_code"):
        logger.info("Reasoner did not propose code in Turn %d. Finalizing graph execution.", current_turn)
        return {
            "is_complete": True,
            "stop_reason": state.get("stop_reason") or StopReason.COMPLETED
        }

    state_dir = state.get("state_dir")
    low_retrieval_counter = state.get("low_retrieval_counter", 0)
    stagnation_counter = state.get("stagnation_counter", 0)
    
    evidence_count = 0
    retrieval_score = 0.0
    old_coverage = state.get("coverage_score", 0.0)
    coverage_score = old_coverage
    confidence_score = state.get("confidence_score", 0.0)
    is_complete = state.get("is_complete", False)
    stop_reason = state.get("stop_reason")
    
    if state_dir:
        state_dir_path = Path(state_dir)
        
        # 3. Read retrieved hits for current turn
        hits_file = state_dir_path / f"retrieved_hits_turn_{current_turn}.json"
        if hits_file.exists():
            try:
                hits = json.loads(hits_file.read_text())
                if isinstance(hits, list):
                    evidence_count = len(hits)
                    if evidence_count > 0:
                        retrieval_score = sum(float(h.get("score", 0.0)) for h in hits) / evidence_count
            except Exception as e:
                logger.error("Failed to read retrieved hits file: %s", e)
                
        # 4. Read model completion signal if available
        completion_file = state_dir_path / "completion_signal.json"
        if completion_file.exists():
            try:
                signal = json.loads(completion_file.read_text())
                coverage_score = float(signal.get("coverage_score", old_coverage))
                confidence_score = float(signal.get("confidence_score", confidence_score))
                if "is_complete" in signal:
                    is_complete = bool(signal["is_complete"])
            except Exception as e:
                logger.error("Failed to read completion_signal.json: %s", e)
                
    # 5. Calculate stagnation: if coverage did not improve compared to previous turn
    if current_turn > 1:
        if coverage_score <= old_coverage:
            stagnation_counter += 1
            logger.info(
                "Stagnation detected: coverage did not improve (%.2f <= %.2f). Counter: %d",
                coverage_score, old_coverage, stagnation_counter
            )
        else:
            stagnation_counter = 0
            
    logger.info(
        "Execution Validator (Turn %d): evidence_count=%d, retrieval_score=%.2f, coverage=%.2f, confidence=%.2f, stagnation=%d",
        current_turn, evidence_count, retrieval_score, coverage_score, confidence_score, stagnation_counter
    )
    
    # 6. Check retrieval score stop conditions ONLY if retrieval SDK operations actually occurred in this turn
    has_sdk_calls = turns[-1].get("sdk_calls", 0) > 0 if turns else False
    
    if has_sdk_calls:
        if evidence_count == 0:
            logger.warning("No search hits found. Aborting early.")
            is_complete = True
            stop_reason = StopReason.INSUFFICIENT_EVIDENCE
        elif retrieval_score < 0.25:
            low_retrieval_counter += 1
            logger.warning(
                "Low retrieval score (%.2f < 0.25). low_retrieval_counter=%d",
                retrieval_score, low_retrieval_counter
            )
            if low_retrieval_counter >= 2:
                logger.warning("Repeated low retrieval scores. Aborting early.")
                is_complete = True
                stop_reason = StopReason.INSUFFICIENT_EVIDENCE
            
    return {
        "evidence_count": evidence_count,
        "retrieval_score": retrieval_score,
        "coverage_score": coverage_score,
        "confidence_score": confidence_score,
        "low_retrieval_counter": low_retrieval_counter,
        "stagnation_counter": stagnation_counter,
        "is_complete": is_complete,
        "stop_reason": stop_reason
    }
