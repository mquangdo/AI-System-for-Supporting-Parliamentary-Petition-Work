"""Agents: main agent (graph) + retrieval agent (graph con dạng tool).

KHÔNG import eager ở đây để tránh chuẩn bị model/Qdrant khi chỉ cần config.
Import trực tiếp từ mô-đun con: from agents.main_agent import MainAgent.
"""