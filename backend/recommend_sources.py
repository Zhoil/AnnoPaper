# -*- coding: utf-8 -*-
"""
文献推荐数据源注册表（单一数据源）。

职责：
  1. 按文体（学术 / 新闻 / 通用）集中登记允许的外部数据源与官网 URL。
  2. 提供渲染方法，将数据源列表格式化为可插入 system prompt 的文本块。
  3. 从 NEWS 源自动派生域名白名单，供 URL 白名单验证直接复用。

上游消费方：
  - prompts.py：拼接 RECOMMEND_SYSTEM_PROMPT / _NEWS / _GENERAL 的"参考库"段落
  - llm_recommender.py：URL 白名单校验新闻类推荐
"""

from typing import List, Dict
from urllib.parse import urlparse


# ─── 学术类数据源（学术论文 / 综述 / 技术报告）───
ACADEMIC_SOURCES: List[Dict[str, str]] = [
    {'name': 'arXiv',            'url': 'https://arxiv.org/',
     'note': '物理、计算机、数学、统计、经济等预印本'},
    {'name': 'ACL Anthology',    'url': 'https://aclanthology.org/',
     'note': '自然语言处理会议论文'},
    {'name': 'Semantic Scholar', 'url': 'https://www.semanticscholar.org/',
     'note': '聚合 NeurIPS / ICML / AAAI / IEEE 等'},
    {'name': 'DOI',              'url': 'https://doi.org/',
     'note': '所有正式发表论文的持久链接'},
]

# ─── 新闻 / 评论类数据源 ───
NEWS_SOURCES: List[Dict[str, str]] = [
    {'name': '新华网',             'url': 'https://www.news.cn/'},
    {'name': '人民网',             'url': 'https://www.people.com.cn/'},
    {'name': '澎湃新闻',           'url': 'https://www.thepaper.cn/'},
    {'name': '路透社',             'url': 'https://www.reuters.com/'},
    {'name': 'BBC News',           'url': 'https://www.bbc.com/news'},
    {'name': 'The Guardian',       'url': 'https://www.theguardian.com/'},
    {'name': 'The New York Times', 'url': 'https://www.nytimes.com/'},
    {'name': 'Bloomberg',          'url': 'https://www.bloomberg.com/'},
]

# ─── 通用 / 科普 / 行业报告类数据源 ───
GENERAL_SOURCES: List[Dict[str, str]] = [
    {'name': 'OpenAlex',     'url': 'https://openalex.org/',
     'note': '全学科 2.5 亿篇文献元数据'},
    {'name': 'Wikipedia',    'url': 'https://wikipedia.org/',
     'note': '权威百科词条'},
    {'name': 'Crossref/DOI', 'url': 'https://doi.org/',
     'note': '正式发表文献持久链接'},
    {'name': 'arXiv',        'url': 'https://arxiv.org/',
     'note': '预印本论文'},
]


# ───────────────────────────── 渲染工具 ─────────────────────────────

def _display_width(s: str) -> int:
    """近似显示宽度：中文字符算 2，其余算 1，用于对齐中英混排。"""
    return sum(2 if '\u4e00' <= ch <= '\u9fff' else 1 for ch in s)


def _render_block(sources: List[Dict[str, str]], name_width: int = 16) -> str:
    """将数据源列表渲染为带对齐的 prompt 文本块。"""
    lines = []
    for s in sources:
        name = s['name']
        pad = ' ' * max(1, name_width - _display_width(name))
        line = f"  - {name}{pad}{s['url']}"
        note = s.get('note')
        if note:
            line += f"  （{note}）"
        lines.append(line)
    return '\n'.join(lines)


def render_academic_sources() -> str:
    """学术类数据源块（供 RECOMMEND_SYSTEM_PROMPT 引用）。"""
    return _render_block(ACADEMIC_SOURCES)


def render_news_sources() -> str:
    """新闻类数据源块（供 RECOMMEND_SYSTEM_PROMPT_NEWS 引用）。"""
    return _render_block(NEWS_SOURCES)


def render_general_sources() -> str:
    """通用类数据源块（供 RECOMMEND_SYSTEM_PROMPT_GENERAL 引用）。"""
    return _render_block(GENERAL_SOURCES)


# ─────────────────────── 新闻域名白名单（自动派生）───────────────────────

def _extract_root_domain(url: str) -> str:
    """从 URL 提取根域名（剥离 www. 前缀）。"""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ''
    if host.startswith('www.'):
        host = host[4:]
    return host


# 主白名单由 NEWS_SOURCES 自动派生，避免与 prompt 文本列表手工同步
_PRIMARY_NEWS_DOMAINS = {_extract_root_domain(s['url']) for s in NEWS_SOURCES}
_PRIMARY_NEWS_DOMAINS.discard('')

# 补充别名（同一家媒体的其他域），此处集中维护
_NEWS_DOMAIN_ALIASES = [
    'xinhuanet.com',  # 新华网英文/旧域
    'bbc.co.uk',      # BBC 英国本土域
]

NEWS_DOMAIN_WHITELIST: List[str] = sorted(_PRIMARY_NEWS_DOMAINS.union(_NEWS_DOMAIN_ALIASES))
