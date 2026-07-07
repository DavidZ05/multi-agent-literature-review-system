from __future__ import annotations

from importlib.resources import files
import re


class PromptNotFoundError(FileNotFoundError):
    """Raised when a packaged agent prompt is missing."""


_PROMPT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def load_prompt(name: str) -> str:
    if not _PROMPT_NAME.fullmatch(name):
        raise PromptNotFoundError(name)
    prompt_path = files("src.literature_review").joinpath("prompts", f"{name}.txt")
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptNotFoundError(name) from exc


__all__ = ["PromptNotFoundError", "load_prompt"]
