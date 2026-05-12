"""
轻量 RAG 索引模块：基于 jieba 分词 + BM25 的段落级检索。

功能：
  - build_chunks：将解析产物 structured_content / 纯文本切分为检索单元
  - tokenize：中英文分词 + 停用词过滤
  - build_index：对 chunks 建 BM25Okapi 索引并序列化
  - load_index：从数据库懒加载 + 内存 LRU 缓存
  - retrieve：按 query 召回 top-k chunks

所有方法都以防御式写法处理异常，避免阻塞主流程。
"""

import json
import pickle
import re
from collections import OrderedDict
from typing import List, Dict, Optional, Tuple, Any

import jieba

try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None  # type: ignore
    _BM25_AVAILABLE = False
    print("⚠️ rank_bm25 未安装，RAG 检索将被禁用。请执行 pip install rank_bm25")


# ────────────────────────── 分词与停用词 ──────────────────────────

_STOP_WORDS = {
    # 中文常见虚词
    '的', '了', '是', '在', '和', '及', '与', '或', '也', '还', '就', '都',
    '而', '但', '而且', '并且', '因为', '所以', '如果', '那么', '那', '这',
    '这个', '那个', '一个', '一种', '一些', '一', '不', '没', '没有', '有',
    '为', '对', '以', '被', '把', '让', '给', '从', '到', '向', '之', '其',
    '之间', '之中', '之后', '之前', '等', '着', '过', '吗', '吧', '呢', '啊',
    '上', '下', '中', '内', '外', '年', '月', '日',
    # 英文常见虚词
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'of', 'in', 'on',
    'at', 'to', 'for', 'by', 'with', 'as', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'this', 'that', 'these', 'those', 'it', 'its', 'we',
    'they', 'he', 'she', 'i', 'you', 'not', 'no', 'so', 'do', 'does', 'did',
    'have', 'has', 'had', 'will', 'would', 'can', 'could', 'should',
}

_PUNCT_RE = re.compile(r'^[\s\W_]+$', re.UNICODE)


def tokenize(text: str) -> List[str]:
    """jieba 精确分词 + 小写化 + 去停用词/纯标点/单字符噪声。"""
    if not text:
        return []
    tokens = []
    for tok in jieba.lcut(text):
        tok = tok.strip().lower()
        if not tok or len(tok) < 2:
            continue
        if _PUNCT_RE.match(tok):
            continue
        if tok in _STOP_WORDS:
            continue
        tokens.append(tok)
    return tokens


# ────────────────────────── Chunk 切分 ──────────────────────────

def _split_long_text(text: str, max_chars: int) -> List[str]:
    """将超长文本按句号/换行切分，累加到不超过 max_chars。"""
    if len(text) <= max_chars:
        return [text]
    pieces = re.split(r'(?<=[。！？.!?\n])', text)
    out, buf = [], ''
    for p in pieces:
        if len(buf) + len(p) <= max_chars:
            buf += p
        else:
            if buf:
                out.append(buf.strip())
            if len(p) > max_chars:
                # 硬切
                for i in range(0, len(p), max_chars):
                    out.append(p[i:i + max_chars].strip())
                buf = ''
            else:
                buf = p
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


def _table_to_text(item: Dict) -> str:
    """将表格 item 的 table_data 拼成行文本。"""
    rows = item.get('table_data') or []
    if not rows:
        return item.get('content', '')
    lines = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            lines.append(' | '.join(str(c) for c in row))
        else:
            lines.append(str(row))
    return '\n'.join(lines)


def build_chunks(structured_content: Optional[List[Dict]],
                 full_text: Optional[str] = '',
                 max_chars: int = 400,
                 min_chars: int = 80) -> List[Dict[str, Any]]:
    """
    构建 RAG 检索单元。
    优先从 structured_content 构建；若为空则按段落切分 full_text。
    输出：[{idx, page, content, bbox, source_type: 'text'|'table'}]
    """
    chunks: List[Dict[str, Any]] = []

    if structured_content:
        # 按页聚合相邻文本块，避免碎片；表格独立成 chunk
        buf_text = ''
        buf_page = None
        buf_bbox = None

        def flush():
            nonlocal buf_text, buf_page, buf_bbox
            if buf_text.strip():
                for piece in _split_long_text(buf_text.strip(), max_chars):
                    if piece:
                        chunks.append({
                            'idx': len(chunks),
                            'page': buf_page if buf_page is not None else 0,
                            'content': piece,
                            'bbox': buf_bbox,
                            'source_type': 'text'
                        })
            buf_text = ''
            buf_page = None
            buf_bbox = None

        for item in structured_content:
            item_type = item.get('type', 'text')
            content = (item.get('content') or '').strip()
            page = item.get('page', 0)

            if item_type == 'table':
                flush()
                tbl_text = _table_to_text(item)
                if tbl_text.strip():
                    chunks.append({
                        'idx': len(chunks),
                        'page': page or 0,
                        'content': tbl_text.strip(),
                        'bbox': item.get('bbox'),
                        'source_type': 'table'
                    })
                continue

            if item_type == 'image':
                # 图片本身无法检索，但 surrounding_text 可作为文本
                surrounding = (item.get('surrounding_text') or '').strip()
                if surrounding:
                    content = surrounding
                else:
                    continue

            if not content:
                continue

            # 同页且累积未超上限则合并
            if buf_page is None:
                buf_page = page
                buf_bbox = item.get('bbox')
            elif buf_page != page or len(buf_text) + len(content) > max_chars:
                flush()
                buf_page = page
                buf_bbox = item.get('bbox')

            buf_text = (buf_text + '\n' + content).strip() if buf_text else content

            if len(buf_text) >= max_chars:
                flush()

        flush()

        # 合并过短的相邻同页 chunk
        merged: List[Dict[str, Any]] = []
        for c in chunks:
            if (merged and c['source_type'] == 'text'
                    and merged[-1]['source_type'] == 'text'
                    and merged[-1]['page'] == c['page']
                    and len(merged[-1]['content']) < min_chars
                    and len(merged[-1]['content']) + len(c['content']) <= max_chars):
                merged[-1]['content'] = merged[-1]['content'] + '\n' + c['content']
            else:
                merged.append(c)
        # 重新编号
        for i, c in enumerate(merged):
            c['idx'] = i
        return merged

    # 回退：按段落切 full_text
    if full_text:
        paragraphs = re.split(r'\n\s*\n+', full_text)
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            for piece in _split_long_text(para, max_chars):
                if len(piece) < 10:
                    continue
                chunks.append({
                    'idx': len(chunks),
                    'page': 0,
                    'content': piece,
                    'bbox': None,
                    'source_type': 'text'
                })
    return chunks


# ────────────────────────── 索引构建 / 加载 ──────────────────────────

def build_index(chunks: List[Dict]) -> Optional[Tuple[str, bytes, int]]:
    """返回 (chunks_json, bm25_pickle_bytes, chunk_count)；失败或依赖缺失返回 None。"""
    if not _BM25_AVAILABLE or not chunks:
        return None
    tokenized_corpus = [tokenize(c.get('content', '')) for c in chunks]
    # 过滤空 token 行（BM25Okapi 要求每行至少 1 个 token）
    safe_corpus = [t if t else ['_'] for t in tokenized_corpus]
    try:
        bm25 = BM25Okapi(safe_corpus)
    except Exception as e:
        print(f"⚠️ BM25 构建失败: {e}")
        return None
    try:
        bm25_blob = pickle.dumps(bm25, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"⚠️ BM25 序列化失败: {e}")
        return None
    chunks_json = json.dumps(chunks, ensure_ascii=False)
    return chunks_json, bm25_blob, len(chunks)


# 内存 LRU 缓存（避免每次对话都反序列化）
_INDEX_CACHE: "OrderedDict[int, Tuple[List[Dict], Any]]" = OrderedDict()
_CACHE_MAX = 16


def load_index(analysis_id: int, db) -> Optional[Tuple[List[Dict], Any]]:
    """从缓存或数据库加载 (chunks, bm25_obj)。未命中返回 None。"""
    if not _BM25_AVAILABLE or analysis_id is None:
        return None
    if analysis_id in _INDEX_CACHE:
        _INDEX_CACHE.move_to_end(analysis_id)
        return _INDEX_CACHE[analysis_id]
    try:
        row = db.load_rag_index(analysis_id)
    except Exception as e:
        print(f"⚠️ 读取 RAG 索引失败 id={analysis_id}: {e}")
        return None
    if not row:
        return None
    try:
        chunks = json.loads(row['chunks_json'])
        bm25 = pickle.loads(row['bm25_blob'])
    except Exception as e:
        print(f"⚠️ 反序列化 RAG 索引失败 id={analysis_id}: {e}")
        return None
    _INDEX_CACHE[analysis_id] = (chunks, bm25)
    _INDEX_CACHE.move_to_end(analysis_id)
    while len(_INDEX_CACHE) > _CACHE_MAX:
        _INDEX_CACHE.popitem(last=False)
    return chunks, bm25


def invalidate_cache(analysis_id: int):
    """手动失效缓存（记录删除/重建时调用）。"""
    _INDEX_CACHE.pop(analysis_id, None)


# ────────────────────────── 检索 ──────────────────────────

def retrieve(query: str,
             chunks: List[Dict],
             bm25_obj: Any,
             top_k: int = 5,
             min_score: float = 0.1) -> List[Dict]:
    """BM25 打分召回 top_k。低于 min_score 的结果会被过滤。"""
    if not query or not chunks or bm25_obj is None:
        return []
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    try:
        scores = bm25_obj.get_scores(q_tokens)
    except Exception as e:
        print(f"⚠️ BM25 打分失败: {e}")
        return []

    scored = []
    for i, s in enumerate(scores):
        if i >= len(chunks):
            break
        if s < min_score:
            continue
        scored.append((float(s), chunks[i]))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    out = []
    for score, c in top:
        out.append({
            **c,
            'score': round(score, 4)
        })
    return out


# ───────────────────────── 全文扫描与意图识别 ─────────────────────────

# 全局性问题关键词：触发则会从 BM25 召回 top-k 切换为全文扫描
GLOBAL_INTENT_KEYWORDS = [
    # 涵盖性词汇
    '总结', '概括', '摘要', '概述', '概览', '综述', '综合', '整体', '整篇',
    '全文', '通篇', '文章内容', '文档内容', '主要内容', '核心内容',
    '主要观点', '核心观点', '主要论点', '核心论点', '主要观念',
    '讲什么', '讲的是什么', '讲了什么', '说的是什么', '写的是什么',
    '关于什么', '讨论什么', '破题', '中心思想', '中心论题',
    '整个文档', '整个文章', '通读', '通览', '简述', '试着总结',
    # 英文
    'summary', 'summarize', 'summarise', 'overview', 'overall', 'in general',
    'main idea', 'main point', 'key point', 'whole document', 'entire document',
    'tl;dr', 'tldr', 'what is this about', 'what does this paper'
]


def detect_global_intent(query: str) -> bool:
    """启发式判断用户问题是否属于全局性问题，命中则切全文扫描。"""
    if not query:
        return False
    q = query.lower()
    for kw in GLOBAL_INTENT_KEYWORDS:
        if kw in q or kw in query:
            return True
    return False


def retrieve_full_scan(chunks: List[Dict], max_chars: int = 10000) -> List[Dict]:
    """全文扫描：按原始顺序返回所有 chunks，内容总量接近 max_chars 时会被裁剪。

    策略：先按顺序填充，预算快溯时优先保留每页的首段，避免前半部占满、后半部全丢。
    """
    if not chunks:
        return []
    total = sum(len(c.get('content', '')) for c in chunks)
    if total <= max_chars:
        return [dict(c) for c in chunks]

    # 超出预算：按页抽稀，优先保留每页第一个 chunk，剩余预算均匀补充后续 chunk
    by_page: Dict[int, List[Dict]] = {}
    order: List[int] = []
    for c in chunks:
        p = c.get('page', 0) or 0
        if p not in by_page:
            by_page[p] = []
            order.append(p)
        by_page[p].append(c)

    picked: List[Dict] = []
    used = 0
    # 第一轮：每页首段
    for p in order:
        first = by_page[p][0]
        body_len = len(first.get('content', ''))
        if used + body_len > max_chars:
            break
        picked.append(dict(first))
        used += body_len
    # 第二轮：按原顺序补充其他 chunk
    existing_ids = {c.get('idx') for c in picked}
    for c in chunks:
        if c.get('idx') in existing_ids:
            continue
        body_len = len(c.get('content', ''))
        if used + body_len > max_chars:
            continue
        picked.append(dict(c))
        used += body_len
    picked.sort(key=lambda x: x.get('idx', 0))
    return picked


def format_context(retrieved: List[Dict], max_chars: int = 2800) -> str:
    """将召回片段格式化为 prompt 可用的上下文字符串。按 idx/page 顺序排版，便于全文模式阅读。"""
    if not retrieved:
        return ''
    # 排序：有 score 的按分数降序，无 score（全文扫描）按 idx 升序
    has_score = any('score' in c for c in retrieved)
    ordered = sorted(
        retrieved,
        key=lambda c: (-(c.get('score') or 0), c.get('idx', 0))
    ) if has_score else sorted(retrieved, key=lambda c: (c.get('page', 0), c.get('idx', 0)))
    lines = []
    total = 0
    for c in ordered:
        page = c.get('page', 0)
        idx = c.get('idx', 0)
        src = c.get('source_type', 'text')
        tag = '表格' if src == 'table' else '正文'
        header = f"[第{page}页·{tag}·片段{idx}]" if page else f"[{tag}·片段{idx}]"
        body = c.get('content', '')
        block = f"{header}\n{body}"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block) + 2
    return '\n\n'.join(lines)
