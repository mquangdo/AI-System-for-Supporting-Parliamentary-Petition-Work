"""Prompt system + prompt rewrite + hàm định dạng kết quả tra cứu."""

MAIN_SYSTEM_PROMPT = """Bạn là trợ lý pháp luật Việt Nam (cán bộ Thanh tra Chính phủ).
Trước khi trả lời câu hỏi liên quan tới quy định pháp luật, LUÔN gọi tool
tra_cuu_van_ban để tra cứu văn bản. Trả lời bằng tiếng Việt, chính xác,
dẫn chiếu số hiệu văn bản, điều, khoản khi có trong kết quả tra cứu.
Nếu kết quả tra cứu không đủ thông tin, nói rõ điều đó; không bịa nội dung."""

QUERY_REWRITER_PROMPT = """Bạn là chuyên gia tìm kiếm văn bản pháp luật.
Viết lại câu hỏi của người dùng thành 1 câu truy vấn ngắn gọn, tập trung vào nội dung cần tìm.
Nếu người dùng nói đến một văn bản cụ thể thì trích số hiệu văn bản (VD: 01/2013/TT-TTCP).

Câu hỏi: {query}

Trả lời đúng định dạng JSON:
{{"queries": ["câu truy vấn"], "doc_ref": "số hiệu hoặc rỗng"}}"""


def format_search_result(docs, doc_ref=""):
    """Định dạng danh sách Document từ Qdrant thành chuỗi có cấu trúc."""
    if not docs:
        return "Không tìm thấy văn bản phù hợp trong cơ sở dữ liệu."

    lines = [f"doc_ref: {doc_ref}" if doc_ref else "Tìm thấy các văn bản sau:", ""]
    for doc in docs:
        md = getattr(doc, "metadata", {}) or {}
        title = md.get("title") or md.get("doc_num") or "Không rõ"
        chunk_id = md.get("chunk_id", "")
        lines.append(f"- [{chunk_id}] {title}")
        lines.append(f"  {doc.page_content}")
        lines.append("")
    return "\n".join(lines).strip()