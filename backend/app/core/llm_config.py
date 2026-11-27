"""统一管理兼容 OpenAI Chat Completions 协议的大模型配置。"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LLMConfig:
    """当前大模型请求所需的配置。"""

    api_url: str
    api_key: str
    model: str
    timeout: float


def load_llm_config() -> LLMConfig:
    """读取统一环境变量；仅在未配置新变量时兼容旧版 DeepSeek 配置。"""
    new_configured = any(
        os.getenv(name, "").strip()
        for name in ("LLM_API_URL", "LLM_BASE_URL", "LLM_API_KEY", "CSU_API_KEY", "LLM_MODEL", "CSU_MODEL")
    )
    legacy_deepseek = not new_configured and bool(os.getenv("DEEPSEEK_API_KEY", "").strip())

    api_url = os.getenv("LLM_API_URL", "").strip().rstrip("/")
    if not api_url:
        base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
        if base_url:
            api_url = base_url
        elif legacy_deepseek:
            api_url = "https://api.deepseek.com/chat/completions"
        else:
            api_url = "https://api.chat.csu.edu.cn/v1/chat/completions"

    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    if legacy_deepseek:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        model = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-flash"
    else:
        api_key = (
            os.getenv("LLM_API_KEY", "").strip()
            or os.getenv("CSU_API_KEY", "").strip()
        )
        model = (
            os.getenv("LLM_MODEL", "").strip()
            or os.getenv("CSU_MODEL", "").strip()
        )

    if not api_key:
        raise RuntimeError("LLM_API_KEY_NOT_CONFIGURED")
    if not model:
        raise RuntimeError("LLM_MODEL_NOT_CONFIGURED")

    try:
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("LLM_TIMEOUT_INVALID") from exc
    if timeout <= 0:
        raise RuntimeError("LLM_TIMEOUT_INVALID")

    return LLMConfig(
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
    )
