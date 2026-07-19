"""DeepSeek thinking-mode wrapper preserves reasoning_content for tool rounds."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.llm import DeepSeekChatOpenAI


def test_request_payload_echoes_reasoning_content_for_tool_calls():
    llm = DeepSeekChatOpenAI(
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        max_tokens=1024,
        reasoning_effort="max",
        extra_body={"thinking": {"type": "enabled"}},
    )
    messages = [
        HumanMessage(content="Analyze AAPL"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_price",
                    "args": {"ticker": "AAPL"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
            additional_kwargs={"reasoning_content": "Need live price first."},
        ),
        ToolMessage(content='{"price": 190}', tool_call_id="call_1"),
    ]

    payload = llm._get_request_payload(messages)
    assistant = next(m for m in payload["messages"] if m.get("role") == "assistant")
    assert assistant.get("tool_calls")
    assert assistant.get("reasoning_content") == "Need live price first."


def test_request_payload_adds_empty_reasoning_content_when_missing():
    llm = DeepSeekChatOpenAI(
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_price",
                    "args": {"ticker": "AAPL"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
    ]
    payload = llm._get_request_payload(messages)
    assistant = payload["messages"][0]
    assert "reasoning_content" in assistant
    assert assistant["reasoning_content"] == ""
