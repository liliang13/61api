"""协议转换:Anthropic Messages ↔ OpenAI chat,含真流式与 count_tokens 端点。"""
import json
import sys
from pathlib import Path

import pytest
from flask import Flask

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from extensions import db, hash_api_key
from models import ApiKey, User

RAW_KEY = "sk-test-cc-1234567890"


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (tmp_path / "protocol-test.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    from api.gateway import bp
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def raw_key(app):
    with app.app_context():
        user = User(username="cc-user", status=1, quota=1000, token_version=0,
                    invite_code="CC00001")
        db.session.add(user)
        db.session.flush()
        db.session.add(ApiKey(user_id=user.id, key=hash_api_key(RAW_KEY),
                              key_prefix=RAW_KEY[:8], key_last4=RAW_KEY[-4:],
                              status=1, quota_limit=-1))
        db.session.commit()
    return RAW_KEY


def test_anthropic_to_chat_maps_system_tools_images_and_tool_results():
    from services.protocol import anthropic_to_chat

    payload = {
        "model": "any", "max_tokens": 100,
        "system": [{"type": "text", "text": "你是助手"}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "看图"},
                                         {"type": "image", "source": {"type": "base64",
                                                                      "media_type": "image/png",
                                                                      "data": "AAAA"}}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1",
                                               "name": "get_weather", "input": {"city": "北京"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": "晴 25 度"}]},
        ],
        "tools": [{"name": "get_weather", "description": "查天气",
                   "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "auto"},
        "stop_sequences": ["END"],
    }
    chat = anthropic_to_chat(payload)
    assert chat["messages"][0] == {"role": "system", "content": "你是助手"}
    assert chat["messages"][1]["content"][0] == {"type": "text", "text": "看图"}
    assert chat["messages"][1]["content"][1]["type"] == "image_url"
    assert chat["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,AAAA")
    assert chat["messages"][2]["role"] == "assistant"
    assert chat["messages"][2]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(chat["messages"][2]["tool_calls"][0]["function"]["arguments"]) == {"city": "北京"}
    assert chat["messages"][3] == {"role": "tool", "tool_call_id": "toolu_1", "content": "晴 25 度"}
    assert chat["tools"] == [{"type": "function",
                              "function": {"name": "get_weather", "description": "查天气",
                                           "parameters": {"type": "object"}}}]
    assert chat["tool_choice"] == "auto"
    assert chat["stop"] == ["END"]
    assert chat["max_tokens"] == 100


def test_chat_to_anthropic_maps_tool_calls():
    from services.protocol import chat_to_anthropic

    body = {"choices": [{"message": {"content": "查一下",
                                     "tool_calls": [{"id": "call_1",
                                                     "function": {"name": "get_weather",
                                                                  "arguments": "{\"city\": \"北京\"}"}}]},
                         "finish_reason": "tool_calls"}],
           "usage": {"prompt_tokens": 11, "completion_tokens": 7}}
    resp = chat_to_anthropic(body, "m1")
    assert resp["type"] == "message" and resp["role"] == "assistant"
    assert resp["stop_reason"] == "tool_use"
    assert resp["content"][0] == {"type": "text", "text": "查一下"}
    assert resp["content"][1]["type"] == "tool_use"
    assert resp["content"][1]["name"] == "get_weather"
    assert resp["content"][1]["input"] == {"city": "北京"}
    assert resp["usage"] == {"input_tokens": 11, "output_tokens": 7}


def test_stream_converter_is_incremental_and_handles_tools():
    from services.protocol import anthropic_sse_from_openai_stream

    consumed = []

    def upstream():
        chunks = [
            'data: {"choices":[{"delta":{"role":"assistant","content":"你"}}]}\n\n'.encode("utf-8"),
            'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'.encode("utf-8"),
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"get_weather","arguments":"{\\"city\\": "}}]}}]}\n\n'.encode("utf-8"),
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments": "\\"北京\\"}"}}]}}]}\n\n'.encode("utf-8"),
            b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":9,"completion_tokens":6}}\n\n',
            b'data: [DONE]\n\n',
        ]
        for chunk in chunks:
            encoded = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            consumed.append(encoded)
            yield encoded

    gen = anthropic_sse_from_openai_stream(upstream())
    first = next(gen).decode()
    assert first.startswith("event: message_start")     # 首事件无需等待上游,立即返回
    assert consumed == []
    second = next(gen).decode()                         # 拉取第二个事件才消费上游首块
    assert len(consumed) == 1
    assert "content_block_start" in second

    events = [first] + [second] + [ev.decode() for ev in gen]
    kinds = [line[7:].splitlines()[0] for line in events if line.startswith("event: ")]
    assert kinds == ["message_start", "content_block_start", "content_block_delta",
                     "content_block_delta", "content_block_stop", "content_block_start",
                     "content_block_delta", "content_block_delta", "content_block_stop",
                     "message_delta", "message_stop"]

    def datas():
        for line in events:
            for ln in line.splitlines():
                if ln.startswith("data: "):
                    yield json.loads(ln[6:])

    items = list(datas())
    tool_start = next(d for d in items if d.get("type") == "content_block_start"
                      and d["content_block"]["type"] == "tool_use")
    assert tool_start["content_block"]["name"] == "get_weather"
    frags = [d["delta"]["partial_json"] for d in items if d.get("type") == "content_block_delta"
             and d["delta"]["type"] == "input_json_delta"]
    assert json.loads("".join(frags)) == {"city": "北京"}
    final = next(d for d in items if d.get("type") == "message_delta")
    assert final["delta"]["stop_reason"] == "tool_use"
    assert final["usage"] == {"input_tokens": 9, "output_tokens": 6}


def test_messages_endpoints_auth_and_count_tokens(app, raw_key):
    client = app.test_client()

    bad = client.post("/v1/messages", json={"model": "m", "max_tokens": 10,
                                            "messages": [{"role": "user", "content": "hi"}]})
    assert bad.status_code == 401
    assert bad.get_json()["type"] == "error"
    assert bad.get_json()["error"]["type"] == "authentication_error"

    ok = client.post("/v1/messages/count_tokens", headers={"x-api-key": raw_key},
                     json={"model": "m", "max_tokens": 10,
                           "messages": [{"role": "user", "content": "你好,帮我查一下天气"}]})
    assert ok.status_code == 200
    assert ok.get_json()["input_tokens"] >= 1
