"""Agents: workflow single-graph 3 node (orchestrator / retrieve / summarize).

KHÔNG import eager ở đây để tránh chuẩn bị model/Qdrant khi chỉ cần config.
Import trực tiếp từ mô-đun con, VD: from agents.workflow import run_workflow.
"""