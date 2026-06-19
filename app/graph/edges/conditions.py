from app.graph.state.agent_state import AgentState

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
