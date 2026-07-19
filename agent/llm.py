"""DeepSeek ChatOpenAI wrapper with thinking-mode + tool-call support.

DeepSeek thinking mode returns `reasoning_content` alongside `content`. When the
model issues tool calls, subsequent requests MUST echo `reasoning_content` or
the API returns HTTP 400. See:
https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
"""

from typing import Any, Optional, Union

import openai
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI


class DeepSeekChatOpenAI(ChatOpenAI):
    """ChatOpenAI that preserves DeepSeek `reasoning_content` across tool rounds."""

    def _create_chat_result(
        self,
        response: Union[dict, openai.BaseModel],
        generation_info: Optional[dict] = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info=generation_info)

        # Prefer the raw SDK object — model_dump may drop non-OpenAI fields.
        reasoning = None
        if isinstance(response, openai.BaseModel) and getattr(response, "choices", None):
            message = response.choices[0].message
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning is None:
                model_extra = getattr(message, "model_extra", None) or {}
                reasoning = model_extra.get("reasoning_content")
        elif isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                reasoning = msg.get("reasoning_content")

        if reasoning is not None and result.generations:
            message = result.generations[0].message
            if isinstance(message, AIMessage):
                message.additional_kwargs["reasoning_content"] = reasoning

        return result

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = payload.get("messages") or []
        originals = list(input_) if isinstance(input_, (list, tuple)) else []

        # Pair serialized assistant messages with original LC messages for kwargs.
        ai_originals = [m for m in originals if isinstance(m, AIMessage)]
        ai_idx = 0
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            original = ai_originals[ai_idx] if ai_idx < len(ai_originals) else None
            ai_idx += 1
            if not msg.get("tool_calls"):
                continue
            # DeepSeek requires the field whenever tool_calls are present.
            reasoning = ""
            if original is not None:
                reasoning = original.additional_kwargs.get("reasoning_content") or ""
            msg["reasoning_content"] = reasoning

        return payload


def build_deepseek_llm() -> DeepSeekChatOpenAI:
    """Build the portfolio agent LLM with thinking mode and large output budget."""
    from config import config

    # thinking mode ignores temperature; omit it so we don't pretend it applies.
    kwargs = dict(
        model=config.DEEPSEEK_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        max_tokens=config.DEEPSEEK_MAX_TOKENS,
        reasoning_effort=config.DEEPSEEK_REASONING_EFFORT,
        extra_body={"thinking": {"type": "enabled" if config.DEEPSEEK_THINKING else "disabled"}},
    )
    return DeepSeekChatOpenAI(**kwargs)
