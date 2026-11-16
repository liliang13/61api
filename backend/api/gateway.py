#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容网关:/v1/chat/completions、/v1/embeddings、/v1/models。鉴权用 sk- 开头的 API Key。"""
import json
from datetime import datetime

from flask import Blueprint, Response, request, stream_with_context

from extensions import check_rate_limit, db, err
from models import ApiKey, User
from services.relay import (gateway_error, list_models_for_key, run_chat, run_embeddings,
                            validate_messages)

bp = Blueprint("gateway", __name__)


def _lookup_key(token):
    if not token:
        return None, None
    from extensions import hash_api_key
    rec = ApiKey.query.filter_by(key=hash_api_key(token), status=1).first()
    if not rec:
        return None, None
    user = db.session.get(User, rec.user_id)
    if not user or user.status != 1:
        return None, None
    return user, rec


def _auth_key():
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    return _lookup_key(token)


def _guard(user, key, payload=None):
    """公共校验:返回错误 Response 或 None。密钥限额为硬顶,达到即拦。

    余额为零但持有该模型可用资源包时放行,真实额度由 reserve 冻结时把关。
    """
    if not user:
        return gateway_error("无效的 API Key", "authentication_error", 401)
    if user.quota <= 0:
        from services.billing import user_has_pack_for
        model = payload.get("model") if isinstance(payload, dict) else None
        if not user_has_pack_for(user.id, str(model).strip() if model else None):
            return gateway_error("余额不足,请先充值", "insufficient_quota", 402)
    if 0 < key.quota_limit <= key.used_quota:
        return gateway_error("该密钥额度已用尽", "insufficient_quota", 402)
    import config
    if not check_rate_limit("gateway", key.id, config.GATEWAY_RATE_LIMIT_PER_MINUTE,
                            config.GATEWAY_RATE_LIMIT_WINDOW_SECONDS):
        return gateway_error("请求过于频繁,请稍后重试", "rate_limit_exceeded", 429)
    if not isinstance(payload, dict) or not payload.get("model"): 
        return gateway_error("缺少 model 字段", "invalid_request_error")
    return None


@bp.post("/v1/chat/completions")
def chat_completions():
    user, key = _auth_key()
    payload = request.get_json(silent=True)
    bad = _guard(user, key, payload)
    if bad:
        return bad
    model = str(payload.get("model")).strip()
    stream = bool(payload.get("stream"))
    return run_chat(user=user, api_key=key, model_name=model,
                    payload=payload, stream=stream)


@bp.post("/v1/embeddings")
def embeddings():
    user, key = _auth_key()
    payload = request.get_json(silent=True)
    bad = _guard(user, key, payload)
    if bad:
        return bad
    if not payload.get("input"):
        return gateway_error("缺少 input 字段", "invalid_request_error")
    model = str(payload.get("model")).strip()
    return run_embeddings(user=user, api_key=key, model_name=model, payload=payload)


def _auth_key_loose():
    """兼容 Anthropic 客户端:支持 x-api-key 头与 Authorization Bearer。"""
    auth = request.headers.get("Authorization", "")
    xkey = request.headers.get("x-api-key", "")
    token = (xkey or (auth[7:].strip() if auth.startswith("Bearer ") else "")).strip()
    return _lookup_key(token)


@bp.post("/v1/messages")
def anthropic_messages():
    """Anthropic Messages API 兼容端点(Claude Code / Cline 等客户端直连)。

    网关内部走 OpenAI 协议(计费/渠道切换复用),边缘做协议转换。
    """
    from services import protocol
    user, key = _auth_key_loose()
    payload = request.get_json(silent=True)
    bad = _guard(user, key, payload)
    if bad:
        # Anthropic 客户端按 {"type":"error",...} 解析错误,统一转格式
        body = bad.get_json(silent=True) or {}
        inner = body.get("error") if isinstance(body.get("error"), dict) else {}
        return Response(json.dumps({"type": "error",
                                    "error": {"type": inner.get("type", "api_error"),
                                              "message": inner.get("message") or "请求被拒绝"}},
                                   ensure_ascii=False),
                        status=bad.status_code, mimetype="application/json")
    invalid = validate_messages(payload.get("messages"))
    if invalid:
        return gateway_error(invalid)
    model = str(payload.get("model")).strip()
    stream = bool(payload.get("stream"))
    chat_payload = protocol.anthropic_to_chat(payload)
    result = run_chat(user=user, api_key=key, model_name=model,
                      payload=chat_payload, stream=stream)
    if stream and result.status_code == 200:
        # result 是 OpenAI SSE Response;包一层逐块转成 Anthropic 事件流(真流式)
        def converted():
            from services.protocol import anthropic_sse_from_openai_stream
            for ev in anthropic_sse_from_openai_stream(iter(result.response)):
                yield ev
        resp = Response(stream_with_context(converted()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp
    if isinstance(result, Response):  # 错误透传
        return result
    body, status = result
    if status != 200:
        # 转成 Anthropic 错误格式
        err_body = body if isinstance(body, dict) else {}
        msg = (err_body.get("error") or {}).get("message") if isinstance(err_body.get("error"), dict) else str(err_body)[:300]
        return Response(json.dumps({"type": "error",
                                    "error": {"type": "api_error", "message": msg or "上游错误"}},
                                   ensure_ascii=False), status=status, mimetype="application/json")
    return Response(json.dumps(protocol.chat_to_anthropic(body, model), ensure_ascii=False),
                    mimetype="application/json")


@bp.post("/v1/messages/count_tokens")
def anthropic_count_tokens():
    """Anthropic count_tokens:按网关估算口径返回 input_tokens。"""
    from services.billing import estimate_tokens
    from services import protocol
    user, key = _auth_key_loose()
    payload = request.get_json(silent=True)
    bad = _guard(user, key, payload)
    if bad:
        return bad
    chat = protocol.anthropic_to_chat(payload)
    total = 0
    for m in chat.get("messages", []):
        content = m.get("content")
        if isinstance(content, list):
            total += sum(estimate_tokens(p.get("text", "") if isinstance(p, dict) else str(p))
                         for p in content)
        else:
            total += estimate_tokens(str(content))
        total += 4  # 每条消息的结构开销
    if chat.get("tools"):
        total += estimate_tokens(json.dumps(chat["tools"], ensure_ascii=False))
    return Response(json.dumps({"input_tokens": max(1, total)}, ensure_ascii=False),
                    mimetype="application/json")


@bp.post("/v1/responses")
def openai_responses():
    """OpenAI Responses API 兼容端点(无状态文本子集,Codex 等新客户端)。"""
    from services import protocol
    user, key = _auth_key()
    payload = request.get_json(silent=True)
    bad = _guard(user, key, payload)
    if bad:
        return bad
    model = str(payload.get("model")).strip()
    stream = bool(payload.get("stream"))
    chat_payload = protocol.responses_to_chat(payload)
    result = run_chat(user=user, api_key=key, model_name=model,
                      payload=chat_payload, stream=stream)
    if stream and result.status_code == 200:
        def converted():
            for ev in protocol.openai_chunks_to_responses(iter(result.response), model)():
                yield ev
        resp = Response(stream_with_context(converted()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp
    if isinstance(result, Response):
        return result
    body, status = result
    if status != 200:
        return Response(json.dumps(body, ensure_ascii=False),
                        status=status, mimetype="application/json")
    return Response(json.dumps(protocol.chat_to_responses(body, model), ensure_ascii=False),
                    mimetype="application/json")


@bp.get("/v1/models")
def v1_models():
    user, key = _auth_key()
    if not user:
        return gateway_error("无效的 API Key", "authentication_error", 401)
    return Response(json.dumps({"object": "list", "data": list_models_for_key()},
                               ensure_ascii=False), mimetype="application/json")
