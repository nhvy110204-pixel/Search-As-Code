import logging
from app.graph.state.agent_state import AgentState
from app.shared.enums import StopReason

logger = logging.getLogger(__name__)

async def observer_node(state: AgentState) -> dict:
    """
    Observer Node: Evidence Validator & Turn Monitor.
    Decides whether the agent loop is complete or needs to stop due to limits,
    stagnation, repeated failures, or sufficient progress.
    """
    is_complete = state.get("is_complete", False)
    stop_reason = state.get("stop_reason")
    
    current_turn = state.get("current_turn", 0)
    max_turns = state.get("max_turns", 10)
    
    coverage_score = state.get("coverage_score", 0.0)
    confidence_score = state.get("confidence_score", 0.0)
    stagnation_counter = state.get("stagnation_counter", 0)
    turns = state.get("turns", [])
    
    # 1. Target Met: Check if we have gathered sufficient evidence
    if coverage_score >= 0.90 and confidence_score >= 0.80:
        if not is_complete:
            logger.info("Target metadata criteria met (coverage >= 0.90 and confidence >= 0.80). Completing.")
            is_complete = True
            stop_reason = StopReason.COMPLETED

    # 2. Repeated Execution Failures: Check if the last 3 turns failed in the sandbox
    if len(turns) >= 3 and all(t.get("returncode", 0) != 0 for t in turns[-3:]):
        logger.warning("Observer detected 3 consecutive sandbox execution failures. Aborting.")
        is_complete = True
        stop_reason = StopReason.REPEATED_TOOL_FAILURES

    # 3. Stagnation: Check if agent is looping without progress
    if stagnation_counter >= 3:
        logger.warning("Observer detected stagnation (no coverage improvement for 3 turns). Aborting.")
        is_complete = True
        stop_reason = StopReason.STAGNATED

    # 4. Hard turn limit reached
    if current_turn >= max_turns and not is_complete:
        logger.warning("Max turns limit (%d) reached.", max_turns)
        is_complete = True
        if coverage_score >= 0.90 and confidence_score >= 0.80:
            stop_reason = StopReason.COMPLETED
        else:
            # Fallback to insufficient evidence refusal if score is sub-optimal at max turns
            stop_reason = StopReason.INSUFFICIENT_EVIDENCE

    logger.info(
        "Observer Node: is_complete=%s, stop_reason=%s",
        is_complete, stop_reason
    )

    return {
        "is_complete": is_complete,
        "stop_reason": stop_reason
    }
