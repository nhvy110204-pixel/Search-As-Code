from langgraph.graph import StateGraph, START, END
from app.graph.state.agent_state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reasoner import reasoner_node
from app.graph.nodes.executor import executor_node
import os
import sys
from langgraph.checkpoint.redis import RedisSaver
from langgraph.checkpoint.memory import MemorySaver
from app.config.settings import settings

def should_continue(state: AgentState) -> str:
    """
    Quyết định xem có nên tiếp tục thực thi hay dừng lại.
    Trả về "execute" nếu có code để chạy, hoặc "end" nếu việc thực thi đã hoàn tất
    hoặc đã đạt đến số vòng tối đa.
    """
    # Nếu không có code đang chờ được đề xuất bởi Reasoner, dừng đồ thị.
    if not state.get("_pending_code"):
        return "end"
    
    # Nếu chúng ta đã đạt hoặc vượt quá số vòng tối đa cho phép
    current_turn = state.get("current_turn", 0)
    max_turns = state.get("max_turns", 10)
    if current_turn >= max_turns:
        return "end"
        
    return "execute"

from app.graph.nodes.extractor import extractor_node

# Định nghĩa cấu trúc StateGraph
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

# Tự động chuyển đổi checkpoint saver dựa trên môi trường để hỗ trợ kiểm thử đơn vị ngoại tuyến
if "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or settings.APP_ENV == "test":
    saver = MemorySaver()
else:
    redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    saver = RedisSaver(redis_url=redis_url)

# Biên dịch đồ thị agent cuối cùng với checkpointer được bật
agent_graph = workflow.compile(checkpointer=saver)
