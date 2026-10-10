"""Every LLM call in the app goes through llm(), so the provider can be swapped in
one place (for example, if Bosch provides its own model).

Providers: anthropic (default), groq, openrouter. Pick one per call with
llm(..., provider="groq"), or set LLM_PROVIDER (and optionally LLM_MODEL) in .env."""

import functools
import json
import os
import urllib.error
import urllib.request

import anthropic
from dotenv import load_dotenv

load_dotenv()

# OpenAI-compatible providers: base url, key variable, default model
OPENAI_STYLE = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "nvidia/nemotron-3.5-lightning:free"),
}


@functools.cache
def _client() -> anthropic.Anthropic:
    # Lazy: importing this module works without credentials (tests, AppTest).
    return anthropic.Anthropic()


def llm(prompt: str, system: str | None = None, model: str | None = None,
        effort: str = "high", max_tokens: int = 16000, provider: str | None = None) -> str:
    """Send one prompt, return the text answer. Raises RuntimeError on a refusal or HTTP error."""
    if provider is None:  # LLM_MODEL pairs with LLM_PROVIDER, so only the env pair is used together
        provider = os.environ.get("LLM_PROVIDER", "anthropic")
        model = model or os.environ.get("LLM_MODEL")
    if provider in OPENAI_STYLE:
        return _openai_style(provider, prompt, system, model, max_tokens)
    if provider != "anthropic":
        raise ValueError(f"unknown provider {provider!r}; use anthropic, {', '.join(OPENAI_STYLE)}")
    return _anthropic(prompt, system, model or "claude-opus-5-5", effort, max_tokens)


def _anthropic(prompt, system, model, effort, max_tokens) -> str:
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


def _openai_style(provider, prompt, system, model, max_tokens) -> str:
    base, key_var, default_model = OPENAI_STYLE[provider]
    key = os.environ.get(key_var)
    if not key:
        raise RuntimeError(f"{key_var} is not set; add it to .env")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model or default_model, "messages": messages, "max_tokens": max_tokens}).encode()
    # a User-Agent is needed: Groq's Cloudflare front door rejects urllib's default with a 403
    req = urllib.request.Request(f"{base}/chat/completions", body, {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "chaos-planner/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{provider} HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
    return data["choices"][0]["message"]["content"] or ""
