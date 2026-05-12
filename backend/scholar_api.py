"""
文献推荐服务：arXiv + Semantic Scholar 公共 API 聚合检索，
另对外提供 OpenAlex / Wikipedia 验证端的节流与 HTTP 工具。

- arXiv:           Atom XML，CS / Math / Physics 预印本，无需 Key
- Semantic Scholar：ACL / NeurIPS / ICML / IEEE 等会议期刊，无需 Key
- OpenAlex / Wikipedia：仅供 llm_recommender 中的 verify_by_* 链路做验证

特性：
- 分源节流，避免触发公共接口限流
- 本地文件缓存（TTL 7 天）在 backend/.scholar_cache 目录下
- 任何一路失败自动降级，不阻塞其他分支
"""

import os
import ssl
import time
import json
import random
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional


USER_AGENT = "AnnoPaper/1.0 (research-assistant; mailto:research@annopaper.local)"
CACHE_TTL_SECONDS = 7 * 24 * 3600
# 分源限流：arXiv 官方建议≥ 3s，Semantic Scholar 公共接口频繁 429（建议≥ 5s）
# OpenAlex / Wikipedia 官方允许较高 QPS，保留 0.2s 作为礼貌性节流
_MIN_INTERVAL = {'arxiv': 3.0, 's2': 5.0, 'openalex': 0.2, 'wikipedia': 0.2}
_last_request_ts = {'arxiv': 0.0, 's2': 0.0, 'openalex': 0.0, 'wikipedia': 0.0}
# 429 冷却时间戳：当命中 429 时把对应 source 的冷却截止时间推后，下次 _throttle 会先等尽
_cooldown_until = {'arxiv': 0.0, 's2': 0.0, 'openalex': 0.0, 'wikipedia': 0.0}

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_BACKEND_DIR, '.scholar_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)


# ───────────────────── SSL 上下文（优先 certifi，其次系统证书，最后降级无验证）─────────────────────

def _build_ssl_context() -> ssl.SSLContext:
    # 1) certifi——最推荐的证书路径
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    # 2) 系统默认证书
    try:
        return ssl.create_default_context()
    except Exception:
        pass
    # 3) 最后降级到无验证（仅用于公开的文献元数据接口）
    ctx = ssl._create_unverified_context()
    return ctx


_SSL_CONTEXT: Optional[ssl.SSLContext] = None
_SSL_FALLBACK_CONTEXT: Optional[ssl.SSLContext] = None


def _get_ssl_context(prefer_verify: bool = True) -> ssl.SSLContext:
    global _SSL_CONTEXT, _SSL_FALLBACK_CONTEXT
    if prefer_verify:
        if _SSL_CONTEXT is None:
            _SSL_CONTEXT = _build_ssl_context()
        return _SSL_CONTEXT
    if _SSL_FALLBACK_CONTEXT is None:
        _SSL_FALLBACK_CONTEXT = ssl._create_unverified_context()
    return _SSL_FALLBACK_CONTEXT


# ───────────────────────── 缓存工具 ─────────────────────────

def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode('utf-8')).hexdigest()
    return os.path.join(_CACHE_DIR, f"{h}.json")


def _cache_get(key: str):
    p = _cache_path(key)
    if not os.path.exists(p):
        return None
    try:
        if time.time() - os.path.getmtime(p) > CACHE_TTL_SECONDS:
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cache_put(key: str, data):
    try:
        with open(_cache_path(key), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _throttle(source: str):
    """双重节流：常规最小间隔 + 429 冷却时间。哪个更晚用哪个。"""
    now = time.time()
    interval = _MIN_INTERVAL.get(source, 1.0)
    wait_normal = interval - (now - _last_request_ts.get(source, 0.0))
    wait_cooldown = _cooldown_until.get(source, 0.0) - now
    wait = max(wait_normal, wait_cooldown, 0.0)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts[source] = time.time()


def _http_get(url: str, timeout: int = 10, max_retries: int = 3,
              source: Optional[str] = None) -> str:
    """带 SSL 降级与 429/5xx 指数退避重试的 GET。

    source：如果传入，429 时会把该 source 的冷却时间推后，防止外层紧接着
    的下一次请求继续撞 429。
    """
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, application/atom+xml;q=0.9, */*;q=0.8'
    })

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        # SSL：先验证，失败再降级
        try:
            ctx = _get_ssl_context(prefer_verify=(attempt == 0))
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            last_err = e
            # 429 / 5xx 退避；尊重 Retry-After
            if e.code in (429, 500, 502, 503, 504):
                retry_after = 0
                try:
                    retry_after = int(e.headers.get('Retry-After') or 0)
                except Exception:
                    retry_after = 0
                # 429 使用更大基数 + 最小 5s，防止群集效应
                if e.code == 429:
                    base = max(5.0, (2 ** attempt) * 2.0 + random.uniform(0, 2.0))
                else:
                    base = (2 ** attempt) + random.uniform(0, 1.0)
                sleep_s = retry_after if retry_after > 0 else base
                sleep_s = min(sleep_s, 20.0)
                # 429：把冷却推后，令后续调用者 _throttle 时也等待
                if e.code == 429 and source and source in _cooldown_until:
                    _cooldown_until[source] = max(
                        _cooldown_until.get(source, 0.0),
                        time.time() + sleep_s,
                    )
                time.sleep(sleep_s)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            reason = getattr(e, 'reason', None)
            # SSL 错误 → 下一次降级到无验证
            if isinstance(reason, ssl.SSLError) or 'CERTIFICATE_VERIFY_FAILED' in str(reason):
                # 强制降级到无验证的 fallback ctx
                try:
                    with urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_context(prefer_verify=False)) as resp:
                        return resp.read().decode('utf-8', errors='replace')
                except Exception as inner:
                    last_err = inner
                    time.sleep(1.0 + attempt)
                    continue
            # 其他网络异常：退避重试
            time.sleep(1.0 + attempt)
            continue
        except Exception as e:
            last_err = e
            time.sleep(1.0 + attempt)
            continue

    raise last_err if last_err else RuntimeError(f'HTTP GET failed: {url}')


# ───────────────────────── arXiv ─────────────────────────

def arxiv_search(query: str, max_results: int = 5) -> List[Dict]:
    """arXiv Atom XML 搜索。"""
    if not query:
        return []
    cache_key = f"arxiv::{query}::{max_results}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        "http://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({
            'search_query': f'all:{query}',
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
            'sortOrder': 'descending'
        })
    )

    try:
        _throttle('arxiv')
        xml_text = _http_get(url, timeout=10, source='arxiv')
    except Exception as e:
        print(f"⚠️ arXiv 检索失败: {e}")
        return []

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    results = []
    try:
        root = ET.fromstring(xml_text)
        for entry in root.findall('atom:entry', ns):
            arxiv_url = (entry.findtext('atom:id', default='', namespaces=ns) or '').strip()
            arxiv_id = arxiv_url.rsplit('/', 1)[-1] if arxiv_url else ''
            title = (entry.findtext('atom:title', default='', namespaces=ns) or '').strip().replace('\n', ' ')
            summary = (entry.findtext('atom:summary', default='', namespaces=ns) or '').strip().replace('\n', ' ')
            published = (entry.findtext('atom:published', default='', namespaces=ns) or '').strip()
            year = published[:4] if len(published) >= 4 else ''
            authors = [
                (a.findtext('atom:name', default='', namespaces=ns) or '').strip()
                for a in entry.findall('atom:author', ns)
            ]
            results.append({
                'source': 'arXiv',
                'title': title,
                'authors': [a for a in authors if a],
                'year': year,
                'summary': summary,
                'url': arxiv_url or f"https://arxiv.org/abs/{arxiv_id}",
                'external_id': arxiv_id,
                'venue': 'arXiv'
            })
    except ET.ParseError as e:
        print(f"⚠️ arXiv XML 解析失败: {e}")
        return []

    _cache_put(cache_key, results)
    return results


# ───────────────── Semantic Scholar（覆盖 ACL/NeurIPS 等）─────────────────

def semantic_scholar_search(query: str, max_results: int = 5) -> List[Dict]:
    """Semantic Scholar Graph API 搜索。
    覆盖 arXiv 以外的 ACL Anthology / NeurIPS / ICML / IEEE 等会议/期刊文献。
    """
    if not query:
        return []
    cache_key = f"s2::{query}::{max_results}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    fields = 'title,abstract,year,authors,venue,url,externalIds'
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        + urllib.parse.urlencode({
            'query': query,
            'limit': max_results,
            'fields': fields
        })
    )

    try:
        _throttle('s2')
        body = _http_get(url, timeout=15, max_retries=4, source='s2')
        data = json.loads(body)
    except urllib.error.HTTPError as e:
        # 429：部分源不可用，降级为空列表，不阻塞 arXiv 分支
        print(f"⚠️ Semantic Scholar 检索失败 (HTTP {e.code}): {e.reason}")
        return []
    except Exception as e:
        print(f"⚠️ Semantic Scholar 检索失败: {e}")
        return []

    results = []
    for p in (data.get('data') or []):
        ext = p.get('externalIds') or {}
        venue = (p.get('venue') or '').strip()
        paper_url = p.get('url') or ''
        if not paper_url:
            if ext.get('DOI'):
                paper_url = f"https://doi.org/{ext['DOI']}"
            elif ext.get('ArXiv'):
                paper_url = f"https://arxiv.org/abs/{ext['ArXiv']}"
            elif ext.get('ACL'):
                paper_url = f"https://aclanthology.org/{ext['ACL']}"

        results.append({
            'source': 'Semantic Scholar',
            'title': (p.get('title') or '').strip(),
            'authors': [(a or {}).get('name', '') for a in (p.get('authors') or []) if (a or {}).get('name')],
            'year': str(p.get('year') or ''),
            'summary': (p.get('abstract') or '').strip(),
            'url': paper_url,
            'external_id': ext.get('DOI') or ext.get('ArXiv') or ext.get('ACL') or '',
            'venue': venue or '—'
        })

    _cache_put(cache_key, results)
    return results


# ───────────────────────── 关键词抽取工具 ─────────────────────────

def _extract_keywords(text: str, topk: int = 10) -> List[str]:
    """从中文/混合文本中抽取关键词，用于降低整句中文直接送检造成的召回损失。
    优先使用 jieba.analyse.extract_tags，不可用时退化为正则+词频。"""
    if not text:
        return []
    try:
        import jieba.analyse  # 延迟加载，避免循环依赖
        kws = jieba.analyse.extract_tags(text, topK=topk)
        if kws:
            return [w for w in kws if w.strip()]
    except Exception:
        pass
    import re
    from collections import Counter
    toks = re.findall(r'[A-Za-z][A-Za-z\-]{2,}|[\u4e00-\u9fff]{2,}', text)
    cnt = Counter(toks)
    return [w for w, _ in cnt.most_common(topk)]


def _reconstruct_abstract(inv_idx) -> str:
    """还原 OpenAlex 的倒排索引摘要为可读文本。"""
    if not isinstance(inv_idx, dict) or not inv_idx:
        return ''
    pos_word = []
    for word, positions in inv_idx.items():
        for p in (positions or []):
            pos_word.append((p, word))
    pos_word.sort(key=lambda x: x[0])
    return ' '.join(w for _, w in pos_word)


# ───────────────────────── 组合检索 ─────────────────────────

def build_query_from_record(record: Dict, prefer: str = 'thesis') -> str:
    """从数据库记录中构建检索 query。

    prefer='thesis'（默认，新）：
        优先使用 LLM 分析已经产出的主旨 JSON（summary.core_points 前 2 条）+ title，
        再经 jieba TF-IDF 关键词化，确保中文整句不会拖垮外部 API 的召回率。
    prefer='title'：
        旧行为，兼容内部其他调用方。
    """
    summary = record.get('summary') or {}
    core_points = [str(p).strip() for p in (summary.get('core_points') or []) if str(p).strip()]
    title = (record.get('title') or '').strip()
    filename = record.get('filename') or ''
    keypoints = record.get('keypoints') or []

    if prefer == 'thesis' and (core_points or title):
        raw_parts = []
        if title and title != filename:
            raw_parts.append(title)
        raw_parts.extend(core_points[:2])
        raw_text = ' '.join(raw_parts)
        kws = _extract_keywords(raw_text, topk=10)
        if kws:
            return ' '.join(kws)[:200]
        return raw_text[:200]

    # 兼容旧行为
    parts = []
    if title and title != filename:
        parts.append(title)
    if core_points and not parts:
        parts.append(core_points[0][:80])
    kp_terms = []
    for kp in keypoints[:6]:
        label = (kp.get('annotation_label') or '').strip()
        if label:
            kp_terms.append(label)
        else:
            txt = (kp.get('content') or '')[:12]
            if txt:
                kp_terms.append(txt)
    if kp_terms:
        parts.append(' '.join(kp_terms[:3]))
    return ' '.join(parts).strip()[:200]


def _dedup_and_rank(*lists: List[Dict]) -> List[Dict]:
    """按 (标题前 40 字符 lowercase) 去重，交错拼接两路结果保证多样性。"""
    seen = set()
    merged = []
    max_len = max((len(l) for l in lists), default=0)
    for i in range(max_len):
        for lst in lists:
            if i >= len(lst):
                continue
            item = lst[i]
            key = (item.get('title') or '').strip().lower()[:40]
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def recommend_for_record(record: Dict, max_results: int = 6) -> Dict:
    """
    聚合 arXiv + Semantic Scholar 推荐（LLM 路径失败时的兜底降级方案）。
    返回：{ query, results: [...], sources: {...} }
    """
    query = build_query_from_record(record)
    if not query:
        return {'query': '', 'results': [], 'sources': {'arxiv': 0, 'semantic_scholar': 0}}

    per_source = max(3, (max_results // 2) + 1)
    arxiv_list = arxiv_search(query, max_results=per_source)
    s2_list = semantic_scholar_search(query, max_results=per_source)
    merged = _dedup_and_rank(arxiv_list, s2_list)[:max_results]

    return {
        'query': query,
        'results': merged,
        'sources': {
            'arxiv': len(arxiv_list),
            'semantic_scholar': len(s2_list)
        }
    }
