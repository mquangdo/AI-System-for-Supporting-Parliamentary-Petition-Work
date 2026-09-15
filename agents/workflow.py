"""Workflow: 3 node — orchestrator + retrieve + summarize.

Graph:
    START -> orchestrator_node --router--> retrieve_node -> summarize_node
            ^                          `-> END              `-> orchestrator_node
            |                                                 (vòng tới khi answer)
            `-------------------------- (lặp lại tới khi answer)

- orchestrator_node: LLM chạy phẳng (KHÔNG tools), CHỈ QUYẾT ĐỊNH hướng đi.
  Nhận list messages thật `[System(ORCHESTRATOR_PROMPT)] + state.messages`;
  tin cuối = câu hỏi hiện tại, các tin trước = lịch sử. Phân tích JSON ->
  action search/answer. KHÔNG tự summarize: khi đã có summary thì chỉ gán
  answer = summary rồi kết thúc.
- retrieve_node: retrieve agent — dùng ĐÚNG tool allowlist ("tra_cuu_van_ban"),
  gom kết quả thô vào observations.
- summarize_node: LLM tổng hợp observations -> summary (dẫn chiếu văn bản).

Multi-turn dùng cơ chế built-in của LangGraph: `messages` có reducer
`add_messages` + checkpointer MemorySaver (persist theo thread_id). Người dùng
gửi qua `HumanMessage`; câu trả lời là `AIMessage` được nối tự động.
"""

import json
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph, START, END

from agents import prompts
from agents.llm import get_llm
from agents.state import Analysis, LegalQAState
from agents.tools import get_tools

# Allowlist tools cho retrieve node
RETRIEVE_NODE_TOOLS = ("tra_cuu_van_ban",)
MAX_RETRIEVE_TURNS = 3
MAX_CONTEXT_MESSAGES = 20


def _json_object(raw):
    """Trích object JSON đầu tiên từ chuỗi LLM."""
    raw = str(raw)
    return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])


def _llm_input(system, messages):
    """Dựng input [system, *history] với trim để context không phình vô hạn."""
    def _count(msgs):
        return len(msgs) if isinstance(msgs, list) else 1

    trimmed = trim_messages(
        messages,
        strategy="last",
        max_tokens=MAX_CONTEXT_MESSAGES,
        token_counter=_count,
        start_on="human",
        include_system=False,
    )
    return [system, *trimmed]


def _conversation_text(messages):
    """Ghép history messages thành chuỗi (cho tool tra cứu, tối đa 6 tin)."""
    parts = []
    for m in messages[-6:]:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts)


def orchestrator_node(state: LegalQAState) -> LegalQAState:
    """LLM phẳng: CHỈ quyết định. Có summary -> answer = summary, không summarize."""
    if state.summary and not state.answer:
        # Đã được summarize_node tổng hợp: chỉ việc dùng, không gọi LLM lại
        state.answer = state.summary
        state.analysis = Analysis(action="answer", reasoning="dùng summary có sẵn", new_query="")
        state.messages.append(AIMessage(content=state.answer))
        return state

    llm = get_llm(provider='groq', temperature=0.0)
    system = SystemMessage(prompts.ORCHESTRATOR_PROMPT)
    msgs = _llm_input(system, state.messages)

    try:
        data = _json_object(llm.invoke(msgs).content)
        action = str(data.get("action") or "").strip().lower()
        answer = str(data.get("answer") or "").strip()
        if action == "answer" and not answer:
            # LLM bảo trả lời ngay nhưng không đưa nội dung: ép tra cứu
            action = "search"
        state.analysis = Analysis(
            action=action or ("answer" if state.summary else "search"),
            reasoning=str(data.get("reasoning") or "").strip(),
            new_query=str(data.get("new_query") or "").strip(),
        )
    except Exception:
        # LLM lỗi/parse hỏng: thử search; từ chối đoán mò
        state.analysis = Analysis(
            action="search",
            reasoning="fallback do lỗi LLM/parse",
            new_query=state.question,
        )
        answer = ""

    if answer and state.analysis.action == "answer":
        state.answer = answer
        state.messages.append(AIMessage(content=state.answer))

    return state


def retrieve_node(state: LegalQAState) -> LegalQAState:
    """Retrieve agent: gọi tool tra_cuu_van_ban, gom kết quả thô vào observations."""
    state.early_stop_counter -= 1
    tool = get_tools(*RETRIEVE_NODE_TOOLS)[0]
    query = state.analysis.new_query or state.question
    result = tool.invoke(
        {"query": query, "conversation": _conversation_text(state.messages)}
    )
    state.observations.append(result)
    return state


def summarize_node(state: LegalQAState) -> LegalQAState:
    """Tổng hợp toàn bộ observations thành summary (dẫn chiếu văn bản)."""
    observations = "\n\n".join(state.observations) or "(không có kết quả)"
    prompt = prompts.SUMMARY_PROMPT.format(
        question=state.question,
        observations=observations,
    )
    content = get_llm(provider='groq', temperature=0.0).invoke(prompt).content
    state.summary = str(content if content is not None else "").strip()
    return state


def router(state: LegalQAState) -> str:
    """Điều hướng từ orchestrator: search -> retrieve_node; ngược lại -> END."""
    if state.early_stop_counter > 0 and state.analysis.action == "search":
        return "retrieve_node"
    return "__end__"


@lru_cache(maxsize=1)
def workflow():
    """Dựng graph 3 node: orchestrator --router--> retrieve -> summarize (lặp).

    Compile với MemorySaver: state (messages, analysis, observations, summary,
    answer) persist theo thread_id — lịch sử tự khôi phục giữa các lượt. Kết
    quả cache (lru_cache) để không compile lại mỗi lượt gọi.
    """
    graph = StateGraph(LegalQAState)
    graph.add_node("orchestrator_node", orchestrator_node)
    graph.add_node("retrieve_node", retrieve_node)
    graph.add_node("summarize_node", summarize_node)
    graph.set_entry_point("orchestrator_node")
    graph.add_conditional_edges(
        "orchestrator_node",
        router,
        {
            "retrieve_node": "retrieve_node",
            "__end__": END,
        },
    )
    graph.add_edge("retrieve_node", "summarize_node")
    graph.add_edge("summarize_node", "orchestrator_node")
    return graph.compile(
        checkpointer=MemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[("agents.state", "Analysis")]
            )
        )
    )


def run_workflow(question: str, thread_id: str = "default"):
    """Chạy workflow 1 lượt trong thread; resume tự động từ checkpointer.

    Câu hỏi nạp qua `HumanMessage`; lịch sử (messages cũ) được checkpointer
    khôi phục theo thread_id — không truyền thủ công. Đổi thread_id để bắt
    đầu hội thoại mới. Trả về (answer, messages_sau_lượt_này).
    """
    if not question or not question.strip():
        raise ValueError("Câu hỏi không được để trống.")
    final = workflow().invoke(
        {
            "question": question,
            "messages": [HumanMessage(content=question)],
            "analysis": Analysis(action="", reasoning="", new_query=""),
            "observations": [],
            "summary": "",
            "answer": "",
            "early_stop_counter": MAX_RETRIEVE_TURNS,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return final["answer"].strip(), final["messages"]


def main():
    """CLI chat multi-turn: python -m agents.workflow (thread_id=default)."""
    print("Workflow sẵn sàng. Gõ 'exit'/'quit'/'thoát' để thoát.")
    while True:
        user_input = input("\nBạn: ").strip()
        if user_input in ("exit", "quit", "thoát", "thoat"):
            break
        try:
            answer, _ = run_workflow(user_input)
            print(f"\nAssistant: {answer}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[Lỗi] {exc}")


if __name__ == "__main__":
    main()