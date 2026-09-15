"""Config: đọc .env bằng python-dotenv, registry per-provider LLM.

Quy ước env mỗi provider: `{PROVIDER}_API_KEY`, `{PROVIDER}_BASE_URL`,
`{PROVIDER}_MODEL` (thêm provider = thêm 1 entry vào PROVIDERS, không phải
thêm field trong Settings).
"""

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


def _env(name, default=""):
    """Lấy giá trị env đã chuẩn hóa."""
    return _clean(os.getenv(name, default))


@dataclass(frozen=True)
class ProviderConfig:
    """Cấu hình một provider LLM (đọc từ env theo prefix `<NAME>_*`)."""

    name: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""  # model mặc định; trống = phải truyền đích danh

    @classmethod
    def from_env(cls, name):
        """Đọc ProviderConfig từ biến env `{NAME}_API_KEY/BASE_URL/MODEL`."""
        prefix = f"{name.upper()}_"
        return cls(
            name=name,
            api_key=_env(prefix + "API_KEY"),
            base_url=_env(prefix + "BASE_URL"),
            model=_env(prefix + "MODEL"),
        )


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "nvidia"
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
        return cls(
            llm_provider=_env("LLM_PROVIDER", "nvidia"),
            qdrant_url=_env("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=_env("QDRANT_API_KEY"),
            qdrant_collection=_env("QDRANT_COLLECTION", "vpl_chunks"),
            embedding_model=_env(
                "EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
            retrieve_top_k=int(_env("RETRIEVE_TOP_K", "6")),
            timeout_sec=int(_env("TIMEOUT_SEC", "120")),
            system_prompt=_env("SYSTEM_PROMPT"),
        )


# Registry provider LLM. Thêm provider mới: thêm 1 entry ở đây + khai báo biến
# env `{NAME}_API_KEY / _{NAME}_MODEL / _{NAME}_BASE_URL` trong .env.
PROVIDERS: dict[str, ProviderConfig] = {
    cfg.name: cfg
    for cfg in (
        ProviderConfig.from_env("nvidia"),
        ProviderConfig.from_env("groq"),
    )
}

# Fallback dùng chung cho các provider không có key riêng (OpenAI-compatible).
_GENERIC = ProviderConfig(
    name="_generic",
    api_key=_env("LLM_API_KEY"),
    base_url=_env("LLM_BASE_URL"),
    model=_env("OPENAI_LLM_MODEL"),
)

_settings = None


def get_settings() -> Settings:
    """Trả về Settings singleton (load 1 lần, dùng lại)."""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def get_provider_config(name) -> ProviderConfig:
    """Config của provider (có fallback generic LLM_* cho nvidia)."""
    cfg = PROVIDERS.get((name or "").lower())
    if cfg is None:
        raise NotImplementedError(
            f"Provider '{name}' chưa hỗ trợ. Có: {sorted(PROVIDERS)}"
        )
    if cfg.name == "nvidia" and not cfg.api_key:
        cfg = ProviderConfig(
            name=cfg.name,
            api_key=_GENERIC.api_key,
            base_url=_GENERIC.base_url,
            model=_GENERIC.model or cfg.model,
        )
    return cfg