"""
MinerU PDF 解析器

基于 OpenDataLab MinerU 3.x pipeline 后端实现的 PDF 结构化解析，
与 DoclingPDFParser 输出同构，可由 pdf_parser.PDFParser 路由统一调度。

中文论文解析相较 Docling 的优势：
  - 字符还原准确（不会出现 G → ß 等 CMap 错误）
  - 中文标点两侧不会强行插入空格
  - 表格输出 HTML 结构，保留单元格 bbox
  - 公式输出 LaTeX，可直接进入 LLM 分析
  - 滑动窗口机制支持长文档

模型缓存：通过 MINERU_MODEL_SOURCE + MODELSCOPE_CACHE / HF_HOME 环境变量控制
（在 app.py 中统一配置，指向 D 盘项目本地目录 .mineru_cache / .hf_cache）

协议：本文件仅调用 MinerU 公开 Python API；MinerU 3.1+ 采用
"MinerU Open Source License (based on Apache 2.0)"，商用无碍。
"""
import os
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional


class MineruPDFParser:
    """MinerU PDF 解析器（pipeline 后端，CPU 友好）

    核心流程（与 Docling 对齐）：
      1. pipeline_doc_analyze → 模型推理
      2. result_to_middle_json → 结构化中间 JSON（含 pdf_info.blocks）
      3. union_make(CONTENT_LIST) → 扁平化 content_list
      4. 映射到项目统一 schema：
         {text, structured_content=[{type,content,page,bbox,subtype}], metadata}
    """

    def __init__(self):
        self.structure_data: Dict[str, List[Dict[str, Any]]] = {}
        self._initialized = False
        # 延迟加载
        self._pipeline_doc_analyze = None
        self._result_to_middle_json = None
        self._union_make = None
        self._make_mode = None
        self._data_writer_cls = None

    # ── 延迟初始化 ─────────────────────────────────────────

    def _init_modules(self):
        """首次调用时加载 MinerU 模块（体积较大，启动期不做 import）"""
        if self._initialized:
            return

        print("🔄 MinerU 首次初始化，模型将按需下载到缓存目录...")
        # MinerU 3.x 公开 API
        from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
        from mineru.backend.pipeline.model_json_to_middle_json import (
            result_to_middle_json as pipeline_result_to_middle_json,
        )
        from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
        from mineru.data.data_reader_writer import FileBasedDataWriter
        from mineru.utils.enum_class import MakeMode

        self._pipeline_doc_analyze = pipeline_doc_analyze
        self._result_to_middle_json = pipeline_result_to_middle_json
        self._union_make = pipeline_union_make
        self._make_mode = MakeMode
        self._data_writer_cls = FileBasedDataWriter
        self._initialized = True
        print("✅ MinerU 解析器初始化完成")

    # ── 主入口 ─────────────────────────────────────────────

    def parse_pdf(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        使用 MinerU 解析 PDF
        返回：{'text': str, 'structured_content': list, 'metadata': dict}
        失败返回 None，由上层路由器决定是否回落其他引擎。
        """
        try:
            print(f"📄 MinerU 解析: {os.path.basename(filepath)}")

            # 内存保护：超大文件跳过 MinerU（由路由器转 PyMuPDF 降级）
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 80:
                print(f"⚠️ 文件过大 ({file_size_mb:.1f}MB > 80MB)，MinerU 跳过")
                return None

            self._init_modules()

            # 读取 PDF bytes
            with open(filepath, 'rb') as f:
                pdf_bytes = f.read()

            # 图片输出临时目录（content_list 中的 img_path 将写到此处；
            # 本项目不依赖这些图片文件，用完即删）
            with tempfile.TemporaryDirectory(prefix='mineru_') as tmp_dir:
                image_writer = self._data_writer_cls(tmp_dir)
                image_dir = os.path.basename(tmp_dir)

                # ── 1. 模型推理 ──
                infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_list = (
                    self._pipeline_doc_analyze(
                        pdf_bytes_list=[pdf_bytes],
                        lang_list=['ch'],             # 中文论文默认 'ch'（auto 亦可）
                        parse_method='auto',
                        formula_enable=True,
                        table_enable=True,
                    )
                )

                # ── 2. 中间 JSON ──
                middle_json = self._result_to_middle_json(
                    infer_results[0],
                    all_image_lists[0],
                    all_pdf_docs[0],
                    image_writer,
                    lang_list[0],
                    ocr_list[0],
                    formula_enable=True,
                    table_enable=True,
                )

                pdf_info = middle_json.get('pdf_info', []) or []
                num_pages = len(pdf_info)

                # ── 3. content_list（扁平、带 bbox + page_idx + type）──
                content_list = self._union_make(
                    pdf_info, self._make_mode.CONTENT_LIST, image_dir
                )

            # ── 4. 映射到项目统一 schema ──
            result: Dict[str, Any] = {
                'text': '',
                'structured_content': [],
                'metadata': {
                    'page_count': num_pages,
                    'title': os.path.splitext(os.path.basename(filepath))[0],
                    'author': '',
                    'parser': 'mineru',
                },
            }

            page_texts: Dict[int, List[str]] = {}
            structured: List[Dict[str, Any]] = []
            in_non_body = False  # 是否处于非正文章节（参考文献 / 致谢 / 附录 等）

            for item in content_list:
                # content_list 页码从 0 开始，项目里统一 1-based
                page_idx = item.get('page_idx', 0)
                page_no = int(page_idx) + 1 if isinstance(page_idx, (int, float)) else 1

                bbox = self._bbox_from_item(item)
                itype = item.get('type', 'text')

                if itype == 'text' or itype == 'equation':
                    raw_text = (item.get('text') or '').strip()
                    if not raw_text or self._is_noise(raw_text, page_no, num_pages):
                        continue
                    # 文本归一化：压缩多余空白、去零宽字符、处理中英间隔
                    text = self._normalize_text(raw_text)
                    if not text:
                        continue
                    text_level = item.get('text_level')  # 1=title, 2=section, ...
                    subtype = 'SectionHeader' if text_level else 'TextItem'

                    # 遇到标题时更新非正文状态；进入非正文后跳过其下所有内容
                    if text_level:
                        in_non_body = self._is_non_body_section(text)
                    if in_non_body:
                        continue

                    structured.append({
                        'type': 'text',
                        'content': text,
                        'page': page_no,
                        'bbox': bbox,
                        'subtype': subtype,
                    })
                    page_texts.setdefault(page_no, []).append(text)

                elif itype == 'image':
                    cap = ' '.join(item.get('img_caption') or [])
                    foot = ' '.join(item.get('img_footnote') or [])
                    desc = f"\n【图片】\n- 位置: 第 {page_no} 页\n- 内容: 此处包含图片\n"
                    if cap:
                        desc += f"- 图注: {cap}\n"
                    if foot:
                        desc += f"- 脚注: {foot}\n"
                    surrounding = '\n'.join(page_texts.get(page_no, [])[-5:])
                    structured.append({
                        'type': 'image',
                        'content': desc,
                        'page': page_no,
                        'bbox': bbox,
                        'surrounding_text': surrounding,
                        'metadata': {'caption': cap, 'footnote': foot},
                    })

                elif itype == 'table':
                    cap = ' '.join(item.get('table_caption') or [])
                    foot = ' '.join(item.get('table_footnote') or [])
                    html = item.get('table_body', '') or ''
                    table_data = self._html_table_to_array(html)
                    table_text = self._format_table_text(table_data, cap, foot)
                    structured.append({
                        'type': 'table',
                        'content': table_text,
                        'page': page_no,
                        'bbox': bbox,
                        'table_data': table_data,
                        'metadata': {'caption': cap, 'footnote': foot, 'html': html},
                    })

            # 拼接逐页文本：先合并同页碎片成完整段落，再按段落用 \n\n 分隔
            # （与 Docling 输出格式一致，便于下游复用）
            parts = []
            for pg in sorted(page_texts.keys()):
                parts.append(f"\n\n===== 第 {pg} 页 =====\n\n")
                merged_blocks = self._merge_text_blocks(page_texts[pg])
                parts.append('\n\n'.join(merged_blocks))
            result['text'] = ''.join(parts)
            result['structured_content'] = structured

            # 缓存（供 find_text_location 使用）
            self.structure_data[filepath] = structured

            text_cnt = sum(1 for x in structured if x['type'] == 'text')
            tbl_cnt = sum(1 for x in structured if x['type'] == 'table')
            pic_cnt = sum(1 for x in structured if x['type'] == 'image')
            print(f"✅ MinerU 解析完成: {num_pages} 页, "
                  f"{text_cnt} 文本块, {tbl_cnt} 表格, {pic_cnt} 图片")
            return result

        except ImportError as e:
            print(f"❌ MinerU 未安装或依赖缺失: {e}")
            return None
        except (MemoryError, RuntimeError) as e:
            print(f"❌ MinerU 内存/运行时错误: {e}")
            return None
        except Exception as e:
            print(f"❌ MinerU 解析失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ── 查询接口（与 DoclingPDFParser 对齐） ──────────────

    def find_text_location(self, filepath: str, text_to_find: str) -> Optional[Dict[str, Any]]:
        if not filepath or filepath not in self.structure_data:
            return None
        t = (text_to_find or '').strip()
        if not t:
            return None
        for item in self.structure_data[filepath]:
            if item['type'] == 'text' and t in item['content']:
                return {
                    'page': item['page'],
                    'bbox': item.get('bbox'),
                    'full_content': item['content'],
                }
        return None

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _bbox_from_item(item: Dict[str, Any]) -> Dict[str, float]:
        """MinerU bbox 格式 [x0, y0, x1, y1]（左上原点，y 向下）"""
        bb = item.get('bbox')
        if isinstance(bb, (list, tuple)) and len(bb) >= 4:
            return {
                'x0': float(bb[0]),
                'y0': float(bb[1]),
                'x1': float(bb[2]),
                'y1': float(bb[3]),
            }
        return {'x0': 0, 'y0': 0, 'x1': 0, 'y1': 0}

    # ── 文本清洗（与 Docling 对齐）────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        单块文本归一化：
          - 去除零宽字符、BOM 等不可见字符
          - 合并连续空白为单空格（保留换行交给上层段落合并处理）
          - 修复中文字符之间误插入的空格
          - 合并行尾英文连字符（hyphen + 换行）
        """
        if not text:
            return ''
        # 去零宽字符与 BOM
        t = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
        # 行尾英文连字符合并："informa-\ntion" → "information"
        t = re.sub(r'([A-Za-z])-\s*\n\s*([A-Za-z])', r'\1\2', t)
        # 段内换行改为空格，便于后续合并
        t = re.sub(r'\s*\n\s*', ' ', t)
        # 压缩连续空白
        t = re.sub(r'[ \t]+', ' ', t)
        # 中文字符之间的多余空格（MinerU 一般已处理，这里兜底）
        t = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', t)
        # 中文与 ASCII 交界处不应有空格 → 删除
        t = re.sub(r'([\u4e00-\u9fff])\s+([A-Za-z0-9])', r'\1\2', t)
        t = re.sub(r'([A-Za-z0-9])\s+([\u4e00-\u9fff])', r'\1\2', t)
        return t.strip()

    @staticmethod
    def _smart_join(texts: List[str]) -> str:
        """
        智能合并文本碎片：
          - 中文/CJK 字符之间不加空格
          - 拉丁字符/数字之间加空格
          - 中文与拉丁字符之间不加空格（保持紧凑）
        """
        if not texts:
            return ''
        if len(texts) == 1:
            return texts[0]
        result = texts[0]
        for i in range(1, len(texts)):
            prev_char = result[-1] if result else ''
            next_char = texts[i][0] if texts[i] else ''
            need_space = (
                prev_char.isascii() and prev_char.isalnum() and
                next_char.isascii() and next_char.isalnum()
            )
            if need_space:
                result += ' ' + texts[i]
            else:
                result += texts[i]
        return result

    @classmethod
    def _merge_text_blocks(cls, blocks: List[str]) -> List[str]:
        """
        合并同页的碎片文本块为完整段落：
          - SectionHeader（以数字编号或纯大写开头）独立成段
          - 连续短文本（<80 字且不以句末标点结尾）合并为一段
          - 长文本（>=80 字或以句末标点结尾）独立成段
        """
        if not blocks:
            return []
        merged: List[str] = []
        buffer: List[str] = []
        sentence_end = re.compile(r'[。！？.!?;；]$')
        heading_pat = re.compile(r'^(\d+(\.\d+)*\s|[A-Z][A-Z\s]{2,})')
        for blk in blocks:
            is_heading = bool(heading_pat.match(blk))
            is_long = len(blk) >= 80
            ends_sentence = bool(sentence_end.search(blk))
            if is_heading:
                if buffer:
                    merged.append(cls._smart_join(buffer))
                    buffer = []
                merged.append(blk)
            elif is_long or ends_sentence:
                buffer.append(blk)
                merged.append(cls._smart_join(buffer))
                buffer = []
            else:
                buffer.append(blk)
        if buffer:
            merged.append(cls._smart_join(buffer))
        return merged

    @staticmethod
    def _is_non_body_section(heading: str) -> bool:
        """
        判断标题是否属于非正文章节（参考文献、附录、致谢、作者简介等）。
        返回 True 表示从这个标题开始到下一个正文标题之间的内容都不纳入正文。
        """
        h = heading.lower().strip()
        # 去掉开头的编号（如 "7. References" → "references"）
        h_clean = re.sub(r'^[\d.\s]+', '', h).strip()
        non_body_patterns = [
            r'^references?$', r'^bibliography$', r'^参考文献',
            r'^appendix', r'^附录',
            r'^acknowledge?ments?$', r'^致谢',
            r'^author', r'^作者简介', r'^作者信息',
            r'^biograph', r'^about the author',
            r'^conflict.{0,5}interest', r'^funding', r'^基金',
            r'^supplementary', r'^补充材料',
            r'^declarations?$', r'^ethics',
            r'^data availability',
        ]
        for pat in non_body_patterns:
            if re.match(pat, h_clean, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _is_noise(text: str, page_no: int = 0, total_pages: int = 0) -> bool:
        """噪声过滤（页码、页眉页脚、极短碎片）— 规则与 Docling 版对齐"""
        t = text.strip()
        if len(t) <= 2:
            return True
        if t.isdigit():
            return True
        patterns = [
            r'^\d+$',
            r'^-\s*\d+\s*-$',
            r'^第\s*\d+\s*页',
            r'^page\s*\d+',
            r'^©\s*\d{4}',
            r'^copyright',
            r'^\d{4}\s+(association|conference|ieee|acm)',
            r'^(vol|volume)\.?\s*\d',
            r'^(doi|arxiv|issn)[:\s]',
        ]
        low = t.lower()
        for pat in patterns:
            if re.match(pat, low):
                return True
        if re.match(r'^[\d\s,.;:\-\u2013\u2014]+$', t):
            return True
        return False

    @staticmethod
    def _html_table_to_array(html: str) -> List[List[str]]:
        """极简 HTML table → 二维数组（不依赖 bs4 以降低启动开销）"""
        if not html:
            return []
        rows: List[List[str]] = []
        # 提取所有 <tr>...</tr>
        for tr_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.I | re.S):
            row_html = tr_match.group(1)
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.I | re.S)
            row = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def _format_table_text(table_data: List[List[str]], caption: str = '', footnote: str = '') -> str:
        if not table_data:
            return (caption or '') + (('\n' + footnote) if footnote else '')
        lines = ['\n【表格】']
        if caption:
            lines.append(f"标题: {caption}")
        lines.append('')
        header = table_data[0]
        lines.append(' | '.join(header))
        lines.append('-' * min(80, sum(len(c) + 3 for c in header)))
        for row in table_data[1:]:
            lines.append(' | '.join(row))
        if footnote:
            lines.append(f"\n脚注: {footnote}")
        return '\n'.join(lines)
