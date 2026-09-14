"""Main agent (supervisor): StateGraph tường minh với state riêng (MessagesState).

Graph: START -> model (LLM bind_tools) --tool_call?--> tools (ToolNode) -> model -> END.
Tool `tra_cuu_van_ban` chính là RetrievalAgent (graph con có state riêng).
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from agents import prompts
from agents.config import get_settings
from agents.llm import make_chat_model
from agents.retrieval_agent import RetrievalAgent


class MainAgent:
    """Supervisor graph: trò chuyện + gọi tool tra_cuu_van_ban khi cần."""

    def __init__(self, model=None, system_prompt=None, thread_id="default",
                 checkpointer=None, tools=None):
        """Khởi tạo MainAgent: LLM + tool list + checkpointer, dựng graph."""
        settings = get_settings()
        self._system_prompt = system_prompt or settings.system_prompt or prompts.MAIN_SYSTEM_PROMPT
        self._tool_list = tools if tools is not None else [RetrievalAgent().to_tool()]
        self._model = make_chat_model(model)
        self._checkpointer = checkpointer or InMemorySaver()
        self._thread_id = thread_id
        self._graph = self._build_graph()

    def _build_graph(self):
        """Xây graph: model -> (tool_call? -> tools -> model) -> END."""
        model = self._model.bind_tools(self._tool_list)
        tool_node = ToolNode(self._tool_list)

        def call_model(state):
            """Gọi LLM với system prompt + lịch sử messages."""
            messages = [("system", self._system_prompt)] + state["messages"]
            return {"messages": [model.invoke(messages)]}

        graph = StateGraph(MessagesState)
        graph.add_node("model", call_model)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", tools_condition)
        graph.add_edge("tools", "model")
        return graph.compile(checkpointer=self._checkpointer)

    # -- API bên ngoài ---------------------------------------------------

    def chat(self, text, thread_id=None):
        """Gửi câu hỏi, trả về câu trả lời cuối cùng của main agent."""
        config = {"configurable": {"thread_id": thread_id or self._thread_id}}
        result = self._graph.invoke({"messages": [("user", text)]}, config)
        return result["messages"][-1].content

    def history(self, thread_id=None):
        """Danh sách message trong thread."""
        config = {"configurable": {"thread_id": thread_id or self._thread_id}}
        return self._graph.get_state(config).values.get("messages", [])

    def reset(self, thread_id=None):
        """Xóa bộ nhớ thread."""
        tid = thread_id or self._thread_id
        delete = getattr(self._checkpointer, "delete_thread", None)
        if delete is not None:
            delete(tid)


def main():
    """CLI chat tương tác: python -m agents.main_agent"""
    agent = MainAgent()
    print("Main agent sẵn sàng. Gõ 'exit' / 'quit' / 'thoát' để thoát.")
    while True:
        user_input = input("\nBạn: ").strip()
        if user_input in ("exit", "quit", "thoát", "thoat"):
            break
        reply = agent.chat(user_input)
        print(f"\nAssistant: {reply}")


if __name__ == "__main__":
    main()