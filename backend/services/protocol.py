#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协议转换层:OpenAI chat ↔ Anthropic Messages / OpenAI Responses。

网关内部统一走 OpenAI chat 格式(计量/扣费/渠道切换复用),
在网关边缘做协议进出转换。
"""
import json
import time
import uuid


# ================= Anthropic Messages =================

def _block_text(block):
    return block.get("text", "") if isinstance(block, dict) else str(block)


def anthropic_to_chat(payload: dict) -> dict:
    """Anthropic /v1/messages 请求 → OpenAI chat 请求。

    支持 system、text/image/tool_use/tool_result 内容块、tools、tool_choice、
    stop_sequences;thinking 块丢弃。
    """
    messages = []
    system = payload.get("system")
    if system:
        if isinstance(system, list):
            system = "\n".join(_block_text(b) for b in system if isinstance(b, dict))
        if str(system).strip():
            messages.append({"role": "system", "content": str(system)})

    def image_part(source):
        if not isinstance(source, dict):
            return None
        if source.get("type") == "base64":
            return {"type": "image_url",
                    "image_url": {"url": f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"}}
        if source.get("type") == "url" and source.get("url"):
            return {"type": "image_url", "image_url": {"url": source["url"]}}
        return None

    for m in payload.get("messages", []):
        role = m.get("role", "user")
        content = m.get("content")
        if not isinstance(content, list):
            messages.append({"role": role, "content": str(content or "")})
            continue
        if role == "assistant":
            texts, tool_calls = [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") in ("text", None):
                    if b.get("text"):
                        texts.append(b["text"])
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or "toolu_" + uuid.uuid4().hex[:16],
                        "type": "function",
                        "function": {"name": b.get("name") or "",
                                     "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
                # thinking 块不上送
            out = {"role": "assistant", "content": "\n".join(texts)}
            if tool_calls:
                out["tool_calls"] = tool_calls
            messages.append(out)
        else:
            parts, tool_results = [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype in ("text", None):
                    if b.get("text"):
                        parts.append({"type": "text", "text": b["text"]})
                elif btype == "image":
                    part = image_part(b.get("source"))
                    if part:
                        parts.append(part)
                elif btype == "tool_result":
                    inner = b.get("content")
                    if isinstance(inner, list):
                        inner = "\n".join(_block_text(x) for x in inner if isinstance(x, dict))
                    tool_results.append({"role": "tool",
                                         "tool_call_id": b.get("tool_use_id") or "",
                                         "content": str(inner if inner is not None else "")})
            if parts and all(p.get("type") == "text" for p in parts):
                messages.append({"role": role, "content": "\n".join(p["text"] for p in parts)})
            elif parts:
                messages.append({"role": role, "content": parts})
            elif not tool_results:
                messages.append({"role": role, "content": ""})
            for tr in tool_results:
                messages.append(tr)

    out = {"messages": messages,
           "max_tokens": payload.get("max_tokens") or 4096}
    if payload.get("temperature") is not None:
        out["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        out["top_p"] = payload["top_p"]
    if payload.get("stop_sequences"):
        out["stop"] = payload["stop_sequences"]
    tools = payload.get("tools")
    if isinstance(tools, list):
        out_tools = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            fn = {"name": t["name"]}
            if t.get("description"):
                fn["description"] = t["description"]
            if isinstance(t.get("input_schema"), dict):
                fn["parameters"] = t["input_schema"]
            out_tools.append({"type": "function", "function": fn})
        if out_tools:
            out["tools"] = out_tools
    choice = payload.get("tool_choice")
    if isinstance(choice, dict):
        ctype = choice.get("type")
        if ctype == "auto":
            out["tool_choice"] = "auto"
        elif ctype == "any":
            out["tool_choice"] = "required"
        elif ctype == "none":
            out["tool_choice"] = "none"
        elif ctype == "tool" and choice.get("name"):
            out["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    if payload.get("stream"):
        out["stream"] = True
    return out


_STOP_REASON = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def chat_to_anthropic(body: dict, model_name: str) -> dict:
    """OpenAI chat 响应 → Anthropic /v1/messages 响应(非流式)。"""
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    stop_reason = _STOP_REASON.get(choice.get("finish_reason"), "end_turn")
    usage = body.get("usage") or {}
    content = []
    text = msg.get("content")
    if isinstance(text, str):
        content.append({"type": "text", "text": text})
    elif isinstance(text, list):
        for piece in text:
            content.append({"type": "text", "text": _block_text(piece)})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        content.append({"type": "tool_use",
                        "id": tc.get("id") or "toolu_" + uuid.uuid4().hex[:16],
                        "name": fn.get("name") or "",
                        "input": args if isinstance(args, dict) else {}})
    if not content:
        content.append({"type": "text", "text": ""})
    return {
        "id": "msg_" + uuid.uuid4().hex[:24],
        "type": "message",
        "role": "assistant",
        "model": model_name,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0)},
    }


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def anthropic_sse_from_openai_stream(upstream_iter):
    """增量转换 OpenAI chat SSE 字节流 → Anthropic Messages 事件流(真流式)。

    逐行解析上游分片并即时产出事件,文本与 tool_calls 映射为动态编号的
    content block;计费由 relay 自身的观察器完成,此处只做格式转换。
    """
    parts = []
    usage = {"ptoks": 0, "ctoks": 0}
    state = {"started": False, "text_index": None, "next_index": 0,
             "tool_blocks": {}, "closed": set(), "stop_reason": "end_turn"}

    def message_start():
        if state["started"]:
            return None
        state["started"] = True
        mid = "msg_" + uuid.uuid4().hex[:24]
        return _sse("message_start", {
            "type": "message_start",
            "message": {"id": mid, "type": "message", "role": "assistant", "model": "",
                        "content": [], "stop_reason": None, "stop_sequence": None,
                        "usage": {"input_tokens": usage["ptoks"], "output_tokens": 0}}})

    def close_block(index):
        if index is None or index in state["closed"]:
            return None
        state["closed"].add(index)
        return _sse("content_block_stop", {"type": "content_block_stop", "index": index})

    yield message_start()
    buf = b""
    for chunk in upstream_iter:
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                buf = b""
                break
            try:
                obj = json.loads(data.decode("utf-8", "ignore"))
            except Exception:
                continue
            if isinstance(obj.get("usage"), dict):
                if obj["usage"].get("prompt_tokens"):
                    usage["ptoks"] = int(obj["usage"]["prompt_tokens"])
                if obj["usage"].get("completion_tokens"):
                    usage["ctoks"] = int(obj["usage"]["completion_tokens"])
            for ch in obj.get("choices") or []:
                delta = ch.get("delta") or {}
                text = delta.get("content")
                if isinstance(text, str) and text:
                    parts.append(text)
                    if state["text_index"] is None:
                        index = state["next_index"]
                        state["next_index"] += 1
                        state["text_index"] = index
                        yield _sse("content_block_start", {
                            "type": "content_block_start", "index": index,
                            "content_block": {"type": "text", "text": ""}})
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta", "index": state["text_index"],
                        "delta": {"type": "text_delta", "text": text}})
                for tc in delta.get("tool_calls") or []:
                    oi = tc.get("index", 0)
                    if oi not in state["tool_blocks"]:
                        closed = close_block(state["text_index"])
                        if closed:
                            yield closed
                            state["text_index"] = None
                        index = state["next_index"]
                        state["next_index"] += 1
                        state["tool_blocks"][oi] = index
                        fn = tc.get("function") or {}
                        yield _sse("content_block_start", {
                            "type": "content_block_start", "index": index,
                            "content_block": {"type": "tool_use",
                                              "id": tc.get("id") or "toolu_" + uuid.uuid4().hex[:16],
                                              "name": fn.get("name") or "",
                                              "input": {}}})
                    frag = (tc.get("function") or {}).get("arguments")
                    if frag:
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta", "index": state["tool_blocks"][oi],
                            "delta": {"type": "input_json_delta", "partial_json": frag}})
                if ch.get("finish_reason"):
                    state["stop_reason"] = _STOP_REASON.get(ch["finish_reason"], "end_turn")
    closed = close_block(state["text_index"])
    if closed:
        yield closed
    for index in sorted(state["tool_blocks"].values()):
        closed = close_block(index)
        if closed:
            yield closed
    text = "".join(parts)
    ctoks = usage["ctoks"] or max(1, len(text) // 3)
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": state["stop_reason"], "stop_sequence": None},
        "usage": {"input_tokens": usage["ptoks"], "output_tokens": ctoks}})
    yield _sse("message_stop", {"type": "message_stop"})


# ================= OpenAI Responses =================

def responses_to_chat(payload: dict) -> dict:
    """/v1/responses 请求(无状态文本子集)→ OpenAI chat 请求。"""
    inp = payload.get("input")
    messages = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": str(payload["instructions"])})
    if isinstance(inp, str):
        messages.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        for item in inp:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content")
                if isinstance(content, list):
                    texts = [p.get("text", "") for p in content
                             if isinstance(p, dict) and p.get("type") in ("input_text", "output_text", "text")]
                    content = "\n".join(texts)
                messages.append({"role": role, "content": str(content or "")})
    out = {"messages": messages, "max_tokens": payload.get("max_output_tokens") or 4096}
    if payload.get("temperature") is not None:
        out["temperature"] = payload["temperature"]
    if payload.get("stream"):
        out["stream"] = True
    return out


def chat_to_responses(body: dict, model_name: str) -> dict:
    """OpenAI chat 响应 → /v1/responses 响应(无状态文本子集)。"""
    choice = (body.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    usage = body.get("usage") or {}
    return {
        "id": "resp_" + uuid.uuid4().hex[:24],
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model_name,
        "output": [{"type": "message", "id": "msg_" + uuid.uuid4().hex[:12],
                    "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0),
                  "total_tokens": usage.get("total_tokens", 0)},
        "output_text": text,
    }


def openai_chunks_to_responses(upstream_iter, model_name: str):
    """OpenAI SSE → Responses SSE(response.created / output_text.delta / response.completed)。"""
    parts = []
    usage = {"ptoks": 0, "ctoks": 0}

    def consume():
        buf = b""
        for chunk in upstream_iter:
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    return
                try:
                    obj = json.loads(data.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if isinstance(obj.get("usage"), dict):
                    usage["ptoks"] = int(obj["usage"].get("prompt_tokens") or usage["ptoks"])
                    usage["ctoks"] = int(obj["usage"].get("completion_tokens") or usage["ctoks"])
                for ch in obj.get("choices") or []:
                    delta = (ch.get("delta") or {}).get("content")
                    if isinstance(delta, str) and delta:
                        parts.append(delta)

    rid = "resp_" + uuid.uuid4().hex[:24]

    def sse(t, data):
        return f"event: {t}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    def events():
        yield sse("response.created", {"type": "response.created",
                                       "response": {"id": rid, "object": "response",
                                                    "status": "in_progress", "model": model_name}})
        consume()
        for piece in parts:
            yield sse("response.output_text.delta",
                      {"type": "response.output_text.delta", "item_id": "msg_0",
                       "output_index": 0, "content_index": 0, "delta": piece})
        text = "".join(parts)
        ctoks = usage["ctoks"] or max(1, len(text) // 3)
        yield sse("response.completed", {
            "type": "response.completed",
            "response": {"id": rid, "object": "response", "status": "completed",
                         "model": model_name, "output": [],
                         "output_text": text,
                         "usage": {"input_tokens": usage["ptoks"], "output_tokens": ctoks}}})

    return events
