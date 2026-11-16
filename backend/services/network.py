import ipaddress
import socket
from urllib.parse import urlparse


def validate_upstream_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("上游地址必须是有效的 HTTP(S) URL")
    if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("上游地址不能包含凭据、查询参数或片段")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("上游地址端口无效") from exc
    if not 1 <= port <= 65535:
        raise ValueError("上游地址端口无效")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("上游地址无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("上游地址不能指向内网、环回或保留地址")
    return value
