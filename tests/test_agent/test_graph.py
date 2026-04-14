def test_graph_compiles():
    from fabops.agent.graph import build_graph
    g = build_graph()
    assert g is not None
