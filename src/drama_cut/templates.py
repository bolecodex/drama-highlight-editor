from __future__ import annotations

import json
from importlib import resources
from pathlib import Path


def _templates_root():
    return resources.files("drama_cut").joinpath("templates")


def list_templates() -> list[dict]:
    with resources.as_file(_templates_root().joinpath("index.json")) as path:
        return json.loads(Path(path).read_text(encoding="utf-8"))


def get_template_meta(template_id: str) -> dict:
    for item in list_templates():
        if item["id"] == template_id:
            return item
    known = ", ".join(item["id"] for item in list_templates())
    raise KeyError(f"未知模板：{template_id}。可用模板：{known}")


def load_template(template_id: str) -> str:
    meta = get_template_meta(template_id)
    with resources.as_file(_templates_root().joinpath(meta["file"])) as path:
        return Path(path).read_text(encoding="utf-8")
