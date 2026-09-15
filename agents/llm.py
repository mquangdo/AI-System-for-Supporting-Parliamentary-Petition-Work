"""LLM: các hàm get_llm.<provider>() tự đọc ProviderConfig từ config.py.

Mỗi provider một hàm get_llm_<provider>; dispatcher get_llm() chỉ dùng
provider từ tham số hoặc mặc định `settings.llm_provider`. Không suy đoán gì
thêm. Thêm provider mới: viết hàm + đăng ký _FACTORIES.
"""

from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from agents.config import get_provider_config, get_settings


def _only(kwargs, name):
    """Giữ giá trị chỉ khi khác None (tránh truyền tham số model không nhận)."""
    value = kwargs.pop(name, None)
    if value is not None:
        kwargs[name] = value
    return kwargs


def get_llm_nvidia(model=None, temperature=1.0, top_p=1.0, max_tokens=2048):
    """Tạo ChatNVIDIA từ config (provider `nvidia` / fallback generic LLM_*)."""
    cfg = get_provider_config("nvidia")
    kwargs = _only(
        {
            "model": model or cfg.model,
            "api_key": cfg.api_key or "EMPTY",
            "temperature": temperature,
            "top_p": top_p,
            "max_completion_tokens": max_tokens,
        },
        "top_p",
    )
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    return ChatNVIDIA(**kwargs)


def get_llm_groq(model=None, temperature=1.0, top_p=None, max_tokens=2048):
    """Tạo ChatGroq từ config (provider `groq`). Cần GROQ_API_KEY + model.

    Groq KHÔNG có tham số top_p (pydantic sẽ warn nếu truyền) nên chỉ chuyển
    khi người gọi đích danh.
    """
    cfg = get_provider_config("groq")
    model = model or cfg.model
    if not model:
        raise ValueError(
            "Thiếu model cho Groq: set GROQ_MODEL trong .env hoặc truyền `model=`."
        )
    return ChatGroq(
        **_only(
            {
                "model": model,
                "api_key": cfg.api_key,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            },
            "top_p",
        )
    )


_FACTORIES = {
    "nvidia": get_llm_nvidia,
    "groq": get_llm_groq,
}


def get_llm(provider=None, model=None, temperature=1.0, top_p=None, max_tokens=2048):
    """Dispatcher: provider từ tham số, ngược lại dùng mặc định settings.

    top_p mặc định None: provider nào không hỗ trợ (Groq) sẽ không nhận tham
    số này; provider hỗ trợ (NVIDIA) nhận top_p=1.0 nếu cần.
    """
    if not provider:
        provider = get_settings().llm_provider
    factory = _FACTORIES.get((provider or "").lower())
    if factory is None:
        raise NotImplementedError(
            f"Provider '{provider}' chưa hỗ trợ. Có: {sorted(_FACTORIES)}"
        )
    return factory(model=model, temperature=temperature, top_p=top_p, max_tokens=max_tokens)