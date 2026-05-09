# -*- coding: utf-8 -*-
"""
文本文体类型检测器（规则打分 + 特征提取，零 LLM 开销）

职责：
  1. 基于文本表层特征（引用标记、摘要/参考文献结构、通讯社词汇、图表密度等）
     对文档做文体分类；
  2. 为每种文体输出一段定制化的 LLM 分析指引（genre_hint），可直接注入
     ANALYZE_SYSTEM_PROMPT 中的 {genre_hint} 占位符；
  3. 同时返回命中特征，便于日志/调试与前端可选展示。

分类体系：
  academic_paper    学术论文
  review_paper      综述/文献综述
  technical_report  技术报告/白皮书
  news_report       新闻报道
  opinion_essay     评论/观点文章
  research_report   研究/行业报告
  popular_science   科普文章
  general           通用（兜底）
"""

import re
from typing import Dict, List, Tuple, Optional


# ─── 各文体的中文名 ────────────────────────────────────────────
GENRE_CN_NAME = {
    'academic_paper':   '学术论文',
    'review_paper':     '综述论文',
    'technical_report': '技术报告',
    'news_report':      '新闻报道',
    'opinion_essay':    '评论文章',
    'research_report':  '研究报告',
    'popular_science':  '科普文章',
    'general':          '通用文本',
}


# ─── 各文体对应的 LLM 分析指引（注入 system prompt）────────────
# 每段均遵循"角色+侧重点+产出偏好"结构，与原 prompt 的 <rules>/<scoring> 协同
GENRE_GUIDANCE = {
    'academic_paper': """<genre_guidance>
【文体判定】本文为 **学术论文**。请依此定制分析：
- 论点筛选偏重：研究问题/假设、方法创新、实验结果、关键结论、作者主张
- 论据偏重：实验数据、对比基线、显著性、案例；避免将引用他人结论误当作本文论点
- 关键数据偏重：定量指标（准确率/F1/AUC/RMSE 等）、样本规模（若涉及规模对比）、消融实验差异
- 专业术语偏重：研究对象、核心技术、数据集、评价指标、方法论
- 标题应体现研究主题和结论，而非文献综述型表达
</genre_guidance>""",

    'review_paper': """<genre_guidance>
【文体判定】本文为 **综述论文 / 文献综述**。请依此定制分析：
- 论点筛选偏重：本综述归纳出的研究脉络、范式演进、关键分歧、未解难题、未来方向
- 论据偏重：代表性方法/流派的概括总结、对比维度；引用标记密集时以"综述作者本人的评价判断"为核心论点
- 关键数据偏重：各方法在公共基准上的横向对比数值
- 专业术语偏重：领域范式、技术家族、数据基准、评价维度
- 避免把被综述的原始文献观点误记为本文论点——分清"他人工作" vs "综述结论"
</genre_guidance>""",

    'technical_report': """<genre_guidance>
【文体判定】本文为 **技术报告 / 白皮书**。请依此定制分析：
- 论点筛选偏重：架构决策、关键技术选型、性能突破、工程取舍、落地成效
- 论据偏重：性能指标、资源消耗、部署规模、可靠性数据
- 关键数据偏重：吞吐/延迟/QPS/成本/可用性等工程指标
- 专业术语偏重：系统组件、协议、框架、硬件平台
- 标题应体现"做了什么系统、解决了什么问题"
</genre_guidance>""",

    'news_report': """<genre_guidance>
【文体判定】本文为 **新闻报道**。请依此定制分析：
- 论点筛选偏重：核心事件（What/When/Where/Who/Why/How）、重要表态、政策发布、关键时间节点
- 论据偏重：直接引语、官方发言、权威机构数据、事件时间线
- 关键数据偏重：事件中涉及的金额/规模/人数/时间等事实数据
- 专业术语偏重：涉事机构、关键人物身份、相关政策名
- 标题应直指核心事件；避免把记者转述当作独立论点
</genre_guidance>""",

    'opinion_essay': """<genre_guidance>
【文体判定】本文为 **评论 / 观点文章**。请依此定制分析：
- 论点筛选偏重：作者明确的立场与主张（"应当""必须""我认为""反对"等措辞附近的完整句）
- 论据偏重：作者用于支撑其立场的事例、类比、数据、引用
- 关键数据偏重：作者用于强化观点的关键数字（若文中出现）
- 专业术语偏重：文章主题相关的社会/行业关键词
- 区分"作者主张"与"引用他人观点"——论点必须是作者立场
</genre_guidance>""",

    'research_report': """<genre_guidance>
【文体判定】本文为 **研究报告 / 行业报告**。请依此定制分析：
- 论点筛选偏重：核心结论、趋势判断、市场/行业拐点、风险提示、关键预测
- 论据偏重：市场数据、同比/环比对比、头部企业案例、历史对照
- 关键数据偏重：市场规模、增速、份额、渗透率、预测值；成对的对比数据优先（A vs B）
- 专业术语偏重：行业细分赛道、主要玩家、监管术语
- 标题应体现所分析的行业/市场及核心判断
</genre_guidance>""",

    'popular_science': """<genre_guidance>
【文体判定】本文为 **科普文章**。请依此定制分析：
- 论点筛选偏重：文章试图向大众传递的核心科学观点/常识纠偏/原理解释
- 论据偏重：通俗解释、类比比喻、日常案例、权威科学结论
- 关键数据偏重：有说服力的基础科学数据（若出现）
- 专业术语偏重：被通俗化解释的基础科学概念
- 标题应体现科普主题，而非包装成学术表达
</genre_guidance>""",

    'general': """<genre_guidance>
【文体判定】文体未明确识别，采用 **通用分析策略**。按原规则提取最具信息量的论点和支撑论据即可。
</genre_guidance>""",
}


# ─── 辅助：字符类别统计 ────────────────────────────────────────
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_LATIN_WORD_RE = re.compile(r'[A-Za-z]{2,}')


def _count_cjk(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _extract_features(text: str, metadata: Optional[Dict] = None) -> Dict:
    """提取用于文体判定的表层特征。"""
    metadata = metadata or {}
    text_len = max(1, len(text))
    cjk_chars = _count_cjk(text)
    # 粗略"千字"度量：中文以汉字计，英文以单词近似 1.5 字符
    kilo_chars = max(1.0, text_len / 1000.0)

    # ── 学术/综述类特征 ──
    # 参考文献段落：匹配结尾区域的"参考文献"或"References"
    tail = text[-max(len(text) // 6, 500):]
    has_references = bool(re.search(
        r'(?:^|\n|。)\s*(?:参\s*考\s*文\s*献|[Rr]eferences|[Bb]ibliography)\s*(?:\n|$|：)',
        tail
    )) or bool(re.search(r'\n\s*\[\s*\d+\s*\][^\n]{10,}', text))

    # 摘要（文章前 1/6 区间）
    head = text[:max(len(text) // 6, 500)]
    has_abstract = bool(re.search(
        r'(?:^|\n)\s*(?:摘\s*要|[Aa]bstract|[Ss]ummary)\s*[:：\n]',
        head
    ))

    # 关键词
    has_keywords = bool(re.search(
        r'(?:^|\n)\s*(?:关\s*键\s*词|[Kk]eywords?)\s*[:：]',
        text
    ))

    # 引用标记：[1]、[1,2]、[1-3]、（Author, 2023）、（2023）
    bracket_refs = len(re.findall(r'\[\s*\d+(?:\s*[,，\-–]\s*\d+)*\s*\]', text))
    year_refs = len(re.findall(
        r'[（(](?:[A-Z][A-Za-z\u4e00-\u9fff\s\.]{0,40},?\s*)?\d{4}[a-z]?[）)]',
        text
    ))
    citation_count = bracket_refs + year_refs

    # DOI
    doi_count = len(re.findall(r'10\.\d{4,9}/[^\s"\'，。；）)]+', text))

    # 综述特征词
    review_hits = sum(1 for kw in
        ('综述', '文献综述', '文献回顾', '研究综述',
         'a review of', 'a survey of', 'literature review')
        if kw.lower() in text.lower())

    # ── 技术报告特征 ──
    code_fences = len(re.findall(r'```', text))
    version_tags = len(re.findall(r'\bv\d+\.\d+(?:\.\d+)?\b', text))
    tech_kw_hits = sum(1 for kw in
        ('架构', '模块', '接口', '部署', '服务端', '客户端', '吞吐', '延迟',
         'QPS', 'SDK', 'API', '白皮书', '技术方案', '系统设计')
        if kw in text)

    # ── 新闻报道特征 ──
    news_agency_hits = sum(1 for kw in
        ('新华社', '中新社', '人民日报', '路透社', '美联社', '法新社',
         '彭博社', '（记者', '本报', '据报道', '报道称', '日电')
        if kw in text)
    # 电头/日期行："YYYY年M月D日"在开头出现
    dateline = bool(re.search(
        r'^[^\n]{0,80}\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日',
        text[:500]
    ))

    # ── 评论/观点文章特征 ──
    opinion_hits = 0
    for kw in ('笔者认为', '我们认为', '我认为', '我们主张', '应当',
               '必须认识到', '反对', '值得警惕', '不可否认',
               '可以预见', '有理由相信', '在笔者看来'):
        opinion_hits += text.count(kw)

    # ── 研究/行业报告特征 ──
    percent_matches = len(re.findall(r'\d+(?:\.\d+)?\s*%', text))
    percent_density = percent_matches / kilo_chars  # per 1k chars
    chart_table_hits = len(re.findall(r'(?:图|表|[Ff]igure|[Tt]able)\s*\d+', text))
    market_kw_hits = sum(1 for kw in
        ('市场规模', '同比', '环比', '份额', '渗透率', '增速',
         '行业', '头部企业', '研究报告', '预计到')
        if kw in text)

    # ── 科普文章特征 ──
    science_pop_hits = sum(1 for kw in
        ('简单来说', '打个比方', '换句话说', '可以把它想象', '其实',
         '通俗来讲', '一句话', '别担心', '你可能听说过')
        if kw in text)

    # ── 段落/句子风格特征 ──
    paragraphs = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
    avg_para_len = (sum(len(p) for p in paragraphs) / len(paragraphs)) if paragraphs else 0

    return {
        'text_len': text_len,
        'cjk_chars': cjk_chars,
        'kilo_chars': kilo_chars,
        'has_abstract': has_abstract,
        'has_keywords': has_keywords,
        'has_references': has_references,
        'citation_count': citation_count,
        'bracket_refs': bracket_refs,
        'year_refs': year_refs,
        'doi_count': doi_count,
        'review_hits': review_hits,
        'code_fences': code_fences,
        'version_tags': version_tags,
        'tech_kw_hits': tech_kw_hits,
        'news_agency_hits': news_agency_hits,
        'dateline': dateline,
        'opinion_hits': opinion_hits,
        'percent_matches': percent_matches,
        'percent_density': round(percent_density, 3),
        'chart_table_hits': chart_table_hits,
        'market_kw_hits': market_kw_hits,
        'science_pop_hits': science_pop_hits,
        'avg_para_len': int(avg_para_len),
    }


def _score_genres(f: Dict) -> Dict[str, float]:
    """根据特征为每种文体打分。"""
    scores: Dict[str, float] = {g: 0.0 for g in GENRE_CN_NAME}

    # 学术论文：摘要 + 参考文献 + 引用标记 + DOI
    s = 0.0
    if f['has_abstract']:      s += 3.0
    if f['has_references']:    s += 3.0
    if f['has_keywords']:      s += 1.5
    s += min(f['citation_count'] / 8.0, 4.0)   # 上限 4
    s += min(f['doi_count'] * 1.5, 3.0)
    scores['academic_paper'] = s

    # 综述论文：在学术论文基础上，综述词命中 + 引用更密集
    s = scores['academic_paper'] * 0.5
    s += f['review_hits'] * 2.5
    if f['citation_count'] >= 15:
        s += 2.0
    scores['review_paper'] = s

    # 技术报告：代码块 + 版本号 + 技术关键词；但无学术引用
    s = 0.0
    s += min(f['code_fences'] / 2.0, 3.0)
    s += min(f['version_tags'] * 0.8, 2.0)
    s += min(f['tech_kw_hits'] * 0.4, 3.0)
    if not f['has_references']:
        s += 0.5
    scores['technical_report'] = s

    # 新闻报道：通讯社 + 电头 + 较短篇幅
    s = 0.0
    s += f['news_agency_hits'] * 1.5
    if f['dateline']:         s += 2.0
    if f['text_len'] < 4000:  s += 1.0
    if not f['has_references'] and not f['has_abstract']:
        s += 0.5
    scores['news_report'] = s

    # 评论/观点：立场化措辞密度高；引用较少
    s = 0.0
    s += min(f['opinion_hits'] * 0.8, 5.0)
    if not f['has_references']:
        s += 0.5
    scores['opinion_essay'] = s

    # 研究/行业报告：百分比密度 + 图表 + 市场词汇
    s = 0.0
    s += min(f['percent_density'] * 3.0, 4.0)
    s += min(f['chart_table_hits'] * 0.3, 3.0)
    s += min(f['market_kw_hits'] * 0.6, 3.0)
    scores['research_report'] = s

    # 科普：通俗词 + 低引用密度 + 段落偏短
    s = 0.0
    s += min(f['science_pop_hits'] * 1.0, 4.0)
    if f['citation_count'] <= 3:
        s += 1.0
    if 0 < f['avg_para_len'] < 200:
        s += 0.5
    scores['popular_science'] = s

    # 通用兜底：恒定的低分
    scores['general'] = 1.0

    return scores


def detect_genre(text: str, metadata: Optional[Dict] = None) -> Dict:
    """
    主入口：检测文本文体类型。

    Returns:
        {
          'genre':        'academic_paper' | 'review_paper' | ...,
          'genre_name':   '学术论文',  # 中文名
          'confidence':   0.0 ~ 1.0,
          'scores':       {...各文体的原始分...},
          'features':     {...命中的表层特征...},
          'guidance':     '<genre_guidance>...</genre_guidance>',  # 可直接注入 system prompt
        }
    """
    if not text or len(text.strip()) < 50:
        return {
            'genre': 'general',
            'genre_name': GENRE_CN_NAME['general'],
            'confidence': 0.0,
            'scores': {},
            'features': {},
            'guidance': GENRE_GUIDANCE['general'],
        }

    features = _extract_features(text, metadata)
    scores = _score_genres(features)

    ranked: List[Tuple[str, float]] = sorted(
        scores.items(), key=lambda kv: kv[1], reverse=True
    )
    top_genre, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # top_score 过低时退化为 general
    if top_score < 2.0:
        top_genre = 'general'

    # 置信度：(top - second) / top；top 越大、差距越大越置信
    confidence = 0.0
    if top_score > 0:
        confidence = max(0.0, min(1.0, (top_score - second_score) / top_score))
    # 轻微放大高分的置信下限
    if top_score >= 6.0:
        confidence = max(confidence, 0.6)

    return {
        'genre': top_genre,
        'genre_name': GENRE_CN_NAME[top_genre],
        'confidence': round(confidence, 3),
        'scores': {k: round(v, 2) for k, v in scores.items()},
        'features': features,
        'guidance': GENRE_GUIDANCE.get(top_genre, GENRE_GUIDANCE['general']),
    }
