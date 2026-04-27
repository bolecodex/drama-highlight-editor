from __future__ import annotations

from typing import Any

from ..config import Settings


class ArkClient:
    """Tiny OpenAI-compatible client wrapper for Volcano Ark/Seed."""

    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        self.settings = settings or Settings.load()
        self.model = model or self.settings.ark_model_name

    def complete(self, content: list[dict[str, Any]], max_tokens: int = 8192, temperature: float = 0.1) -> str:
        api_key = self.settings.require_ark_api_key()
        try:
            import httpx
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai 或 httpx 依赖。请运行：python3 -m pip install --user .") from exc

        client = OpenAI(
            api_key=api_key,
            base_url=self.settings.ark_base_url,
            timeout=httpx.Timeout(1200.0, connect=60.0, write=600.0, read=1200.0),
            max_retries=2,
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()
