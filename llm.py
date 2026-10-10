"""Every LLM call in the app goes through llm(), so the provider can be swapped in
one place (for example, if Bosch provides its own model)."""

import functools

import anthropic
from dotenv import load_dotenv

load_dotenv()


@functools.cache
def _client() -> anthropic.Anthropic:
    # Lazy: importing this module works without credentials (tests, AppTest).
    return anthropic.Anthropic()


def llm(prompt: str, system: str | None = None, model: str = "claude-opus-5-5",
        effort: str = "high", max_tokens: int = 16000) -> str:
    """Send one prompt, return the text answer. Raises RuntimeError on a refusal."""
    extra = {"system": system} if system else {}
    if "haiku" not in model:  # Haiku has no server-side fallback
        extra |= {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = _client().beta.messages.create(
        model=model,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
        **extra,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {response.stop_details}")
    return "".join(block.text for block in response.content if block.type == "text")
