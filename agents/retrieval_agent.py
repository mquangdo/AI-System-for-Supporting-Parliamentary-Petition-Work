"""Retrieval agent: StateGraph riêng (rewrite -> retrieve -> format).

Được expose cho main agent dưới dạng tool `tra_cuu_van_ban` (StructuredTool).
"""

import json
from functools import lru_cache
from typing import TypedDict

from langchain_qdrant import QdrantVectorStore
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchText

from agents import prompts
from agents.config import get_settings
from agents.embeddings import get_embeddings
from agents.llm import make_chat_model


@lru_cache(maxsize=1)
def _get_rewrite_llm(model=None):
    """Cache ChatNVIDIA cho rewrite node."""
    return make_chat_model(model, temperature=0.0)


@lru_cache(maxsize=1)
def _get_store(collection_name, url, api_key, timeout):
    """Cache QdrantVectorStore (kết nối 1 lần)."""
    return QdrantVectorStore.from_existing_collection(
        embedding=get_embeddings(),
        collection_name=collection_name,
        url=url,
        api_key=api_key or None,
        timeout=timeout or None,
    )


class RetrievalState(TypedDict, total=False):
    query: str
    conversation: str
    queries: list[str]
    doc_ref: str
    docs: list
    result: str


class RetrievalInput(BaseModel):
    query: str = Field(description="Câu hỏi hoặc nội dung cần tra cứu văn bản.")
    conversation: str = Field(default="", description="Nội dung hội thoại trước (trống nếu không có).")


class RetrievalAgent:
    """Graph tra cứu: rewrite (LLM) -> retrieve (Qdrant) -> format (text)."""

    name = "tra_cuu_van_ban"
    description = (
        "Tra cứu văn bản pháp luật trong cơ sở dữ liệu Qdrant. "
        "Tham số: query (câu hỏi), conversation (hội thoại trước, tùy chọn). "
        "Trả về kết quả tra cứu kèm số hiệu văn bản."
    )

    def __init__(self, model=None, top_k=None):
        """Khởi tạo agent: dựng graph rewrite -> retrieve -> format."""
        settings = get_settings()
        self._model = model or settings.openai_subagent_model or None
        self._top_k = top_k or settings.retrieve_top_k
        self._graph = self._build_graph()

    def _build_graph(self):
        """Xây StateGraph 3 node: rewrite -> retrieve -> format."""
        graph = StateGraph(RetrievalState)
        graph.add_node("rewrite", self._rewrite)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("format", self._format)
        graph.add_edge(START, "rewrite")
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("retrieve", "format")
        graph.add_edge("format", END)
        return graph.compile()

    def _rewrite(self, state):
        """LLM viết lại query thành 1 câu truy vấn + trích doc_ref từ câu hỏi."""
        llm = _get_rewrite_llm(self._model)
        query = state["query"]
        try:
            raw = llm.invoke(
                prompts.QUERY_REWRITER_PROMPT.format(query=query)
            ).content
            data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            queries = [q for q in (data.get("queries") or []) if q.strip()] or [query]
            doc_ref = str(data.get("doc_ref") or "").strip()
        except Exception:
            queries, doc_ref = [query], ""
        return {"queries": [queries[0]], "doc_ref": doc_ref}

    def _retrieve(self, state):
        """Gọi Qdrant với mỗi query, dedup theo chunk_id, trả về danh sách Document."""
        settings = get_settings()
        store = _get_store(
            settings.qdrant_collection,
            settings.qdrant_url,
            settings.qdrant_api_key,
            settings.timeout_sec,
        )
        retriever = store.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": self._top_k,
                "filter": self._doc_ref_filter(state.get("doc_ref")) if state.get("doc_ref") else None,
            },
        )
        docs_by_id = {}
        for q in state["queries"]:
            for doc in retriever.invoke(q):
                doc_id = (doc.metadata or {}).get("chunk_id") or hash(doc.page_content)
                docs_by_id.setdefault(doc_id, doc)
        docs = list(docs_by_id.values())[: self._top_k]
        return {"docs": docs}

    @staticmethod
    def _doc_ref_filter(doc_ref):
        """Tạo filter Qdrant: chỉ lấy chunks có title chứa doc_ref (full-text match)."""
        return Filter(
            must=[FieldCondition(key="metadata.title", match=MatchText(text=doc_ref))]
        )

    def _format(self, state):
        """Format danh sách Document thành chuỗi kết quả có cấu trúc."""
        docs = state.get("docs") or []
        return {"result": prompts.format_search_result(docs, state.get("doc_ref", ""))}

    def run(self, query, conversation=""):
        """Chạy toàn bộ graph: rewrite -> retrieve -> format, trả về chuỗi kết quả."""
        out = self._graph.invoke({"query": query, "conversation": conversation})
        return out.get("result", "")

    def to_tool(self):
        """Bọc graph thành StructuredTool để MainAgent gọi qua ToolNode."""
        from langchain_core.tools import StructuredTool

        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=RetrievalInput,
            func=self.run,
        )