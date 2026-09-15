"""Hàm hạ tầng + pipeline tra cứu dùng chung (KHÔNG phải tool).

Các hàm ở đây là bước đệm cho tools (cache LLM/Qdrant, rewrite query,
truy vấn Qdrant, parse JSON) — không phải bản thân tool. Tool thật nằm
trong tools.py.
"""

import json
from functools import lru_cache

from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import FieldCondition, Filter, MatchText

from agents import prompts
from agents.config import get_settings
from agents.embeddings import get_embeddings
from agents.llm import get_llm

@lru_cache(maxsize=1)
def get_rewrite_llm(model=None):
    """Cache LLM dùng cho rewrite query."""
    return get_llm(model=model, temperature=0.0)


@lru_cache(maxsize=1)
def get_store(collection_name, url, api_key, timeout):
    """Cache QdrantVectorStore (kết nối 1 lần)."""
    return QdrantVectorStore.from_existing_collection(
        embedding=get_embeddings(),
        collection_name=collection_name,
        url=url,
        api_key=api_key or None,
        timeout=timeout or None,
    )


def json_loads_object(raw):
    """Trích object JSON đầu tiên từ chuỗi LLM (bọc trong dấu {} đầu tiên)."""
    return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])


def _doc_ref_filter(doc_ref):
    """Filter Qdrant: chỉ lấy chunks có title chứa doc_ref (full-text match)."""
    return Filter(must=[FieldCondition(key="metadata.title", match=MatchText(text=doc_ref))])


def rewrite_query(query, conversation="", model=None):
    """Viết lại query thành 1 câu truy vấn + trích doc_ref (JSON từ LLM).

    Lỗi LLM/parse -> trả nguyên câu hỏi, doc_ref rỗng.
    """
    llm = get_rewrite_llm(model)
    full = f"{conversation}\n{query}".strip() if conversation else query
    try:
        raw = llm.invoke(prompts.QUERY_REWRITER_PROMPT.format(query=full)).content
        data = json_loads_object(raw)
        queries = [q for q in (data.get("queries") or []) if q.strip()] or [query]
        doc_ref = str(data.get("doc_ref") or "").strip()
        return queries[0], doc_ref
    except Exception:
        return query, ""


def retrieve_docs(query, doc_ref="", top_k=None):
    """Truy vấn Qdrant (kèm filter doc_ref nếu có), dedup theo chunk_id."""
    settings = get_settings()
    store = get_store(
        settings.qdrant_collection,
        settings.qdrant_url,
        settings.qdrant_api_key,
        settings.timeout_sec,
    )
    top_k = top_k or settings.retrieve_top_k
    retriever = store.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": top_k,
            "filter": _doc_ref_filter(doc_ref) if doc_ref else None,
        },
    )
    docs_by_id = {}
    for doc in retriever.invoke(query):
        doc_id = (doc.metadata or {}).get("chunk_id") or hash(doc.page_content)
        docs_by_id.setdefault(doc_id, doc)
    return list(docs_by_id.values())[:top_k]