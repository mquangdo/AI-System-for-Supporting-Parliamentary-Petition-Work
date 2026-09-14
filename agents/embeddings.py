"""Embedding query: HuggingFaceEmbeddings (langchain_huggingface), dùng cache singleton.

Tránh load lại model ở mọi lượt tra cứu: 1 instance duy nhất dùng chung.
Model phải khớp model dựng index (MiniLM 384-d, normalize_embeddings=True).
"""

from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings


def _build():
    """Tạo HuggingFaceEmbeddings từ config (model + normalize)."""
    from agents.config import get_settings

    settings = get_settings()
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 32},
    )


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """Trả về embedder dùng chung (load model 1 lần cho toàn tiến trình)."""
    return _build()