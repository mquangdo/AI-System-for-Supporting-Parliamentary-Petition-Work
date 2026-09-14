"""Config: đọc .env bằng python-dotenv, chuẩn hóa "EMPTY"/rỗng -> ""."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _clean(value):
    """Chuẩn hóa giá trị env: None/rỗng/"EMPTY" -> ""."""
    if value is None:
        return ""
    value = value.strip()
    return "" if value in ("", "EMPTY") else value


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = ""
    llm_api_key: str = ""
    nvidia_api_key: str = ""
    openai_llm_model: str = "deepseek-ai/deepseek-v4-flash-0731"
    openai_subagent_model: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "vpl_chunks"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    retrieve_top_k: int = 6
    timeout_sec: int = 120
    system_prompt: str = ""

    @classmethod
    def load(cls):
        """Đọc toàn bộ biến cấu hình từ .env và trả về Settings."""

        def get(name, default=""):
            """Lấy giá trị env đã chuẩn hóa."""
            return _clean(os.getenv(name, default))

        return cls(
            llm_base_url=get("LLM_BASE_URL"),
            llm_api_key=get("LLM_API_KEY"),
            nvidia_api_key=get("NVIDIA_API_KEY"),
            openai_llm_model=get("OPENAI_LLM_MODEL", "openai/gpt-oss-20b"),
            openai_subagent_model=get("OPENAI_SUBAGENT_MODEL"),
            qdrant_url=get("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=get("QDRANT_API_KEY"),
            qdrant_collection=get("QDRANT_COLLECTION", "vpl_chunks"),
            embedding_model=get(
                "EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
            retrieve_top_k=int(get("RETRIEVE_TOP_K", "6")),
            timeout_sec=int(get("TIMEOUT_SEC", "120")),
            system_prompt=get("SYSTEM_PROMPT"),
        )


_settings = None


def get_settings() -> Settings:
    """Trả về Settings singleton (load 1 lần, dùng lại)."""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings