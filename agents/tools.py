"""Container TOÀN BỘ tools của dự án (kể cả retrieval) + get_tools() allowlist.

Mỗi node trong workflow tự liệt kê TÊN tool mình được phép dùng rồi gọi
get_tools(*names) để nhận đúng subset — không node nào mặc định thấy hết.

Hạ tầng/pipeline đỡ cho tools (rewrite query, truy vấn Qdrant, cache LLM,
parse JSON) nằm ở utils.py — nơi này chỉ khai báo TOOL thật.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents import prompts
from agents.utils import retrieve_docs, rewrite_query


class RetrievalInput(BaseModel):
    """Tham số tool tra_cuu_van_ban."""

    query: str = Field(description="Câu hỏi hoặc nội dung cần tra cứu văn bản.")
    conversation: str = Field(
        default="",
        description="Nội dung hội thoại trước (trống nếu không có).",
    )


def tra_cuu_van_ban(query: str, conversation: str = "") -> str:
    """Tool retrieval nguyên khối: rewrite -> retrieve -> format, trả text."""
    query, doc_ref = rewrite_query(query, conversation)
    docs = retrieve_docs(query, doc_ref)
    return prompts.format_search_result(docs, doc_ref)


# -- Registry: 1 nơi duy nhất liệt kê TOÀN BỘ tool -------------------------
TOOLS: dict[str, StructuredTool] = {
    t.name: t
    for t in [
        StructuredTool.from_function(
            func=tra_cuu_van_ban,
            name="tra_cuu_van_ban",
            description=(
                "Tra cứu văn bản pháp luật trong cơ sở dữ liệu Qdrant. "
                "Tham số: query (câu hỏi), conversation (hội thoại trước, tùy chọn). "
                "Trả về kết quả tra cứu kèm số hiệu văn bản."
            ),
            args_schema=RetrievalInput,
        ),
    ]
}


def get_tools(*names) -> list[StructuredTool]:
    """Lấy tools theo tên. Rỗng = tất cả; tên lạ -> ValueError.

    Dùng cho per-node allowlist: node nào liệt kê tên tool của mình ở đây.
    """
    if not names:
        return list(TOOLS.values())
    missing = [n for n in names if n not in TOOLS]
    if missing:
        raise ValueError(f"Tool không tồn tại trong TOOLS: {missing}")
    return [TOOLS[n] for n in names]