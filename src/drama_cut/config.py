from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def normalize_ark_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.endswith("/api/v3"):
        return value
    return f"{value}/api/v3"


def find_env_file(start: Path | None = None) -> Path | None:
    explicit = os.getenv("DRAMA_CUT_ENV")
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for parent in [cur, *cur.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    arkclaw_home = Path(os.getenv("ARKCLAW_HOME", Path.home() / ".arkclaw")).expanduser()
    candidate = arkclaw_home / ".env"
    if candidate.exists():
        return candidate
    return None


@dataclass(frozen=True)
class Settings:
    ark_api_key: str | None
    ark_base_url: str
    ark_model_name: str

    @classmethod
    def load(cls, start: Path | None = None) -> "Settings":
        env_file = find_env_file(start)
        if env_file:
            load_dotenv(env_file)
        return cls(
            ark_api_key=os.getenv("ARK_API_KEY"),
            ark_base_url=normalize_ark_base_url(os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")),
            ark_model_name=os.getenv("ARK_MODEL_NAME") or os.getenv("TEXT_ENDPOINT") or "doubao-seed-2-0-pro-260215",
        )

    def require_ark_api_key(self) -> str:
        if not self.ark_api_key:
            raise RuntimeError("未设置 ARK_API_KEY。请将它写入 .env 或当前环境变量。")
        return self.ark_api_key
