from app.graph.state.agent_state import AgentState

def should_continue(state: AgentState) -> str:
    """
    Observer node conditional routing logic.
    Returns "finalizer" if graph is complete or error/turn limit is reached.
    Otherwise returns "reasoner" to perform another search turn.
    """
    if state.get("is_complete") or state.get("stop_reason"):
        return "finalizer"
        
    return "reasoner"

def check_citation_status(state: AgentState) -> str:
    """
    Conditional routing after citation validation.
    If unverified claims exist (i.e. validation failed), route back to finalizer.
    Otherwise, proceed to memory_extractor.
    """
    if state.get("unverified_claims"):
        return "finalizer"
    return "memory_extractor"
