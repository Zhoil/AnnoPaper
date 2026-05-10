"""
PDF 解析引擎路由器

策略（中文论文场景优先）：
  1) 首选 MinerU（中文字符还原更准，不会产生 G→ß；中文标点无强插空格；
     表格 HTML、公式 LaTeX、跨页合并）
  2) MinerU 失败/未安装 → 降级 Docling（保留已有集成与 .hf_cache 缓存）
  3) Docling 再失败 → 降级 PyMuPDF（纯文本兜底）

开关：
  环境变量 PDF_PARSER_ENGINE = 'mineru' | 'docling' | 'auto'（默认 auto 等同首选 MinerU）

对外接口与旧 DoclingPDFParser 保持一致：
  - parse_pdf(filepath) -> {'text', 'structured_content', 'metadata'}
  - find_text_location(filepath, text_to_find) -> Optional[Dict]
  - structure_data 属性用于下游缓存查询
"""
import os
from typing import Optional, Dict, Any


class PDFParser:
    """
    统一 PDF 解析路由器：MinerU 首选 + Docling 兜底 + PyMuPDF 最终兜底。
    """

    def __init__(self):
        self.engine_pref = os.environ.get('PDF_PARSER_ENGINE', 'auto').lower().strip()

        # 两个真实解析器都做懒加载（避免启动期同时加载两套大模型）
        self._mineru = None
        self._docling = None

        # 缓存最近一次成功使用的解析器，供 find_text_location 查询
        self._last_parser = None

    # ── 懒加载 ────────────────────────────────────────────

    def _get_mineru(self):
        if self._mineru is None:
            from pdf_parser_mineru import MineruPDFParser
            self._mineru = MineruPDFParser()
        return self._mineru

    def _get_docling(self):
        if self._docling is None:
            from pdf_parser_docling import DoclingPDFParser
            self._docling = DoclingPDFParser()
        return self._docling

    # ── 主入口 ────────────────────────────────────────────

    def parse_pdf(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        按路由策略依次尝试解析器。
        任一引擎成功则返回；全部失败返回 None。
        """
        order = self._resolve_engine_order()
        last_err = None

        for engine in order:
            try:
                if engine == 'mineru':
                    print(f"🎯 引擎选择: MinerU (pref={self.engine_pref})")
                    parser = self._get_mineru()
                    result = parser.parse_pdf(filepath)
                    if result and result.get('text'):
                        self._last_parser = parser
                        return result
                    print("⚠️ MinerU 返回空结果，尝试下一个引擎")
                elif engine == 'docling':
                    print(f"🎯 引擎选择: Docling (pref={self.engine_pref})")
                    parser = self._get_docling()
                    result = parser.parse_pdf(filepath)
                    if result and result.get('text'):
                        self._last_parser = parser
                        return result
                    print("⚠️ Docling 返回空结果，尝试下一个引擎")
            except Exception as e:
                last_err = e
                print(f"⚠️ {engine} 引擎异常: {e}")
                continue

        if last_err:
            print(f"❌ 所有 PDF 解析引擎均失败，最后一次错误: {last_err}")
        return None

    # ── 定位查询（用于下游 text_analyzer 的缓存命中） ───────

    def find_text_location(self, filepath: str, text_to_find: str) -> Optional[Dict[str, Any]]:
        # 优先问上次成功的解析器
        if self._last_parser is not None:
            try:
                hit = self._last_parser.find_text_location(filepath, text_to_find)
                if hit:
                    return hit
            except Exception:
                pass
        # 再兜底问另一引擎（若已初始化）
        for p in (self._mineru, self._docling):
            if p is not None and p is not self._last_parser:
                try:
                    hit = p.find_text_location(filepath, text_to_find)
                    if hit:
                        return hit
                except Exception:
                    continue
        return None

    @property
    def structure_data(self) -> Dict[str, Any]:
        """聚合所有已初始化解析器的缓存，向后兼容旧属性访问"""
        merged: Dict[str, Any] = {}
        for p in (self._mineru, self._docling):
            if p is not None and getattr(p, 'structure_data', None):
                merged.update(p.structure_data)
        return merged

    # ── 策略 ──────────────────────────────────────────────

    def _resolve_engine_order(self):
        """根据 PDF_PARSER_ENGINE 决定尝试顺序"""
        if self.engine_pref == 'mineru':
            return ['mineru']
        if self.engine_pref == 'docling':
            return ['docling']
        # auto：MinerU 优先 → Docling 兜底
        return ['mineru', 'docling']
