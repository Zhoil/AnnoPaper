"""
LLM 驱动的文献推荐 + 严格验证防编造。

流程：
  1. 从文档记录读取文体类型、主旨 JSON 与关键论点
  2. 根据文体选择 system prompt：
     - 学术/综述/技术报告 → arXiv + DOI 强验证
     - 新闻/评论           → 白名单媒体 URL 验证
     - 科普/行业/通用     → OpenAlex/Wikipedia/DOI/arXiv 多源验证
  3. 对 LLM 输出的每一篇，按提供的标识符依次跳转到对应验证器
  4. 丢弃任何无法验证的“幻觉论文/文章”
  5. 对通过验证的条目，用官方 API 的权威数据覆盖 LLM 输出

注意：本模块不包含缓存逻辑（由 app.py 与 database 层管理 2 天缓存 + flag 标记）。
"""

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from urllib.parse import urlparse

from scholar_api import (
    _http_get, _throttle, build_query_from_record, _reconstruct_abstract,
)
from prompts import (
    RECOMMEND_SYSTEM_PROMPT, build_recommend_user_prompt,
    build_recommend_system_prompt, RECOMMEND_GENRE_NAME,
)
# 新闻域名白名单与 prompt 模板同源，由 recommend_sources 统一维护
from recommend_sources import NEWS_DOMAIN_WHITELIST as _NEWS_DOMAIN_WHITELIST


def _build_user_prompt(record: Dict) -> str:
    """从 record 构建用户侧 prompt。此处仅做数据清洗，模板拼接委托 prompts 模块。"""
    title = (record.get('title') or record.get('filename') or '').strip()
    summary = record.get('summary') or {}
    raw_core = summary.get('core_points') or []
    raw_conc = summary.get('conclusions') or []
    keypoints = record.get('keypoints') or []

    # 主旨句：核心观点前 8 条 + 总结性结论前 3 条，尽量给足语义信号
    core_points = [str(p)[:150] for p in raw_core[:8] if str(p).strip()]
    for c in raw_conc[:3]:
        c_s = str(c).strip()
        if c_s and c_s not in core_points:
            core_points.append(c_s[:150])

    kp_texts = []
    for kp in keypoints[:8]:
        label = (kp.get('annotation_label') or '').strip()
        content = (kp.get('content') or '').strip()[:100]
        if label and content:
            kp_texts.append(f'[{label}] {content}')
        elif content:
            kp_texts.append(content)

    genre_type = ((record.get('genre') or {}).get('type') or 'general').strip()
    genre_name = RECOMMEND_GENRE_NAME.get(genre_type, '')

    return build_recommend_user_prompt(title, core_points, kp_texts, genre_name=genre_name)


# ───────────────────────── LLM 调用 ─────────────────────────

def _call_llm(llm_service, provider: str, user_prompt: str,
              system_prompt: Optional[str] = None) -> Optional[str]:
    """使用 LLMService 内部 _call_api 直接请求（不走文档分析的复杂 pipeline）。"""
    if system_prompt is None:
        system_prompt = RECOMMEND_SYSTEM_PROMPT
    try:
        cfg = llm_service._get_provider_config(provider)
        if not cfg.get('api_key'):
            # 回退到 CHAT_PROVIDER
            cfg = llm_service._get_provider_config(llm_service.chat_provider)
            if not cfg.get('api_key'):
                print('⚠️ 无可用 LLM provider')
                return None
        return llm_service._call_api(user_prompt, system_prompt, cfg, call_type='recommend')
    except Exception as e:
        print(f'⚠️ LLM 调用失败: {e}')
        return None


def _parse_llm_output(raw: str) -> List[Dict]:
    """从 LLM 原始输出中解析 papers 列表（容错混合文本 / markdown 代码块）。"""
    if not raw:
        return []
    s = raw.strip()
    # 移除 <think>
    if '<think>' in s:
        s = re.sub(r'<think>[\s\S]*?</think>', '', s).strip()
    if s.startswith('```json'):
        s = s[7:]
    elif s.startswith('```'):
        s = s[3:]
    if s.endswith('```'):
        s = s[:-3]
    s = s.strip()

    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]*\}', s)
        if not m:
            return []
        try:
            data = json.loads(m.group())
        except Exception:
            return []

    papers = data.get('papers') if isinstance(data, dict) else None
    if not isinstance(papers, list):
        return []
    return papers


# ───────────────────────── 论文存在性验证 ─────────────────────────

def _normalize_title(t: str) -> str:
    t = (t or '').lower()
    t = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _title_similar(a: str, b: str, thresh: float = 0.6) -> bool:
    """标题相似度：基于字符级 token 重合的 Jaccard，用于防止 arxiv_id 错位。"""
    a_n = _normalize_title(a)
    b_n = _normalize_title(b)
    if not a_n or not b_n:
        return False
    if a_n == b_n or a_n in b_n or b_n in a_n:
        return True
    set_a = set(a_n.split())
    set_b = set(b_n.split())
    if not set_a or not set_b:
        return False
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    jaccard = inter / union if union else 0
    return jaccard >= thresh


def verify_by_arxiv(arxiv_id: str, llm_title: str) -> Optional[Dict]:
    """arXiv id_list 精确查询，返回真实论文元数据（验证通过）或 None。"""
    if not arxiv_id:
        return None
    # 允许形如 "arXiv:2106.14624" / "2106.14624v1" / "http://arxiv.org/abs/2106.14624"
    clean = arxiv_id.strip()
    if '/' in clean:
        clean = clean.rstrip('/').rsplit('/', 1)[-1]
    clean = clean.replace('arXiv:', '').replace('arxiv:', '').strip()
    # 去掉版本号 v1/v2 仅用于匹配
    base_id = re.sub(r'v\d+$', '', clean)
    if not re.match(r'^\d{4}\.\d{4,6}$', base_id) and not re.match(r'^[a-z\-]+/\d{7}$', base_id):
        return None

    url = (
        "http://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({'id_list': base_id, 'max_results': 1})
    )
    try:
        _throttle('arxiv')
        xml_text = _http_get(url, timeout=10, max_retries=3, source='arxiv')
    except Exception as e:
        print(f'⚠️ arXiv 验证 {base_id} 失败: {e}')
        return None

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    try:
        root = ET.fromstring(xml_text)
        entry = root.find('atom:entry', ns)
        if entry is None:
            return None
        real_title = (entry.findtext('atom:title', default='', namespaces=ns) or '').strip().replace('\n', ' ')
        if not real_title:
            return None
        # 标题相似度校验，防止 LLM 把 id 写错但标题正确的情况被通过
        if not _title_similar(real_title, llm_title, thresh=0.35):
            print(f'⚠️ arXiv {base_id} 标题不一致: LLM="{llm_title[:50]}" vs real="{real_title[:50]}"')
            return None
        summary = (entry.findtext('atom:summary', default='', namespaces=ns) or '').strip().replace('\n', ' ')
        published = (entry.findtext('atom:published', default='', namespaces=ns) or '').strip()
        year = published[:4] if len(published) >= 4 else ''
        authors = [
            (a.findtext('atom:name', default='', namespaces=ns) or '').strip()
            for a in entry.findall('atom:author', ns)
        ]
        return {
            'source': 'arxiv',
            'title': real_title,
            'authors': ', '.join([a for a in authors if a][:6]),
            'year': year,
            'summary': summary[:600],
            'url': f'https://arxiv.org/abs/{base_id}',
            'external_id': base_id,
            'venue': 'arXiv'
        }
    except Exception as e:
        print(f'⚠️ arXiv XML 解析 {base_id} 失败: {e}')
        return None


def verify_by_doi(doi: str, llm_title: str) -> Optional[Dict]:
    """通过 Semantic Scholar DOI 精确查询验证论文是否真实存在。"""
    if not doi:
        return None
    clean = doi.strip().replace('https://doi.org/', '').replace('http://doi.org/', '')
    if not clean.startswith('10.'):
        return None

    url = (
        "https://api.semanticscholar.org/graph/v1/paper/DOI:"
        + urllib.parse.quote(clean, safe='')
        + "?fields=title,abstract,year,authors,venue,url,externalIds"
    )
    try:
        _throttle('s2')
        body = _http_get(url, timeout=15, max_retries=3, source='s2')
        data = json.loads(body)
    except Exception as e:
        print(f'⚠️ DOI {clean} 验证失败: {e}')
        return None

    if not isinstance(data, dict) or not data.get('title'):
        return None

    real_title = (data.get('title') or '').strip()
    if not _title_similar(real_title, llm_title, thresh=0.35):
        print(f'⚠️ DOI {clean} 标题不一致: LLM="{llm_title[:50]}" vs real="{real_title[:50]}"')
        return None

    ext = data.get('externalIds') or {}
    paper_url = data.get('url') or f'https://doi.org/{clean}'
    venue = (data.get('venue') or '').strip() or '—'
    return {
        'source': 'semantic_scholar',
        'title': real_title,
        'authors': ', '.join([
            (a or {}).get('name', '') for a in (data.get('authors') or [])
            if (a or {}).get('name')
        ][:6]),
        'year': str(data.get('year') or ''),
        'summary': (data.get('abstract') or '')[:600],
        'url': paper_url,
        'external_id': clean,
        'venue': venue
    }


def verify_by_openalex(oa_id_or_doi: str, llm_title: str) -> Optional[Dict]:
    """OpenAlex works/{id} 精确查询。id 可为 W123...、doi:10.xxx、https://doi.org/10.xxx。"""
    if not oa_id_or_doi:
        return None
    s = oa_id_or_doi.strip()
    if s.startswith('https://doi.org/') or s.startswith('http://doi.org/'):
        key = s  # OpenAlex 支持完整 DOI URL
    elif s.startswith('10.'):
        key = f'doi:{s}'
    elif s.upper().startswith('W') and s[1:].isdigit():
        key = s.upper()
    else:
        return None

    url = (
        f"https://api.openalex.org/works/{urllib.parse.quote(key, safe=':')}"
        "?select=id,doi,title,publication_year,authorships,primary_location,abstract_inverted_index"
        "&mailto=research@annopaper.local"
    )
    try:
        _throttle('openalex')
        body = _http_get(url, timeout=15, max_retries=2, source='openalex')
        data = json.loads(body)
    except Exception as e:
        print(f'⚠️ OpenAlex 验证 {key} 失败: {e}')
        return None

    if not isinstance(data, dict):
        return None
    real_title = (data.get('title') or '').strip()
    if not real_title or not _title_similar(real_title, llm_title, thresh=0.35):
        return None

    doi = (data.get('doi') or '').replace('https://doi.org/', '')
    oa_id = (data.get('id') or '').rsplit('/', 1)[-1]
    year = str(data.get('publication_year') or '')
    authors = [((a.get('author') or {}).get('display_name') or '').strip()
               for a in (data.get('authorships') or [])][:6]
    loc = data.get('primary_location') or {}
    src = loc.get('source') or {}
    venue = (src.get('display_name') or '').strip() or '—'
    page_url = (loc.get('landing_page_url')
                or (f"https://doi.org/{doi}" if doi else f"https://openalex.org/{oa_id}"))
    return {
        'source': 'openalex',
        'title': real_title,
        'authors': ', '.join([a for a in authors if a]),
        'year': year,
        'summary': _reconstruct_abstract(data.get('abstract_inverted_index'))[:600],
        'url': page_url,
        'external_id': doi or oa_id,
        'venue': venue
    }


def verify_by_wikipedia(title: str, lang: str = 'zh') -> Optional[Dict]:
    """通过 Wikipedia REST API page summary 验证词条是否存在。不分歧/不缺失即视为有效。"""
    if not title:
        return None
    lang = (lang or 'zh').strip().lower()
    if lang not in ('zh', 'en'):
        lang = 'zh'
    safe_title = urllib.parse.quote(title.replace(' ', '_'), safe='')
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{safe_title}"
    try:
        _throttle('wikipedia')
        body = _http_get(url, timeout=15, max_retries=2, source='wikipedia')
        data = json.loads(body)
    except Exception as e:
        print(f'⚠️ Wikipedia 验证 "{title}" 失败: {e}')
        return None

    if not isinstance(data, dict):
        return None
    if data.get('type') in ('disambiguation', 'no-extract', 'https://mediawiki.org/wiki/HyperSwitch/errors/not_found'):
        return None
    real_title = (data.get('title') or '').strip()
    if not real_title:
        return None
    content_urls = (data.get('content_urls') or {}).get('desktop') or {}
    page_url = content_urls.get('page') or f"https://{lang}.wikipedia.org/wiki/{safe_title}"
    return {
        'source': 'wikipedia',
        'title': real_title,
        'authors': '',
        'year': '',
        'summary': (data.get('extract') or '')[:600],
        'url': page_url,
        'external_id': f'{lang}wiki:{real_title}',
        'venue': 'Wikipedia'
    }


def _verify_by_url_domain(url: str, llm_title: str) -> Optional[Dict]:
    """仅通过域名白名单验证新闻链接。不抓网页，避免被反爬拦截。"""
    if not url or not url.startswith(('http://', 'https://')):
        return None
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    if not host:
        return None
    matched = any(host == d or host.endswith('.' + d) for d in _NEWS_DOMAIN_WHITELIST)
    if not matched:
        return None
    return {
        'source': 'news',
        'title': llm_title,
        'authors': '',
        'year': '',
        'summary': '',
        'url': url,
        'external_id': url,
        'venue': host
    }


# ───────────────────────── 入口函数 ─────────────────────────

def recommend_with_llm(record: Dict, llm_service, provider: str = 'deepseek',
                       max_results: int = 6) -> Dict:
    """
    LLM 驱动的文献推荐主入口。
    根据 record['genre']['type'] 路由到不同的 system prompt 与验证器组合。
    返回：{ query, results: [...], sources: {...}, warning? }
    """
    genre_type = ((record.get('genre') or {}).get('type') or 'general').strip()
    system_prompt = build_recommend_system_prompt(genre_type)

    # 主旨优先模式：对外交付的 query 字段（用于前端展示与下游兼容）
    query = build_query_from_record(record, prefer='thesis')
    user_prompt = _build_user_prompt(record)

    raw = _call_llm(llm_service, provider, user_prompt, system_prompt=system_prompt)
    if not raw:
        return {'query': query, 'results': [], 'sources': {'llm_total': 0, 'genre': genre_type},
                'warning': 'LLM 未返回响应'}

    candidates = _parse_llm_output(raw)
    if not candidates:
        return {'query': query, 'results': [], 'sources': {'llm_total': 0, 'genre': genre_type},
                'warning': 'LLM 输出无法解析为论文列表'}

    verified: List[Dict] = []
    arxiv_verified = 0
    doi_verified = 0
    openalex_verified = 0
    wiki_verified = 0
    news_verified = 0
    dropped = 0
    seen_keys = set()

    # 学术类文体先走 arxiv/doi；通用类在两者均不命中时再走 OpenAlex/Wikipedia。
    academic_like = genre_type in ('academic_paper', 'review_paper', 'technical_report')
    news_like = genre_type in ('news_report', 'opinion_essay')

    for p in candidates:
        if not isinstance(p, dict):
            dropped += 1
            continue
        title = (p.get('title') or '').strip()
        if not title:
            dropped += 1
            continue

        arxiv_id = (p.get('arxiv_id') or '').strip()
        doi = (p.get('doi') or '').strip()
        wiki_title = (p.get('wikipedia_title') or '').strip()
        wiki_lang = (p.get('wikipedia_lang') or 'zh').strip().lower()
        page_url = (p.get('url') or '').strip()

        resolved: Optional[Dict] = None

        if news_like:
            # 新闻分支：仅认白名单媒体 URL
            if page_url:
                resolved = _verify_by_url_domain(page_url, title)
                if resolved:
                    news_verified += 1
        else:
            # 学术优先 → OpenAlex DOI 兜底 → Wikipedia
            if arxiv_id:
                resolved = verify_by_arxiv(arxiv_id, title)
                if resolved:
                    arxiv_verified += 1
            if not resolved and doi:
                resolved = verify_by_doi(doi, title)
                if resolved:
                    doi_verified += 1
            # 非学术文体或上述均未命中时，再走 OpenAlex 与 Wikipedia
            if not resolved and not academic_like and doi:
                resolved = verify_by_openalex(doi, title)
                if resolved:
                    openalex_verified += 1
            if not resolved and not academic_like and wiki_title:
                resolved = verify_by_wikipedia(wiki_title, wiki_lang)
                if resolved:
                    wiki_verified += 1

        if not resolved:
            dropped += 1
            continue

        # 去重：按 external_id 或规范化标题
        key = resolved.get('external_id') or _normalize_title(resolved['title'])[:80]
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # 回填 LLM 侧的补充元数据（新闻类没有官方摘要时尤为必要）
        reason = (p.get('reason') or '').strip()
        if reason:
            resolved['reason'] = reason[:150]
        if not resolved.get('summary'):
            s_llm = (p.get('summary') or '').strip()
            if s_llm:
                resolved['summary'] = s_llm[:600]
        if not resolved.get('venue') or resolved.get('venue') == '—':
            v_llm = (p.get('venue') or '').strip()
            if v_llm:
                resolved['venue'] = v_llm
        if not resolved.get('year'):
            y_llm = str(p.get('year') or '').strip()
            if y_llm:
                resolved['year'] = y_llm

        verified.append(resolved)
        if len(verified) >= max_results:
            break

    return {
        'query': query,
        'results': verified,
        'sources': {
            'llm_total': len(candidates),
            'arxiv_verified': arxiv_verified,
            'doi_verified': doi_verified,
            'openalex_verified': openalex_verified,
            'wikipedia_verified': wiki_verified,
            'news_verified': news_verified,
            'dropped': dropped,
            'genre': genre_type
        },
        'warning': None if verified else '所有 LLM 候选均未通过真实性验证，请稍后重试'
    }
