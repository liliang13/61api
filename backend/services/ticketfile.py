# -*- coding: utf-8 -*-
"""工单附件存储:图片白名单、魔数校验、服务端命名、tmp→正式两段式。

安全约束:
- 仅允许 png/jpg/jpeg/webp/gif,拒绝 svg 等可执行内容的图片格式
- 文件类型按**魔数**判定,不信任扩展名与 Content-Type
- 存储文件名由服务端生成(uuid),用户输入只做展示名
- 大小上限 5MB;key 绑定用户,防止跨用户引用他人临时附件
"""
import re
import secrets
import uuid
from pathlib import Path

from config import BASE_DIR

BASE = Path(BASE_DIR) / "data" / "ticket-files"
MAX_SIZE = 5 * 1024 * 1024  # 5MB

# 扩展名白名单(存储与 Content-Type 映射;不含 svg)
EXT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _sniff_ext(data: bytes) -> str | None:
    """按魔数判定真实图片类型,返回白名单扩展名;非白名单图片返回 None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def _key_is_safe(key: str) -> bool:
    """key 只允许服务端生成的格式(字母数字与 - .),防路径穿越。"""
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+(?:\.tmp)?[A-Za-z0-9_.\-]*", key)) \
        and ".." not in key and "/" not in key and "\\" not in key


def save_tmp(user_id: int, data: bytes, origin_name: str) -> dict:
    """校验并保存临时附件(创建/回复消息前先传图)。

    返回 {key, name, size};校验失败抛 ValueError(信息可直接展示)。
    """
    if len(data) > MAX_SIZE:
        raise ValueError("图片大小不能超过 5MB")
    if not data:
        raise ValueError("文件内容为空")
    ext = _sniff_ext(data)
    if ext is None:
        raise ValueError("仅支持 PNG/JPG/WebP/GIF 图片")
    key = "u{}-{}.tmp{}".format(user_id, uuid.uuid4().hex, ext)
    d = BASE / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    (d / key).write_bytes(data)
    return {"key": key, "name": (origin_name or ("image" + ext))[:120],
            "size": len(data)}


def promote(key: str, user_id: int, message_id: int) -> tuple[Path, str, int]:
    """把临时附件转为正式存储(绑定工单消息 ID);返回 (path, ext, size)。

    key 必须属于该用户且为 tmp 附件;移动后临时文件不复存在(防重用)。
    """
    if not _key_is_safe(key) or not key.startswith("u{}-".format(user_id)):
        raise ValueError("无效的附件引用")
    src = BASE / "tmp" / key
    if not src.exists():
        raise ValueError("附件已失效,请重新上传")
    ext = Path(key).suffix
    final_dir = BASE / "msg"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_name = "m{}.{}".format(message_id, ext.lstrip("."))
    dst = final_dir / final_name
    src.replace(dst)
    size = dst.stat().st_size
    return dst, ext, size


def discard(key: str) -> None:
    """丢弃临时附件(消息提交失败或用户移除图片时)。"""
    if not _key_is_safe(key):
        return
    try:
        (BASE / "tmp" / key).unlink()
    except OSError:
        pass


def open_final(key: str):
    """按 key 返回 (path, mimetype);key 非法或文件缺失返回 (None, None)。"""
    if not _key_is_safe(key) or not key.startswith("m"):
        return None, None
    path = BASE / "msg" / key
    if not path.exists():
        return None, None
    ext = Path(key).suffix.lower()
    return path, EXT_TYPES.get(ext, "application/octet-stream")


def cleanup_tmp(older_than_hours: int = 24) -> int:
    """清理超过时限的临时附件(用户传图后未提交消息的孤儿文件)。"""
    import time
    cutoff = time.time() - older_than_hours * 3600
    n = 0
    tmp = BASE / "tmp"
    if not tmp.exists():
        return 0
    for f in tmp.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            continue
    return n


def valid_image_name(name: str) -> str:
    """展示名清洗:去路径分隔与控制字符。"""
    return re.sub(r"[\\/:*?\"<>|\r\n]", "_", name or "")[:120]
