"""
LLM 驱动的文献推荐 + 严格验证防编造。

流程：
  1. 从文档记录构建主题描述 + 核心论点
  2. 调用 LLM（提供 arXiv/Semantic Scholar/ACL 等文献库接口说明，提示"必须给出可验证的 arxiv_id 或 DOI"）
  3. 对 LLM 输出的每一篇论文，使用真实公开 API 进行存在性 + 标题一致性验证
  4. 丢弃任何无法验证的"幻觉论文"
  5. 对通过验证的论文，用 API 返回的权威数据覆盖 LLM 输出（作者、年份、venue、url、摘要）

注意：本模块不包含缓存逻辑（由 app.py 与 database 层管理 2 天缓存 + flag 标记）。
"""

import os
import json
import urllib.parse
from typing import List, Dict, Optional, Tuple

from scholar_api import _http_get, _throttle, build_query_from_record
from prompts import RECOMMEND_SYSTEM_PROMPT, build_recommend_user_prompt


# ───────────────────────── LLM Prompt（已迁移到 prompts 模块）─────────────────────────
# 保留同名变量用于向下兼容，实际内容引用自 prompts.RECOMMEND_SYSTEM_PROMPT
_RECOMMEND_SYSTEM_PROMPT = RECOMMEND_SYSTEM_PROMPT


def _build_user_prompt(record: Dict) -> str:
    """从 record 构建用户侧 prompt。此处仅做数据清洗，模板拼接委托 prompts 模块。"""
    title = (record.get('title') or record.get('filename') or '').strip()
    summary = record.get('summary') or {}
    raw_core = summary.get('core_points') or []
    keypoints = record.get('keypoints') or []

    # 核心论点截断
    core_points = [str(p)[:150] for p in raw_core[:5] if str(p).strip()]

    # 提取前 8 个关键点作为主题描述
    kp_texts = []
    for kp in keypoints[:8]:
        label = (kp.get('annotation_label') or '').strip()
        content = (kp.get('content') or '').strip()[:100]
        if label and content:
            kp_texts.append(f'[{label}] {content}')
        elif content:
            kp_texts.append(content)

    return build_recommend_user_prompt(title, core_points, kp_texts)


# ───────────────────────── LLM 调用 ─────────────────────────

def _call_llm(llm_service, provider: str, user_prompt: str) -> Optional[str]:
    """使用 LLMService 内部 _call_api 直接请求（不走文档分析的复杂 pipeline）。"""
    try:
        cfg = llm_service._get_provider_config(provider)
        if not cfg.get('api_key'):
            # 回退到 CHAT_PROVIDER
            cfg = llm_service._get_provider_config(llm_service.chat_provider)
            if not cfg.get('api_key'):
                print('⚠️ 无可用 LLM provider')
                return None
        return llm_service._call_api(user_prompt, _RECOMMEND_SYSTEM_PROMPT, cfg, call_type='recommend')
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
        import re
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
        import re
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
    import re
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
    import re
    base_id = re.sub(r'v\d+$', '', clean)
    if not re.match(r'^\d{4}\.\d{4,6}$', base_id) and not re.match(r'^[a-z\-]+/\d{7}$', base_id):
        return None

    url = (
        "http://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({'id_list': base_id, 'max_results': 1})
    )
    try:
        _throttle('arxiv')
        xml_text = _http_get(url, timeout=10, max_retries=2)
    except Exception as e:
        print(f'⚠️ arXiv 验证 {base_id} 失败: {e}')
        return None

    import xml.etree.ElementTree as ET
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
        body = _http_get(url, timeout=15, max_retries=3)
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


# ───────────────────────── 入口函数 ─────────────────────────

def recommend_with_llm(record: Dict, llm_service, provider: str = 'deepseek',
                       max_results: int = 6) -> Dict:
    """
    LLM 驱动的文献推荐主入口。
    返回：{ query, results: [...], sources: {...}, warning? }
    """
    query = build_query_from_record(record)
    user_prompt = _build_user_prompt(record)

    raw = _call_llm(llm_service, provider, user_prompt)
    if not raw:
        return {'query': query, 'results': [], 'sources': {'llm': 0, 'verified': 0},
                'warning': 'LLM 未返回响应'}

    candidates = _parse_llm_output(raw)
    if not candidates:
        return {'query': query, 'results': [], 'sources': {'llm': 0, 'verified': 0},
                'warning': 'LLM 输出无法解析为论文列表'}

    verified = []
    arxiv_verified = 0
    doi_verified = 0
    dropped = 0
    seen_keys = set()

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

        resolved = None
        if arxiv_id:
            resolved = verify_by_arxiv(arxiv_id, title)
            if resolved:
                arxiv_verified += 1
        if not resolved and doi:
            resolved = verify_by_doi(doi, title)
            if resolved:
                doi_verified += 1

        if not resolved:
            dropped += 1
            continue

        # 去重：按 external_id 或规范化标题
        key = resolved.get('external_id') or _normalize_title(resolved['title'])[:80]
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # 附加 LLM 给出的 reason（便于前端展示相关性）
        reason = (p.get('reason') or '').strip()
        if reason:
            resolved['reason'] = reason[:150]
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
            'dropped': dropped
        },
        'warning': None if verified else '所有 LLM 候选均未通过真实性验证，请稍后重试'
    }
