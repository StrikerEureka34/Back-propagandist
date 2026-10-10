import io
import json

import pytest

import llm as llm_mod


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _fake_urlopen(captured):
    def urlopen(req, timeout=None):
        captured["url"], captured["headers"], captured["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
        return _Resp(json.dumps({"choices": [{"message": {"content": "pick cart-wipe"}}]}).encode())
    return urlopen


@pytest.mark.parametrize("provider,host,key_var", [
    ("groq", "api.groq.com", "GROQ_API_KEY"),
    ("groq2", "api.groq.com", "GROQ_API_KEY_2"),
    ("groq3", "api.groq.com", "GROQ_API_KEY_3"),
    ("openrouter", "openrouter.ai", "OPENROUTER_API_KEY"),
])
def test_openai_style_provider_call(monkeypatch, provider, host, key_var):
    seen = {}
    monkeypatch.setenv(key_var, "k-123")
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", _fake_urlopen(seen))
    out = llm_mod.llm("which experiment?", system="be brief", provider=provider)
    assert out == "pick cart-wipe"
    assert host in seen["url"] and seen["url"].endswith("/chat/completions")
    assert seen["headers"]["Authorization"] == "Bearer k-123"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_provider_and_model_from_env(monkeypatch):
    seen = {}
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", _fake_urlopen(seen))
    llm_mod.llm("hi")
    assert seen["body"]["model"] == "some-model"


def test_missing_key_and_unknown_provider(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        llm_mod.llm("hi", provider="groq")
    with pytest.raises(ValueError, match="unknown provider"):
        llm_mod.llm("hi", provider="nope")
