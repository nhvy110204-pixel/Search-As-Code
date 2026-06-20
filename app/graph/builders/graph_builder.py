from langgraph.graph import StateGraph, START, END
from app.graph.state.agent_state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reasoner import reasoner_node
from app.graph.nodes.executor import executor_node
from app.graph.nodes.execution_validator import execution_validator_node
from app.graph.nodes.observer import observer_node
from app.graph.nodes.finalizer import finalizer_node
from app.graph.nodes.citation_validator import citation_validator_node
from app.graph.nodes.memory_extractor import memory_extractor_node
from app.graph.edges.conditions import should_continue, check_citation_status

def build_agent_graph(checkpointer=None):
    """
    Builds the LangGraph StateGraph for the Search-as-Code (SaC) ReAct loop
    with production refactoring, execution validation, and citation self-correction loops.
    """
    workflow = StateGraph(AgentState)
    
    # 1. Register nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("reasoner", reasoner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("execution_validator", execution_validator_node)
    workflow.add_node("observer", observer_node)
    workflow.add_node("finalizer", finalizer_node)
    workflow.add_node("citation_validator", citation_validator_node)
    workflow.add_node("memory_extractor", memory_extractor_node)
    
    # 2. Wire connections
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "reasoner")
    workflow.add_edge("reasoner", "executor")
    workflow.add_edge("executor", "execution_validator")
    workflow.add_edge("execution_validator", "observer")
    
    # Conditional routing from Observer to Reasoner or Finalizer
    workflow.add_conditional_edges(
        "observer",
        should_continue,
        {
            "reasoner": "reasoner",
            "finalizer": "finalizer"
        }
    )
    
    workflow.add_edge("finalizer", "citation_validator")
    
    # Conditional routing from Citation Validator to Finalizer (correction loop) or Memory Extractor (done)
    workflow.add_conditional_edges(
        "citation_validator",
        check_citation_status,
        {
            "finalizer": "finalizer",
            "memory_extractor": "memory_extractor"
        }
    )
    
    workflow.add_edge("memory_extractor", END)
    
    return workflow.compile(checkpointer=checkpointer)
