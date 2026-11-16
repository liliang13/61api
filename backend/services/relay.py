#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转发网关:先原子预留额度,再调用上游,最后按实际用量结算。"""
import json
import random
import time
from types import SimpleNamespace

import requests
from flask import Response, current_app, stream_with_context

from extensions import db
from models import Channel, ModelItem
from services import breaker
from services.billing import (BillingError, abort, compute_cost, conservative_tokens,
                              estimate_tokens, reserve, settle)

UA = "61API-Gateway/1.0"
MOCK_REPLY = ("你好!我是 61API 内置演示渠道(mock)返回的消息。\n\n"
              "这条回复走完了完整的网关流程:鉴权 → 渠道选择 → 计量 → 扣费 → 用量落库,\n"
              "所以你可以在控制台的「用量日志」和「余额」里看到这次调用的效果。\n\n"
              "在「管理后台 → 渠道管理」里添加真实上游(OpenAI 兼容)后,同样的请求会被转发到真实模型。")
MAX_ATTEMPTS = 3
RETRY_STATUS = {401, 403, 408, 429, 500, 502, 503, 504}
# 上游 400 里属于"渠道不承接此模型"的错误特征:命中则换下一渠道而非怼回用户
MODEL_GONE_PATTERNS = ("invalid model", "model not found", "model_not_found",
                       "does not exist", "no such model", "该模型不存在", "无可用模型")


def attempt_order(model_name: str, limit: int = MAX_ATTEMPTS):
    rows = Channel.query.filter_by(status=1).order_by(Channel.priority.asc()).all()
    cands = [c for c in rows
             if ("*" in c.model_list() or model_name in c.model_list())
             and not breaker.is_open(c.id)]
    groups = {}
    for channel in cands:
        groups.setdefault(channel.priority, []).append(channel)
    order = []
    for priority in sorted(groups):
        group = list(groups[priority])
        while group:
            total = sum(max(1, c.weight) for c in group)
            pick = random.uniform(0, total)
            acc = 0
            picked = group[-1]
            for channel in group:
                acc += max(1, channel.weight)
                if pick <= acc:
                    picked = channel
                    break
            order.append(picked)
            group.remove(picked)
    return order[:limit]


def _cache_hit_of(usage: dict) -> int:
    if not isinstance(usage, dict):
        return 0
    hit = usage.get("prompt_cache_hit_tokens")
    if hit is None:
        hit = usage.get("cache_read_input_tokens")
    if hit is None:
        hit = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
    return _usage_int(hit)


def _usage_int(value, default=0):
    if value is None:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _est_prompt_tokens(payload: dict) -> int:
    total = ""
    for message in payload.get("messages", []):
        content = message.get("content")
        if isinstance(content, str):
            total += content
        elif isinstance(content, list):
            total += "".join(part.get("text", "") for part in content
                             if isinstance(part, dict) and isinstance(part.get("text", ""), str))
    return estimate_tokens(total)


def gateway_error(message: str, err_type: str = "invalid_request_error", status: int = 400):
    return Response(json.dumps({"error": {"message": message, "type": err_type}}, ensure_ascii=False),
                    status=status, mimetype="application/json")


def validate_messages(messages):
    if not isinstance(messages, list) or not messages:
        return "messages 必须是非空数组"
    for message in messages:
        if not isinstance(message, dict):
            return "messages 中的每一项必须是对象"
        if not isinstance(message.get("role"), str) or not message.get("role").strip():
            return "每条消息必须包含 role"
        content = message.get("content")
        if content is None and message.get("tool_calls"):
            continue
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            return "消息 content 必须是字符串或内容块数组"
        for part in content:
            if not isinstance(part, dict):
                return "消息内容块必须是对象"
            if "text" in part and not isinstance(part["text"], str):
                return "消息内容块 text 必须是字符串"
    return None


def _default_output_tokens():
    import config
    fallback = (getattr(config, "DEFAULT_MAX_OUTPUT_TOKENS", None)
                or getattr(config, "MAX_OUTPUT_TOKENS", None) or 4096)
    value = current_app.config.get("DEFAULT_MAX_OUTPUT_TOKENS",
                                   current_app.config.get("MAX_OUTPUT_TOKENS", fallback))
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        value = 4096
    return value if value > 0 else 4096


def _chat_output_limit(payload):
    supplied = [name for name in ("max_tokens", "max_completion_tokens") if name in payload]
    if len(supplied) > 1:
        return None, "max_tokens 与 max_completion_tokens 不能同时指定"
    if not supplied:
        return _default_output_tokens(), None
    value = payload[supplied[0]]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None, f"{supplied[0]} 必须是正整数"
    return value, None


def _prepare_chat(payload, stream):
    if not isinstance(payload, dict):
        return None, None, "请求体必须是 JSON 对象"
    invalid = validate_messages(payload.get("messages"))
    if invalid:
        return None, None, invalid
    output_limit, invalid = _chat_output_limit(payload)
    if invalid:
        return None, None, invalid
    prepared = dict(payload)
    prepared.pop("stream_options", None)
    prepared["stream"] = bool(stream)
    if "max_completion_tokens" not in prepared:
        prepared["max_tokens"] = output_limit
    return prepared, output_limit, None


def _billing_response(exc):
    return gateway_error(str(exc), exc.code, exc.status)


def _result_status(result):
    return result[1] if isinstance(result, tuple) else result.status_code


def _release_failed(reservation, message):
    try:
        abort(reservation, error_msg=message, status="error")
        return None
    except BillingError as exc:
        current_app.logger.exception("Failed to release billing reservation")
        return _billing_response(exc)


def _item_snapshot(item):
    return SimpleNamespace(name=item.name, input_price=item.input_price or 0,
                           output_price=item.output_price or 0,
                           cache_input_price=item.cache_input_price or 0)


def _channel_snapshot(channel):
    return SimpleNamespace(id=channel.id, type=channel.type, base_url=channel.base_url,
                           api_key=channel.api_key, model_map=channel.model_mapping())


def _mapped_model(channel, payload: dict) -> dict:
    """发送体按渠道映射改写模型名(目录名 → 上游名);不改共享 payload。

    兼容两种载体:选路快照(SimpleNamespace.model_map=dict)与 ORM Channel(model_mapping())。
    """
    mapping = channel.model_mapping() if hasattr(channel, "model_mapping") \
        else (channel.model_map or {})
    sent = dict(payload)
    name = sent.get("model") or ""
    sent["model"] = mapping.get(name, name)
    return sent


def run_chat(*, user, api_key, model_name: str, payload: dict, stream: bool):
    item = ModelItem.query.filter_by(name=model_name, status=1).first()
    if not item:
        return gateway_error(f"模型 {model_name} 不存在或未开放", "invalid_request_error", 404)
    item = _item_snapshot(item)
    payload, output_limit, invalid = _prepare_chat(payload, stream)
    if invalid:
        return gateway_error(invalid)
    candidates = [_channel_snapshot(c) for c in attempt_order(model_name)]
    if not candidates:
        return gateway_error("无可用上游渠道,请联系管理员", "api_error", 503)
    payload["model"] = model_name
    start = time.time()
    try:
        reservation = reserve(user=user, api_key=api_key, channel=candidates[0], item=item,
                              prompt_tokens=conservative_tokens(payload["messages"]),
                              completion_tokens=output_limit, stream=stream)
    except BillingError as exc:
        return _billing_response(exc)
    try:
        mock = next((c for c in candidates if c.type == "mock"), None)
        if mock:
            result = _run_mock(reservation, mock, item, payload, stream, start)
            last_err = ""
        else:
            result, last_err = _run_upstream(reservation, item, payload, stream, start, candidates)
        if _result_status(result) != 200:
            released = _release_failed(reservation, last_err or "upstream request failed")
            return released or result
        return result
    except BillingError as exc:
        return _billing_response(exc)
    except Exception:
        current_app.logger.exception("Chat relay failed")
        released = _release_failed(reservation, "relay failed")
        return released or gateway_error("上游调用失败", "api_error", 502)


def _run_mock(reservation, channel, item, payload, stream, start):
    prompt_tokens = _est_prompt_tokens(payload)
    if stream:
        observer = _SseObserver()

        def gen():
            try:
                for piece in _sse_stream_mock(payload, prompt_tokens):
                    encoded = piece.encode("utf-8")
                    observer.feed(encoded)
                    yield encoded
            finally:
                latency = int((time.time() - start) * 1000)
                usage = observer.usage or {}
                actual_prompt = _usage_int(usage.get("prompt_tokens"), prompt_tokens)
                completion = _usage_int(usage.get("completion_tokens"),
                                        estimate_tokens(observer.completion_text))
                try:
                    settle(reservation, channel=channel, item=item,
                           prompt_tokens=actual_prompt, completion_tokens=completion,
                           latency_ms=latency, stream=True, cache_hit=observer.cache_hit,
                           source="upstream" if observer.usage else "estimated")
                except BillingError:
                    current_app.logger.exception("Failed to settle mock stream")
                    raise

        response = Response(stream_with_context(gen()), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response

    completion_tokens = estimate_tokens(MOCK_REPLY)
    body = {
        "id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
        "model": item.name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": MOCK_REPLY},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }
    settle(reservation, channel=channel, item=item, prompt_tokens=prompt_tokens,
           completion_tokens=completion_tokens, latency_ms=int((time.time() - start) * 1000))
    return body, 200


def _sse_stream_mock(payload, prompt_tokens):
    pieces = [MOCK_REPLY[i:i + 8] for i in range(0, len(MOCK_REPLY), 8)]
    completion_id = "chatcmpl-mock-" + str(random.randint(10 ** 8, 10 ** 9 - 1))
    created = int(time.time())

    def chunk(delta, finish=None):
        return "data: " + json.dumps({
            "id": completion_id, "object": "chat.completion.chunk", "created": created,
            "model": payload.get("model"),
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }, ensure_ascii=False) + "\n\n"

    yield chunk({"role": "assistant"})
    for piece in pieces:
        yield chunk({"content": piece})
        time.sleep(0.02)
    yield chunk({}, finish="stop")
    completion_tokens = estimate_tokens(MOCK_REPLY)
    yield "data: " + json.dumps({
        "id": completion_id, "object": "chat.completion.chunk", "created": created,
        "model": payload.get("model"), "choices": [],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }) + "\n\n"
    yield "data: [DONE]\n\n"


class _SseObserver:
    def __init__(self):
        self.buf = b""
        self.usage = None
        self.content_parts = []

    @property
    def cache_hit(self):
        return _cache_hit_of(self.usage or {})

    def feed(self, chunk: bytes):
        self.buf += chunk
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            self._line(line.strip())

    def _line(self, line: bytes):
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if data == b"[DONE]" or not data:
            return
        try:
            obj = json.loads(data.decode("utf-8", "ignore"))
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        if isinstance(obj.get("usage"), dict):
            self.usage = obj["usage"]
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = (choice.get("delta") or {}).get("content")
            if isinstance(delta, str):
                self.content_parts.append(delta)

    @property
    def completion_text(self):
        return "".join(self.content_parts)


def _classify_upstream_error(response):
    """非 200 响应分类为 (retry, 描述) 或 (reject, 描述)。

    "模型不存在"类 400 视为渠道配置问题走切换(自愈路径);上下文超限等其他
    4xx 属于客户端错误,直接返回用户,避免同一请求反复打满候选渠道。
    """
    status = response.status_code
    try:
        body = (response.text or "")[:500]
    except Exception:
        body = ""
    detail = f"upstream {status}"
    snippet = body.strip().replace("\n", " ")[:200]
    if snippet:
        detail = f"{detail}: {snippet}"
    if status == 400 and any(p in body.lower() for p in MODEL_GONE_PATTERNS):
        return "retry", f"该渠道不承接此模型({detail})"
    return ("retry", detail) if status in RETRY_STATUS else ("reject", detail)


def _log_failover(channel_id, request_id, detail):
    """失败切换留痕到 channel_events;写失败不影响主请求。"""
    try:
        from models import ChannelEvent
        db.session.add(ChannelEvent(channel_id=channel_id, kind="failover",
                                    message=(detail or "")[:500], request_id=request_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to record failover event")


def _run_upstream(reservation, item, payload, stream, start, candidates):
    last_err = ""
    for channel in candidates:
        phase, data = _try_upstream_once(channel, payload, stream)
        if phase == "retry":
            _log_failover(channel.id, reservation.request_id, data)
            breaker.record_fail(channel.id, data)
            last_err = data
            continue
        if phase == "reject":
            breaker.record_success(channel.id)
            detail, status = data
            return gateway_error("上游请求被拒绝", "api_error", status), detail
        breaker.record_success(channel.id)
        return _finish_ok(reservation, channel, item, payload, data, stream, start), ""
    return gateway_error(f"所有上游渠道均不可用({last_err or '无候选渠道'})", "api_error", 502), last_err


def _try_upstream_once(channel, payload, stream):
    from services.network import validate_upstream_url
    try:
        url = validate_upstream_url(channel.base_url) + "/chat/completions"
    except ValueError:
        return "retry", "invalid upstream URL"
    headers = {"Authorization": f"Bearer {channel.api_key}",
               "Content-Type": "application/json", "User-Agent": UA}
    if stream:
        payload.setdefault("stream_options", {"include_usage": True})
    try:
        upstream = requests.post(url, json=_mapped_model(channel, payload), headers=headers,
                                 stream=stream, timeout=(10, 300), allow_redirects=False)
    except Exception as exc:
        return "retry", f"connect: {exc}"
    if upstream.status_code == 200:
        return "ok", upstream
    try:
        phase, detail = _classify_upstream_error(upstream)
        if phase == "retry":
            return "retry", detail
        return "reject", (detail, upstream.status_code)
    finally:
        upstream.close()


def _finish_ok(reservation, channel, item, payload, upstream, stream, start):
    if not stream:
        try:
            try:
                body = upstream.json()
            except Exception:
                return gateway_error("上游返回非 JSON", "api_error", 502)
        finally:
            upstream.close()
        if not isinstance(body, dict):
            return gateway_error("上游返回格式错误", "api_error", 502)
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        source = "upstream" if usage.get("prompt_tokens") else "estimated"
        prompt_tokens = _usage_int(usage.get("prompt_tokens"), _est_prompt_tokens(payload))
        choices = body.get("choices") or [{}]
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        content = (choice.get("message") or {}).get("content", "")
        completion_tokens = _usage_int(usage.get("completion_tokens"),
                                       estimate_tokens(content if isinstance(content, str) else ""))
        settle(reservation, channel=channel, item=item, prompt_tokens=prompt_tokens,
               completion_tokens=completion_tokens, latency_ms=int((time.time() - start) * 1000),
               cache_hit=_cache_hit_of(usage), source=source)
        body.setdefault("usage", {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                                  "total_tokens": prompt_tokens + completion_tokens})
        return body, 200

    observer = _SseObserver()

    def gen():
        try:
            for chunk in upstream.iter_content(chunk_size=1024):
                if chunk:
                    observer.feed(chunk)
                    yield chunk
        finally:
            upstream.close()
            latency = int((time.time() - start) * 1000)
            source = "upstream" if observer.usage else "estimated"
            if observer.usage:
                prompt_tokens = _usage_int(observer.usage.get("prompt_tokens"))
                completion_tokens = _usage_int(observer.usage.get("completion_tokens"))
            else:
                prompt_tokens = _est_prompt_tokens(payload)
                completion_tokens = estimate_tokens(observer.completion_text)
            try:
                settle(reservation, channel=channel, item=item, prompt_tokens=prompt_tokens,
                       completion_tokens=completion_tokens, latency_ms=latency, stream=True,
                       cache_hit=observer.cache_hit, source=source)
            except BillingError:
                current_app.logger.exception("Failed to settle upstream stream")
                raise

    response = Response(stream_with_context(gen()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _mock_vector(text: str, salt: str = "") -> list:
    import hashlib
    digest = hashlib.sha256((salt + text).encode("utf-8")).digest()
    return [round(((digest[i % 32] / 255.0) - 0.5) * 2, 6) for i in range(256)]


def run_embeddings(*, user, api_key, model_name: str, payload: dict):
    item = ModelItem.query.filter_by(name=model_name, status=1).first()
    if not item:
        return gateway_error(f"模型 {model_name} 不存在或未开放", "invalid_request_error", 404)
    raw = payload.get("input") if isinstance(payload, dict) else None
    if not isinstance(raw, (str, list)) or raw == "" or raw == []:
        return gateway_error("input 必须是字符串或非空数组")
    candidates = attempt_order(model_name)
    if not candidates:
        return gateway_error("无可用上游渠道,请联系管理员", "api_error", 503)
    start = time.time()
    try:
        reservation = reserve(user=user, api_key=api_key, channel=candidates[0], item=item,
                              prompt_tokens=conservative_tokens(raw), completion_tokens=0)
    except BillingError as exc:
        return _billing_response(exc)
    try:
        mock = next((c for c in candidates if c.type == "mock"), None)
        if mock:
            result = _run_mock_embeddings(reservation, mock, item, payload, raw, start)
            last_err = ""
        else:
            result, last_err = _run_upstream_embeddings(reservation, item, payload, raw, start, candidates)
        if _result_status(result) != 200:
            released = _release_failed(reservation, last_err or "embedding request failed")
            return released or result
        return result
    except BillingError as exc:
        return _billing_response(exc)
    except Exception:
        current_app.logger.exception("Embedding relay failed")
        released = _release_failed(reservation, "relay failed")
        return released or gateway_error("上游调用失败", "api_error", 502)


def _run_mock_embeddings(reservation, channel, item, payload, raw, start):
    inputs = raw if isinstance(raw, list) else [raw]
    prompt_tokens = max(1, estimate_tokens("".join(str(x) for x in inputs)))
    data = [{"object": "embedding", "index": i,
             "embedding": _mock_vector(str(value), item.name)} for i, value in enumerate(inputs)]
    body = {"object": "list", "data": data, "model": item.name,
            "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens}}
    settle(reservation, channel=channel, item=item, prompt_tokens=prompt_tokens,
           completion_tokens=0, latency_ms=int((time.time() - start) * 1000))
    return body, 200


def _run_upstream_embeddings(reservation, item, payload, raw, start, candidates):
    from services.network import validate_upstream_url
    last_err = ""
    for channel in candidates:
        try:
            url = validate_upstream_url(channel.base_url) + "/embeddings"
        except ValueError:
            detail = "invalid upstream URL"
            _log_failover(channel.id, reservation.request_id, detail)
            breaker.record_fail(channel.id, detail)
            last_err = detail
            continue
        headers = {"Authorization": f"Bearer {channel.api_key}",
                   "Content-Type": "application/json", "User-Agent": UA}
        try:
            upstream = requests.post(url, json=_mapped_model(channel, payload), headers=headers,
                                     timeout=(10, 120), allow_redirects=False)
        except Exception as exc:
            detail = f"connect: {exc}"
            _log_failover(channel.id, reservation.request_id, detail)
            breaker.record_fail(channel.id, detail)
            last_err = detail
            continue
        if upstream.status_code != 200:
            try:
                phase, detail = _classify_upstream_error(upstream)
                if phase == "retry":
                    _log_failover(channel.id, reservation.request_id, detail)
                    breaker.record_fail(channel.id, detail)
                    last_err = detail
                    continue
                breaker.record_success(channel.id)
                return gateway_error("上游请求被拒绝", "api_error", upstream.status_code), detail
            finally:
                upstream.close()
        breaker.record_success(channel.id)
        try:
            try:
                body = upstream.json()
            except Exception:
                detail = "上游返回非 JSON"
                return gateway_error(detail, "api_error", 502), detail
        finally:
            upstream.close()
        if not isinstance(body, dict):
            detail = "上游返回格式错误"
            return gateway_error(detail, "api_error", 502), detail
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = _usage_int(usage.get("prompt_tokens"),
                                   estimate_tokens(json.dumps(raw, ensure_ascii=False)))
        settle(reservation, channel=channel, item=item, prompt_tokens=prompt_tokens,
               completion_tokens=0, latency_ms=int((time.time() - start) * 1000))
        body.setdefault("usage", {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens})
        return (body, 200), ""
    return gateway_error(f"所有上游渠道均不可用({last_err or '无候选渠道'})", "api_error", 502), last_err


def list_models_for_key() -> list:
    items = ModelItem.query.filter_by(status=1).order_by(ModelItem.sort.asc(), ModelItem.id.asc()).all()
    now = int(time.time())
    # owned_by 不回传渠道厂商,避免向上游供应商信息泄露
    return [{"id": m.name, "object": "model", "created": now, "owned_by": "61api"} for m in items]
