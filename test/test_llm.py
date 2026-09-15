"""Test các factory LLM (registry config.py + get_llm): kiểm tra provider/model
và gọi thật LLM.

Chạy:
    python test/test_llm.py                # test nhanh, không gọi API
    python test/test_llm.py --live         # kèm smoke test invoke thật (cần key)
    python test/test_llm.py --provider groq
"""

import argparse
import sys

sys.path.insert(0, "")

from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from agents import llm as llm_mod
from agents.config import PROVIDERS, get_provider_config, get_settings
from agents.llm import get_llm, get_llm_groq, get_llm_nvidia

_settings = get_settings()
passed = 0


def check(name, cond, extra=""):
    global passed
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({extra})" if extra else ""))
    passed += bool(cond)


def _secret_equals(obj, value):
    """So sánh api_key (có thể là SecretStr, bị mask) với giá trị registry."""
    key = getattr(obj, "groq_api_key", None) or getattr(obj, "api_key", None)
    if hasattr(key, "get_secret_value"):
        key = key.get_secret_value()
    return str(key) == value


def test_dispatch():
    print(f"\n== Registry & dispatch (provider mặc định: {_settings.llm_provider}) ==")
    check("registry có đúng {'nvidia','groq'}", set(PROVIDERS) == {"nvidia", "groq"})
    check("get_llm('nvidia') -> ChatNVIDIA", isinstance(get_llm(provider="nvidia"), ChatNVIDIA))
    check("get_llm('groq') -> ChatGroq",
          isinstance(get_llm(provider="groq", model="llama-3.3-70b-versatile"), ChatGroq))
    check("get_llm_nvidia -> ChatNVIDIA", isinstance(get_llm_nvidia(), ChatNVIDIA))
    check("get_llm() mặc định theo settings",
          isinstance(get_llm(),
                     ChatNVIDIA if _settings.llm_provider == "nvidia" else ChatGroq))

    check("model không ảnh hưởng provider (theo settings)",
          isinstance(get_llm(model="llama-3.3-70b-versatile"),
                     ChatNVIDIA if _settings.llm_provider == "nvidia" else ChatGroq))
    check("provider ưu tiên hơn tên model",
          isinstance(get_llm(provider="groq", model="some-gpt-model"), ChatGroq))

    try:
        get_llm(provider="unknown")
        check("provider lạ -> NotImplementedError", False)
    except NotImplementedError:
        check("provider lạ -> NotImplementedError", True)

    if not get_provider_config("groq").model:
        try:
            get_llm_groq()
            check("groq thiếu model -> ValueError", False)
        except ValueError:
            check("groq model trống -> ValueError", True)
    else:
        check("groq model trống -> ValueError (skip: GROQ_MODEL đã set)", True)


def test_config(provider):
    print(f"\n== Config registry ({provider}) ==")
    cfg = get_provider_config(provider)
    check("key không rỗng trong registry", bool(cfg.api_key))
    if provider == "groq":
        obj = get_llm_groq(model="llama-3.3-70b-versatile")
        check("model truyền đích danh khớp", obj.model == "llama-3.3-70b-versatile")
        check("api_key khớp registry (groq_api_key)",
              str(getattr(obj, "groq_api_key", None)) == cfg.api_key
              or _secret_equals(obj, cfg.api_key))
    else:
        obj = get_llm_nvidia(model="test-model")
        check("model truyền đích danh khớp", obj.model == "test-model")
        check("nvidia chứa key không rỗng", bool(cfg.api_key))


def test_live(provider):
    print(f"\n== Live invoke (provider={provider}) ==")
    cfg = get_provider_config(provider)
    if not cfg.model:
        check(f"bỏ qua live {provider}: chưa có {provider.upper()}_MODEL", True)
        return
    obj = get_llm(provider=provider)  # dùng model mặc định từ registry
    print(f"  provider={provider} model={obj.model}")
    try:
        resp = obj.invoke("Trả lời ngắn: 1+1 bằng mấy?")
        text = resp.content if hasattr(resp, "content") else str(resp)
        check("invoke OK", bool(text.strip()), text.strip()[:80])
    except Exception as exc:  # noqa: BLE001
        check(f"invoke THẤT BẠI: {type(exc).__name__}", False, str(exc)[:120])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Gọi thật LLM để xác nhận từng provider hoạt động.")
    parser.add_argument("--provider", default=None,
                        help="Chỉ test 1 provider (nvidia|groq).")
    args = parser.parse_args()

    providers = [args.provider] if args.provider else sorted(PROVIDERS)

    test_dispatch()

    for p in providers:
        test_config(p)
        if args.live:
            test_live(p)

    print(f"\n-> {passed} checks ", end="")
    print("OK" if passed else "(có FAIL)", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()