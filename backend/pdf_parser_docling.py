"""
Docling PDF 解析器
使用 Docling 库进行文档转换与结构化内容提取
模型缓存路径通过 HF_HOME 环境变量控制（在 app.py 中设置）
"""
import os
import re
from typing import List, Dict, Any, Optional


class DoclingPDFParser:
    """
    Docling PDF 解析器（v2 API）

    文档模型说明（Docling v2）：
      - document.texts:     TextItem / SectionHeaderItem / ListItem 列表
      - document.tables:    TableItem 列表
      - document.pictures:  PictureItem 列表
      - document.pages:     dict[int, PageItem] — 页面元数据
      - item.prov:          ProvenanceItem 列表，含 page_no + BoundingBox

    模型缓存：通过 HF_HOME 环境变量指向 backend/.hf_cache
    """

    def __init__(self):
        self.structure_data = {}
        self.converter = None  # 延迟初始化

    def _init_converter(self):
        """延迟初始化 Docling 转换器（首次解析时才加载模型，禁用 OCR 降低内存占用）"""
        if self.converter is not None:
            return

        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter

        print("🔄 Docling 首次初始化，模型将下载到 .hf_cache/...")
        try:
            # 尝试禁用 OCR 以减少内存占用
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            pipeline_options = PdfPipelineOptions(do_ocr=False)
            from docling.document_converter import PdfFormatOption
            self.converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF],
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
        except Exception as e:
            print(f"⚠️ Docling OCR 禁用配置失败，使用默认配置: {e}")
            self.converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF]
            )
        print("✅ Docling PDF 解析器初始化完成（模型缓存: .hf_cache）")

    def parse_pdf(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        使用 Docling 解析 PDF
        返回：{'text': str, 'structured_content': list, 'metadata': dict}
        """
        result = {
            'text': '',
            'structured_content': [],
            'metadata': {}
        }

        try:
            print(f"📄 Docling 解析: {os.path.basename(filepath)}")

            # 内存保护：大文件直接降级到 PyMuPDF
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 50:
                print(f"⚠️ 文件过大 ({file_size_mb:.1f}MB > 50MB)，跳过 Docling，降级使用 PyMuPDF")
                return self._fallback_pymupdf_parse(filepath)

            self._init_converter()

            # 执行转换
            conv_result = self.converter.convert(filepath)

            # 检查状态
            from docling.datamodel.base_models import ConversionStatus
            if conv_result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
                print(f"❌ Docling 转换失败: {conv_result.status}")
                return None
            if conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
                print("⚠️ Docling 转换部分成功，继续处理可用内容")

            document = conv_result.document

            # ── 元数据 ──
            num_pages = document.num_pages()
            result['metadata'] = {
                'page_count': num_pages,
                'title': document.name or '',
                'author': '',
            }

            # ── 方式一：使用 export_to_markdown() 获取完整文本（兜底）──
            full_md = document.export_to_markdown()

            # ── 方式二：按页分段文本（LLM 分析用，合并碎片 + 过滤噪声 + 过滤非正文）──
            page_texts = {}  # page_no -> [text_parts]
            skip_until_next_section = False  # 是否处于非正文章节中
            for item, _level in document.iterate_items():
                page_no = self._get_page_no(item)
                text = getattr(item, 'text', '')
                item_type = type(item).__name__

                # 检测章节标题，判断是否进入非正文区域
                if 'Header' in item_type or 'SectionHeader' in item_type:
                    if text and self._is_non_body_section(text.strip()):
                        skip_until_next_section = True
                        print(f"  ⏩ 跳过非正文章节: '{text.strip()[:50]}'")
                        continue
                    else:
                        skip_until_next_section = False

                if skip_until_next_section:
                    continue

                if text and text.strip():
                    clean = text.strip()
                    # 过滤噪声：纯页码、极短无意义碎片
                    if self._is_noise(clean, page_no, num_pages):
                        continue
                    page_texts.setdefault(page_no, []).append(clean)

            # 合并同页碎片文本为完整段落
            all_text_parts = []
            for pg in sorted(page_texts.keys()):
                all_text_parts.append(f"\n\n===== 第 {pg} 页 =====\n\n")
                merged = self._merge_text_blocks(page_texts[pg])
                all_text_parts.append('\n\n'.join(merged))

            result['text'] = ''.join(all_text_parts) if all_text_parts else full_md

            # ── 结构化内容提取（合并碎片文本块为完整段落）──
            # 1. 文本块 — 按页分组后合并相邻碎片
            page_raw_items = {}  # page_no -> [(text, bbox, subtype)]
            for txt_item in (document.texts or []):
                text = getattr(txt_item, 'text', '')
                if not text or not text.strip():
                    continue
                clean = text.strip()
                page_no = self._get_page_no(txt_item)
                if self._is_noise(clean, page_no, num_pages):
                    continue
                bbox = self._get_bbox(txt_item)
                item_subtype = type(txt_item).__name__
                page_raw_items.setdefault(page_no, []).append((clean, bbox, item_subtype))

            for pg in sorted(page_raw_items.keys()):
                merged_items = self._merge_structured_blocks(page_raw_items[pg])
                for content, bbox, subtype in merged_items:
                    result['structured_content'].append({
                        'type': 'text',
                        'content': content,
                        'page': pg,
                        'bbox': bbox,
                        'subtype': subtype,
                    })

            # 2. 表格
            for tbl_idx, tbl_item in enumerate(document.tables or []):
                page_no = self._get_page_no(tbl_item)
                bbox = self._get_bbox(tbl_item)
                table_data = self._extract_table_data(tbl_item, document)
                table_text = self._format_table_text(table_data, tbl_idx + 1)
                result['structured_content'].append({
                    'type': 'table',
                    'content': table_text,
                    'page': page_no,
                    'table_data': table_data,
                    'bbox': bbox,
                })

            # 3. 图片
            for pic_idx, pic_item in enumerate(document.pictures or []):
                page_no = self._get_page_no(pic_item)
                bbox = self._get_bbox(pic_item)
                # 获取图片周围文本上下文
                surrounding_text = self._get_surrounding_text(pic_item, page_texts.get(page_no, []))

                img_desc = f"\n【图片 {pic_idx + 1}】\n"
                img_desc += f"- 位置: 第 {page_no} 页\n"
                img_desc += "- 内容: 此处包含图片\n\n"

                result['structured_content'].append({
                    'type': 'image',
                    'content': img_desc,
                    'page': page_no,
                    'image_index': pic_idx,
                    'surrounding_text': surrounding_text,
                    'metadata': {},
                    'bbox': bbox,
                })

            # 缓存结构数据
            self.structure_data[filepath] = result['structured_content']

            text_count = len(document.texts or [])
            table_count = len(document.tables or [])
            pic_count = len(document.pictures or [])
            print(f"✅ Docling 解析完成: {num_pages} 页, "
                  f"{text_count} 文本块, {table_count} 表格, {pic_count} 图片")
            return result

        except (MemoryError, RuntimeError) as e:
            print(f"❌ Docling 内存/运行时错误，降级使用 PyMuPDF: {str(e)}")
            return self._fallback_pymupdf_parse(filepath)
        except Exception as e:
            print(f"❌ Docling 解析失败: {str(e)}")
            import traceback
            traceback.print_exc()
            # 降级使用 PyMuPDF
            print("🔄 尝试降级使用 PyMuPDF 解析...")
            return self._fallback_pymupdf_parse(filepath)

    # ── 工具方法 ──

    def _get_page_no(self, item) -> int:
        """从 item.prov 提取页码"""
        prov = getattr(item, 'prov', None)
        if prov and len(prov) > 0:
            return prov[0].page_no
        return 1

    def _get_bbox(self, item) -> Dict[str, float]:
        """从 item.prov[0].bbox 提取坐标"""
        prov = getattr(item, 'prov', None)
        if prov and len(prov) > 0:
            bb = prov[0].bbox
            if bb:
                return {
                    'x0': float(bb.l),
                    'y0': float(bb.t),
                    'x1': float(bb.r),
                    'y1': float(bb.b),
                }
        return {'x0': 0, 'y0': 0, 'x1': 0, 'y1': 0}

    def _is_non_body_section(self, heading: str) -> bool:
        """
        判断标题是否属于非正文章节（参考文献、附录、致谢、作者简介等）
        """
        h = heading.lower().strip()
        # 去掉开头的编号（如 "7. References" → "references"）
        h_clean = re.sub(r'^[\d.\s]+', '', h).strip()
        non_body_patterns = [
            r'^references?$', r'^bibliography$', r'^\u53c2\u8003\u6587\u732e',
            r'^appendix', r'^\u9644\u5f55',
            r'^acknowledge?ments?$', r'^\u81f4\u8c22',
            r'^author', r'^\u4f5c\u8005\u7b80\u4ecb', r'^\u4f5c\u8005\u4fe1\u606f',
            r'^biograph', r'^about the author',
            r'^conflict.{0,5}interest', r'^funding', r'^\u57fa\u91d1',
            r'^supplementary', r'^\u8865\u5145\u6750\u6599',
            r'^declarations?$', r'^ethics',
            r'^data availability',
        ]
        for pat in non_body_patterns:
            if re.match(pat, h_clean, re.IGNORECASE):
                return True
        return False

    def _is_noise(self, text: str, page_no: int = 0, total_pages: int = 0) -> bool:
        """
        判断文本是否为噪声（页码、页眉页脚、极短无意义碎片）
        噪声不送入 LLM 分析，也不写入结构化内容
        """
        t = text.strip()
        # 空或极短（≤3个非空白字符，排除标题编号如 '1', '2.1'）
        if len(t) <= 2:
            return True
        # 纯数字 — 通常是页码
        if t.isdigit():
            return True
        # 仅含单个标点
        if len(t) == 1 and not t.isalnum():
            return True
        # 常见页眉/页脚模式
        noise_patterns = [
            r'^\d+$',                      # 纯数字页码
            r'^-\s*\d+\s*-$',              # -3- 形式页码
            r'^第\s*\d+\s*页',              # 中文页码
            r'^page\s*\d+',                # 英文页码
            r'^\*\s*corresponding',         # 通讯作者脚注
            r'^proceedings of',             # 会议页脚
            r'^©\s*\d{4}',                 # 版权声明
            r'^copyright',                  # 版权声明
            r'^\d{4}\s+(association|conference|ieee|acm)', # 会议版权行
            r'^(vol|volume)\.?\s*\d',      # 期刊卷号
            r'^(doi|arxiv|issn)[:\s]',      # DOI/arXiv/ISSN
        ]
        t_lower = t.lower()
        for pat in noise_patterns:
            if re.match(pat, t_lower):
                return True
        # 仅包含数字+标点（如 "17716"）
        if re.match(r'^[\d\s,.;:\-\u2013\u2014]+$', t):
            return True
        # 作者/机构信息模式
        author_patterns = [
            r'[\w.+-]+@[\w-]+\.[\w.]+',           # 邮箱地址
            r'\buniversity\b', r'\binstitute\b',    # 机构名
            r'^received:.*accepted:', r'^published:',  # 期刊元数据
        ]
        for pat in author_patterns:
            if re.search(pat, t_lower):
                # 仅当文本较短时才过滤（避免误伤正文中提及大学的句子）
                if len(t) < 120:
                    return True
        return False

    def _merge_text_blocks(self, blocks: List[str]) -> List[str]:
        """
        合并同页的碎片文本块为完整段落。
        规则：
          - SectionHeader（以数字编号或纯大写开头）独立成段
          - 连续短文本（<80字且不以句末标点结尾）合并为一段
          - 长文本（>=80字或以句末标点结尾）独立成段
        """
        if not blocks:
            return []

        merged = []
        buffer = []

        sentence_end = re.compile(r'[。！？.!?;；]$')
        heading_pat = re.compile(r'^(\d+(\.\d+)*\s|[A-Z][A-Z\s]{2,})')

        for blk in blocks:
            is_heading = bool(heading_pat.match(blk))
            is_long = len(blk) >= 80
            ends_sentence = bool(sentence_end.search(blk))

            if is_heading:
                # 先刷出 buffer
                if buffer:
                    merged.append(' '.join(buffer))
                    buffer = []
                merged.append(blk)
            elif is_long or ends_sentence:
                buffer.append(blk)
                merged.append(' '.join(buffer))
                buffer = []
            else:
                buffer.append(blk)

        if buffer:
            merged.append(' '.join(buffer))

        return merged

    def _merge_structured_blocks(self, items: List[tuple]) -> List[tuple]:
        """
        合并结构化文本条目 [(text, bbox, subtype), ...]
        返回合并后的 [(merged_text, first_bbox, primary_subtype), ...]
        """
        if not items:
            return []

        sentence_end = re.compile(r'[。！？.!?;；]$')
        heading_pat = re.compile(r'^(\d+(\.\d+)*\s|[A-Z][A-Z\s]{2,})')

        merged = []
        buf_texts = []
        buf_bbox = None
        buf_subtype = None

        for text, bbox, subtype in items:
            is_heading = 'Header' in subtype or bool(heading_pat.match(text))
            is_long = len(text) >= 80
            ends_sentence = bool(sentence_end.search(text))

            if is_heading:
                if buf_texts:
                    merged.append((' '.join(buf_texts), buf_bbox, buf_subtype))
                    buf_texts = []
                merged.append((text, bbox, subtype))
                buf_bbox = None
                buf_subtype = None
            elif is_long or ends_sentence:
                buf_texts.append(text)
                if buf_bbox is None:
                    buf_bbox = bbox
                if buf_subtype is None:
                    buf_subtype = subtype
                merged.append((' '.join(buf_texts), buf_bbox, buf_subtype))
                buf_texts = []
                buf_bbox = None
                buf_subtype = None
            else:
                buf_texts.append(text)
                if buf_bbox is None:
                    buf_bbox = bbox
                if buf_subtype is None:
                    buf_subtype = subtype

        if buf_texts:
            merged.append((' '.join(buf_texts), buf_bbox or {'x0':0,'y0':0,'x1':0,'y1':0}, buf_subtype or 'TextItem'))

        return merged

    def _get_surrounding_text(self, pic_item, page_text_parts: List[str]) -> str:
        """获取图片周围的文本上下文（取整页文本的前后 200 字）"""
        if not page_text_parts:
            return ''
        full_page = '\n'.join(page_text_parts)
        # 取前 400 字作为上下文
        return full_page[:400].strip()

    def _extract_table_data(self, table_item, document=None) -> List[List[str]]:
        """从 Docling TableItem 提取二维数组"""
        data = []
        try:
            if document:
                df = table_item.export_to_dataframe(doc=document)
            else:
                df = table_item.export_to_dataframe()
            # 表头
            headers = [str(c) for c in df.columns]
            data.append(headers)
            # 数据行
            for _, row in df.iterrows():
                data.append([str(v) for v in row.values])
        except Exception:
            # fallback: 尝试 text 属性
            text = getattr(table_item, 'text', '')
            if text:
                data.append([text])
        return data

    def _format_table_text(self, table_data: List[List[str]], table_idx: int = 0) -> str:
        """将表格数据格式化为文本"""
        if not table_data:
            return "【表格】"

        lines = [f"\n【表格 {table_idx}】\n"]

        if table_data[0]:
            headers = [str(cell).strip() for cell in table_data[0]]
            lines.append(" | ".join(headers))
            lines.append("-" * 50)

        for row in table_data[1:]:
            row_str = " | ".join(str(cell).strip() for cell in row)
            lines.append(row_str)

        lines.append("")
        return "\n".join(lines)

    def find_text_location(self, filepath: str, text_to_find: str) -> Optional[Dict[str, Any]]:
        """
        在 PDF 中定位文本的页码和位置
        返回：{'page': int, 'bbox': dict, 'full_content': str} 或 None
        """
        if not filepath or not os.path.exists(filepath):
            return None

        # 优先使用缓存的结构数据
        if filepath in self.structure_data:
            text_clean = text_to_find.strip()
            for item in self.structure_data[filepath]:
                if item['type'] == 'text' and text_clean in item['content']:
                    return {
                        'page': item['page'],
                        'bbox': item.get('bbox'),
                        'full_content': item['content']
                    }

        return None

    def _fallback_pymupdf_parse(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        PyMuPDF 降级解析：当 Docling 失败/内存不足时，用 PyMuPDF 直接提取文本
        """
        try:
            import fitz
            doc = fitz.open(filepath)
            num_pages = len(doc)
            print(f"🔄 PyMuPDF 降级解析: {os.path.basename(filepath)} ({num_pages} 页)")

            page_texts = {}
            structured_content = []

            for page_idx in range(num_pages):
                page = doc[page_idx]
                page_no = page_idx + 1
                text = page.get_text('text')
                if text and text.strip():
                    clean = text.strip()
                    lines = [l for l in clean.split('\n') if l.strip() and not self._is_noise(l.strip(), page_no, num_pages)]
                    if lines:
                        page_texts[page_no] = lines
                        structured_content.append({
                            'type': 'text',
                            'content': '\n'.join(lines),
                            'page': page_no,
                            'bbox': {'x0': 0, 'y0': 0, 'x1': 0, 'y1': 0},
                            'subtype': 'TextItem',
                        })

            all_text_parts = []
            for pg in sorted(page_texts.keys()):
                all_text_parts.append(f"\n\n===== 第 {pg} 页 =====\n\n")
                all_text_parts.append('\n'.join(page_texts[pg]))

            doc.close()

            result = {
                'text': ''.join(all_text_parts),
                'structured_content': structured_content,
                'metadata': {
                    'page_count': num_pages,
                    'title': os.path.basename(filepath),
                    'author': '',
                    'parser': 'pymupdf_fallback',
                }
            }
            print(f"✅ PyMuPDF 降级解析完成: {num_pages} 页, {len(structured_content)} 文本块")
            return result

        except Exception as e:
            print(f"❌ PyMuPDF 降级解析也失败: {str(e)}")
            return None
