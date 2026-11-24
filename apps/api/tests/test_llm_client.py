"""The Anthropic wrapper, with the SDK client replaced by a stub (no network)."""

from types import SimpleNamespace
from typing import Any

import pytest
from conftest import make_result
from tutor_api.llm import AnthropicTurnLLM, LLMError
from tutor_api.llm.client import FALLBACK_BETA


class StubMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def stub_client(response: Any) -> Any:
    messages = StubMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages), messages=messages)


def response(stop_reason: str, parsed: Any = None, category: str | None = None) -> Any:
    return SimpleNamespace(
        model="m-served",
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        parsed_output=parsed,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=7,
            cache_creation_input_tokens=None,
        ),
    )


async def test_request_shape(settings):
    client = stub_client(response("end_turn", make_result()))
    llm = AnthropicTurnLLM(settings, client=client)
    out = await llm.generate_turn("SYSTEM", "USER")
    kw = client.beta.messages.kwargs
    assert kw["model"] == settings.tutor_model  # from config
    assert kw["output_config"] == {"effort": settings.tutor_effort}  # effort explicit
    assert kw["system"][0]["text"] == "SYSTEM"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["messages"] == [{"role": "user", "content": "USER"}]  # no assistant prefill
    assert "tool_choice" not in kw and "tools" not in kw
    assert kw["fallbacks"] == "default" and kw["betas"] == [FALLBACK_BETA]
    assert out.result is not None and not out.refused
    assert (out.input_tokens, out.cache_read_input_tokens, out.cache_creation_input_tokens) == (
        10,
        7,
        0,
    )


async def test_fallbacks_can_be_disabled(settings):
    settings.tutor_fallbacks = "off"
    client = stub_client(response("end_turn", make_result()))
    await AnthropicTurnLLM(settings, client=client).generate_turn("s", "u")
    assert "fallbacks" not in client.beta.messages.kwargs


async def test_refusal(settings):
    llm = AnthropicTurnLLM(settings, client=stub_client(response("refusal", category="cyber")))
    out = await llm.generate_turn("s", "u")
    assert out.refused and out.result is None and out.refusal_category == "cyber"


@pytest.mark.parametrize("stop", ["max_tokens", "end_turn"])
async def test_unusable_output_raises(settings, stop):
    llm = AnthropicTurnLLM(settings, client=stub_client(response(stop, parsed=None)))
    with pytest.raises(LLMError):
        await llm.generate_turn("s", "u")
