"""知识库服务 — 双源：backend/knowledge/ 内置 md + SQLite 用户导入文档。

- 内置文档随 backend 镜像分发（Dockerfile COPY . .），单一真源在后端文件。
- 用户导入文档落 SQLite（biz_knowledge_docs，持久卷），容器重建不丢；
  由知识库页导入（粘贴/上传 md/txt），AI 解读/问答按启用态挂载。
- 前端知识库页与 AI 解读/问答（RAG 接地）都走本服务，保证两边内容一致。
- 检索为轻量关键词打分（标题/tags 权重高于正文），不引外部依赖；
  片段截取时按关键词命中位置取上下文，控制在 ~300 字。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

# index 全量缓存；docs 缓存 doc_id -> (mtime, content)，mtime 不变即命中，
# md 热更新（改文件）后自动失效重新读盘（2026-10-14 审计 P2-6）。
_CACHE: dict[str, Any] = {"index": None, "docs": {}}

# 导入文档（SQLite）缓存：写操作后 invalidate_import_cache() 失效。
_IMPORT_CATEGORY = "imported"
_IMPORT_TABLE = "biz_knowledge_docs"
_imported_cache: dict[str, Any] = {"rows": None}


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


# ============================================================
# 导入文档（SQLite 双源）
# ============================================================

def _load_imported() -> list[dict]:
    """读取用户导入文档（带进程内缓存；写操作后需 invalidate）。"""
    if _imported_cache["rows"] is not None:
        return _imported_cache["rows"]
    rows: list[dict] = []
    try:
        from database.sqlite_connection import get_biz_db

        biz = get_biz_db()
        if biz.table_exists(_IMPORT_TABLE):
            for r in biz.fetchall(
                "SELECT id, fk_user, title, content, tags, enabled, char_count, "
                "created_at, updated_at FROM biz_knowledge_docs ORDER BY created_at DESC"
            ):
                content = r[3] or ""
                try:
                    tags = json.loads(r[4]) if r[4] else []
                    if not isinstance(tags, list):
                        tags = []
                except Exception:  # noqa: BLE001
                    tags = []
                rows.append({
                    "id": r[0],
                    "fk_user": r[1],
                    "title": r[2] or "",
                    "content": content,
                    "tags": [str(t) for t in tags],
                    "enabled": bool(r[5]),
                    "char_count": r[6] or len(content),
                    "created_at": r[7],
                    "updated_at": r[8],
                })
    except Exception as e:  # noqa: BLE001
        print(f"[Knowledge] 导入文档读取失败: {e}")
    _imported_cache["rows"] = rows
    return rows


def invalidate_import_cache() -> None:
    """导入/删除/启停后调用，让后续请求立即看到新状态。"""
    _imported_cache["rows"] = None


def _imported_meta(d: dict) -> dict:
    return {
        "id": d["id"],
        "category": _IMPORT_CATEGORY,
        "title": d["title"],
        "tags": d.get("tags") or [],
        "source": "import",
        "enabled": d.get("enabled", True),
        "char_count": d.get("char_count") or len(d.get("content") or ""),
        "updated_at": d.get("updated_at"),
    }


def _now_str() -> str:
    # 与 biz_users 等表一致：容器时钟 naive 串（UTC）
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_doc(title: str, content: str, tags: list[str] | None = None,
               fk_user: int | None = None) -> dict:
    """导入一篇知识文档，返回元信息（不含正文）。"""
    doc_id = "kb_" + uuid.uuid4().hex[:8]
    now = _now_str()
    clean_tags = [str(t).strip()[:20] for t in (tags or []) if str(t).strip()][:10]
    from database.sqlite_connection import get_biz_db

    biz = get_biz_db()
    biz.execute(
        f"INSERT INTO {_IMPORT_TABLE} "
        "(id, fk_user, title, content, tags, enabled, char_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        [doc_id, fk_user, title, content, json.dumps(clean_tags, ensure_ascii=False),
         len(content), now, now],
    )
    invalidate_import_cache()
    return {"id": doc_id, "category": _IMPORT_CATEGORY, "title": title,
            "tags": clean_tags, "source": "import", "enabled": True,
            "char_count": len(content), "updated_at": now}


def delete_doc(doc_id: str) -> bool:
    """删除导入文档（内置文档不可删，返回 False）。"""
    exists = any(d["id"] == doc_id for d in _load_imported())
    if not exists:
        return False
    from database.sqlite_connection import get_biz_db

    get_biz_db().execute(f"DELETE FROM {_IMPORT_TABLE} WHERE id = ?", [doc_id])
    invalidate_import_cache()
    return True


def set_doc_enabled(doc_id: str, enabled: bool) -> dict | None:
    """启停导入文档（停用后不参与 AI 解读/问答挂载）。"""
    hit = next((d for d in _load_imported() if d["id"] == doc_id), None)
    if not hit:
        return None
    from database.sqlite_connection import get_biz_db

    get_biz_db().execute(
        f"UPDATE {_IMPORT_TABLE} SET enabled = ?, updated_at = ? WHERE id = ?",
        [1 if enabled else 0, _now_str(), doc_id],
    )
    invalidate_import_cache()
    hit["enabled"] = enabled
    return _imported_meta(hit)


def imported_for_interpret(max_chars: int = 8000) -> list[dict]:
    """AI 解读挂载用：启用态导入文档全文，按更新时间倒序，总量预算截断。

    用户主动导入即期望被 AI 使用；预算防 prompt 爆炸（与 _compact 段一致风格）。
    """
    docs = [d for d in _load_imported() if d.get("enabled")]
    docs.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
    out: list[dict] = []
    budget = max_chars
    for d in docs:
        content = d.get("content") or ""
        if budget <= 0:
            break
        if len(content) > budget:
            content = content[:budget] + "…[内容过长已截断]"
        out.append({"id": d["id"], "title": d["title"], "content": content})
        budget -= len(content)
    return out


def list_docs() -> dict:
    """返回分类 + 文档元数据（不含正文），内置与导入双源合并。"""
    idx = _load_index()
    cats = list(idx.get("categories", []))
    docs = list(idx.get("docs", []))
    imported = _load_imported()
    if imported:
        if not any(c.get("id") == _IMPORT_CATEGORY for c in cats):
            cats.append({"id": _IMPORT_CATEGORY, "name": "我的导入"})
        docs.extend(_imported_meta(d) for d in imported)
    return {"categories": cats, "docs": docs}


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
    # 导入文档优先（id 前缀 kb_，与内置 id 命名空间隔离）
    for d in _load_imported():
        if d["id"] == doc_id:
            return {**_imported_meta(d), "content": d["content"]}
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
    """关键词检索：标题/tags 命中权重 3，正文命中权重 1。内置 + 导入双源。"""
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
    for d in _load_imported():
        if not d.get("enabled"):
            continue
        content = d.get("content") or ""
        if not content:
            continue
        title = d.get("title") or ""
        tags = " ".join(d.get("tags") or [])
        title_tags_hits = sum(1 for t in token_set if t in (title + " " + tags).lower())
        content_hits = sum(1 for t in token_set if t in content.lower())
        score = title_tags_hits * 3 + min(content_hits, 10)
        if score <= 0:
            continue
        scored.append((score, {
            "id": d["id"],
            "title": title,
            "score": score,
            "snippet": _snippet(content, list(token_set)),
            "source": "import",
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
