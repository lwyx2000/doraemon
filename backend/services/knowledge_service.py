"""知识库服务 — 读取 backend/knowledge/ 下的 md 文档，提供列表/详情/关键词检索。

- 文档随 backend 镜像分发（Dockerfile COPY . .），单一真源在后端。
- 前端知识库页与 AI 解读/问答（RAG 接地）都走本服务，保证两边内容一致。
- 检索为轻量关键词打分（标题/tags 权重高于正文），不引外部依赖；
  片段截取时按关键词命中位置取上下文，控制在 ~300 字。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

# index 全量缓存；docs 缓存 doc_id -> (mtime, content)，mtime 不变即命中，
# md 热更新（改文件）后自动失效重新读盘（2026-10-14 审计 P2-6）。
_CACHE: dict[str, Any] = {"index": None, "docs": {}}


def _load_index() -> dict:
    if _CACHE["index"] is not None:
        return _CACHE["index"]
    p = _KNOWLEDGE_DIR / "index.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("docs"), list):
            _CACHE["index"] = data
            return data
    except Exception as e:  # noqa: BLE001
        print(f"[Knowledge] index.json 读取失败: {e}")
    _CACHE["index"] = {"categories": [], "docs": []}
    return _CACHE["index"]


def _safe_path(doc_id: str) -> Path | None:
    """只允许读 index.json 中登记过的文件名，防路径穿越。"""
    for d in _load_index().get("docs", []):
        if d.get("id") == doc_id:
            fname = d.get("file") or ""
            if re.fullmatch(r"[A-Za-z0-9_-]+\.md", fname):
                p = _KNOWLEDGE_DIR / fname
                if p.exists():
                    return p
    return None


def list_docs() -> dict:
    """返回分类 + 文档元数据（不含正文）。"""
    return _load_index()


def _read_doc_content(doc_id: str) -> str | None:
    """读取文档正文，带 mtime 缓存。

    search() 早期版本对每个文档都 get_doc() → 每次检索把全部 md 重新
    读盘一遍（index 有缓存、content 没有）。KB 级文件虽小，但每次 AI
    问答都全量重读属于白交税。mtime 失效保证改文件后下次请求即见新内容。
    """
    p = _safe_path(doc_id)
    if not p:
        return None
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    cached = _CACHE["docs"].get(doc_id)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[Knowledge] 文档读取失败 {doc_id}: {e}")
        return None
    _CACHE["docs"][doc_id] = (mtime, content)
    return content


def get_doc(doc_id: str) -> dict | None:
    content = _read_doc_content(doc_id)
    if content is None:
        return None
    meta = next((d for d in _load_index().get("docs", []) if d.get("id") == doc_id), {})
    return {**meta, "content": content}


def _tokenize(text: str) -> list[str]:
    """中英混合简单分词：英文/数字按词，中文按 2-gram。"""
    tokens: list[str] = []
    for w in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        if len(w) >= 2:
            tokens.append(w)
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(seg) == 2:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def _snippet(content: str, tokens: list[str], width: int = 300) -> str:
    """取关键词命中最密集处的上下文片段。"""
    if not tokens:
        return content[:width]
    best_pos, best_hits = 0, -1
    for m in re.finditer(r"[。\n]", content):
        pos = m.start()
        window = content[max(0, pos - width // 2) : pos + width // 2]
        hits = sum(1 for t in set(tokens) if t in window)
        if hits > best_hits:
            best_pos, best_hits = pos, hits
    if best_hits <= 0:
        return content[:width]
    start = max(0, best_pos - width // 2)
    snippet = content[start : start + width].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(content) else "")


def search(query: str, top_k: int = 3) -> list[dict]:
    """关键词检索：标题/tags 命中权重 3，正文命中权重 1。"""
    q = (query or "").strip()
    if not q:
        return []
    tokens = _tokenize(q)
    if not tokens:
        return []
    token_set = set(tokens)
    scored: list[tuple[float, dict]] = []
    for meta in _load_index().get("docs", []):
        doc_id = meta.get("id", "")
        content = _read_doc_content(doc_id)
        if content is None:
            continue
        title = meta.get("title") or ""
        tags = " ".join(meta.get("tags") or [])
        title_tags_hits = sum(1 for t in token_set if t in (title + " " + tags).lower())
        content_hits = sum(1 for t in token_set if t in content.lower())
        score = title_tags_hits * 3 + min(content_hits, 10)
        if score <= 0:
            continue
        scored.append((score, {
            "id": doc_id,
            "title": title,
            "score": score,
            "snippet": _snippet(content, list(token_set)),
        }))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:top_k]]


def docs_by_ids(doc_ids: list[str]) -> list[dict]:
    """按 id 批量取全文（AI 解读按 context_type 固定挂载用）。"""
    out: list[dict] = []
    for doc_id in doc_ids:
        doc = get_doc(doc_id)
        if doc:
            out.append(doc)
    return out
