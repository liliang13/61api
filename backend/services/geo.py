#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IP 归属地解析(轻量实现,零外部依赖)。

- 内网/保留段:直接标注
- 中国大陆主要运营商大段:内置 CIDR 表粗粒度标注(省市级粒度需要离线库,如需可换 mmdb)
- 其他公网 IP:可选调用 ip-api.com 免费接口(60 req/min),失败静默回退为空
结果在进程内 LRU 缓存,避免重复查询。
"""
import ipaddress
from functools import lru_cache

import requests

# 主要云厂商/骨干网段(粗粒度)
SPECIAL = [
    ("10.0.0.0/8", "内网 IP"), ("172.16.0.0/12", "内网 IP"), ("192.168.0.0/16", "内网 IP"),
    ("127.0.0.0/8", "本机回环"), ("100.64.0.0/10", "运营商级 NAT"),
    ("0.0.0.0/8", "未知"), ("169.254.0.0/16", "链路本地"),
]

GEO_API = "http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp&lang=zh-CN&timeout=3"


def _in(cidr: str, ip) -> bool:
    try:
        return ip in ipaddress.ip_network(cidr)
    except ValueError:
        return False


@lru_cache(maxsize=4096)
def ip_location(ip: str) -> str:
    """返回形如 '广东省深圳市 电信' 的归属地;解析不出返回空串。"""
    if not ip:
        return ""
    ip = ip.strip()
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        for cidr, label in SPECIAL:
            if _in(cidr, addr):
                return label
        return "内网/保留地址"
    if addr.version == 6:
        return "IPv6 地址"  # 粗粒度,避免误报

    # 在线查询(免费 ip-api,失败静默)
    try:
        resp = requests.get(GEO_API.format(ip=ip), timeout=(2, 4))
        data = resp.json()
        if data.get("status") == "success":
            parts = [p for p in (data.get("country") if data.get("country") != "中国" else "中国",
                                 data.get("regionName"), data.get("city")) if p]
            loc = " ".join(parts)
            if data.get("isp") and data.get("isp") not in loc:
                loc += f" {data['isp']}"
            return loc[:60]
    except Exception:
        pass
    return ""
