"""LLM: make_chat_model() -> ChatNVIDIA."""

from langchain_nvidia_ai_endpoints import ChatNVIDIA

from agents.config import get_settings


def make_chat_model(model=None, temperature=1.0, top_p=1.0, max_tokens=4096):
    """Tạo ChatNVIDIA từ config (.env).

    Key ưu tiên: NVIDIA_API_KEY -> LLM_API_KEY. Có LLM_BASE_URL thì gửi tới
    NIM tự host (OpenAI-compatible); ngược lại dùng NVIDIA API Catalog.
    """
    settings = get_settings()
    key = settings.nvidia_api_key or settings.llm_api_key or "EMPTY"
    kwargs = dict(
        model=model or settings.openai_llm_model,
        api_key=key,
        temperature=temperature,
        top_p=top_p,
        max_completion_tokens=max_tokens,
    )
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    return ChatNVIDIA(**kwargs)