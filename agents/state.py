"""State duy nhất của workflow (pattern TimeNet): Pydantic BaseModel + multi-turn.

Multi-turn dùng cơ chế built-in của LangGraph: field `messages` với reducer
`add_messages` + checkpointer. Lịch sử là list message LangChain thật (human/ai),
không phải chuỗi "User:..." format thủ công.
"""

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class Analysis(BaseModel):
    """Quyết định của orchestrator_node (LLM chạy phẳng, không dùng tool)."""

    action: str = Field(
        default="search",
        description="Hành động: 'search' (điều hướng tra cứu) hoặc 'answer' (trả lời ngay).",
    )
    reasoning: str = Field(
        default="",
        description="Lý do chọn hành động.",
    )
    new_query: str = Field(
        default="",
        description="Câu truy vấn đã viết lại (khi search).",
    )


class LegalQAState(BaseModel):
    """Trạng thái toàn workflow: messages multi-turn, quan sát, câu trả lời."""

    question: str = Field(
        description="Câu hỏi hiện tại của người dùng.",
    )
    messages: Annotated[list[AnyMessage], add_messages] = Field(
        default_factory=list,
        description=(
            "Lịch sử hội thoại multi-turn (list message LangChain, nhà cung cấp tự"
            " nối thêm qua reducer add_messages; checkpointer persist theo thread_id)."
        ),
    )
    analysis: Analysis = Field(
        default_factory=Analysis,
        description="Phân tích + quyết định điều hướng của orchestrator_node.",
    )
    observations: list[str] = Field(
        default_factory=list,
        description="Các kết quả tra cứu (text) gom lại từ retrieve_node.",
    )
    summary: str = Field(
        default="",
        description="Kết quả tổng hợp (do summarize_node sinh) — orchestrator chỉ việc dùng.",
    )
    answer: str = Field(
        default="",
        description="Câu trả lời cuối cùng.",
    )
    early_stop_counter: int = Field(
        default=3,
        description="Số vòng tra cứu tối đa còn lại (chống lặp vô hạn search).",
    )