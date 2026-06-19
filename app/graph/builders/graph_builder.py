from langgraph.graph import StateGraph, START, END
from app.graph.state.agent_state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reasoner import reasoner_node
from app.graph.nodes.executor import executor_node
from app.graph.nodes.extractor import extractor_node
from app.graph.edges.conditions import should_continue

def build_agent_graph(checkpointer=None):
    """
    Xây dựng LangGraph StateGraph cho Search-as-Code (SaC) ReAct loop.
    """
    workflow = StateGraph(AgentState)
    
    # Đăng ký các node
    workflow.add_node("planner", planner_node)
    workflow.add_node("reasoner", reasoner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("extractor", extractor_node)
    
    # Định nghĩa các chuyển đổi
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "reasoner")
    
    # Thêm định tuyến có điều kiện sau node Reasoner
    workflow.add_conditional_edges(
        "reasoner",
        should_continue,
        {
            "execute": "executor",
            "end": "extractor"
        }
    )
    
    # Quay lại Reasoner sau khi thực thi hoàn tất
    workflow.add_edge("executor", "reasoner")
    
    # Liên kết node extractor với trạng thái END
    workflow.add_edge("extractor", END)
    
    return workflow.compile(checkpointer=checkpointer)
