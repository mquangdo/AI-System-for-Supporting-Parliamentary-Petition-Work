"""Test workflow chính (pattern TimeNet): chạy run_workflow, kiểm tra multi-turn.

Chạy:
    python test/main_test.py
"""

import os, sys
os.environ["PYTHONIOENCODING"] = "utf-8"
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.tools import TOOLS, get_tools
from agents.workflow import run_workflow, workflow


def test_ok():
    g = workflow()
    assert list(g.get_graph().nodes.keys()) == [
        "__start__", "orchestrator_node", "retrieve_node", "summarize_node", "__end__",
    ], f"graph structure wrong: {list(g.get_graph().nodes.keys())}"
    assert set(TOOLS) == {"tra_cuu_van_ban"}, f"TOOLS wrong: {sorted(TOOLS)}"

    (tool,) = get_tools("tra_cuu_van_ban")
    assert tool.name == "tra_cuu_van_ban"

    try:
        get_tools("unknown_tool")
        assert False, "get_tools() should raise ValueError for unknown name"
    except ValueError:
        pass
    print("test_ok: graph (3 node) + TOOLS registry OK")


def test_live_one_turn():
    answer, messages = run_workflow("Chao ban, ban la ai?", thread_id="test-worker")
    print("\n=== TURN 1 ===")
    print(f"ANSWER: {answer[:200]}")
    assert answer, "answer is empty"
    assert len(messages) == 2, f"state.messages should have 2 entries, got {len(messages)}"
    print(f"MESSAGES: {[type(m).__name__ for m in messages]}")

    answer2, messages2 = run_workflow("Cam on ban", thread_id="test-worker")
    print("\n=== TURN 2 (multi-turn, same thread) ===")
    print(f"ANSWER: {answer2[:200]}")
    assert len(messages2) == 4, f"messages after turn2 should have 4 entries, got {len(messages2)}"
    print(f"MESSAGES: {[type(m).__name__ for m in messages2]}")
    print("test_live_one_turn OK")


if __name__ == "__main__":
    test_ok()
    test_live_one_turn()
    print("\nmain_test: ALL DONE")