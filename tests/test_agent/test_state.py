from fabops.agent.state import AgentState, ToolCallRecord


def test_agent_state_defaults():
    s = AgentState(request_id="r-123", user_query="why stockout?")
    assert s.request_id == "r-123"
    assert s.step_n == 0
    assert s.tool_calls == []
    assert s.part_id is None
    assert s.llm_pro_calls == 0


def test_agent_state_increment_step():
    s = AgentState(request_id="r-123", user_query="why?")
    s.step_n += 1
    assert s.step_n == 1
