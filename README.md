# 智能文章重点分析与标注

> 基于 Vue 3 + Flask + DeepSeek-R1 / Qwen3.5-Plus 的 AI 文档深度分析与物理标注

---

## 技术栈

### 整体架构示意图
![alt text](image.png)

### 前端
| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 响应式 UI 框架 |
| Pinia | 全局状态管理（文档、API 选择、聊天记录） |
| Vite | 构建与热更新 |

### 后端
| 技术 | 用途 |
|------|------|
| Flask | RESTful API 服务 |
| SQLite | 分析记录持久化存储 |
| python-dotenv | 环境变量管理（API 密钥隔离） |
| jieba | 中文分词（关键词统计） |

### PDF 处理（三库协同）
| 技术 | 职责 |
|------|------|
| **PyMuPDF (fitz)** | 图片提取、元数据读取、PDF 页面叠加合并 |
| **pdfplumber** | 字符级精确坐标提取、表格识别 |
| **reportlab** | 创建透明高亮覆盖层（矢量图形绘制） |

### 大模型 API
| 模型 | 用途 | 接口 |
|------|------|------|
| DeepSeek-R1 (`deepseek-reasoner`) | 文档深度分析（默认）、AI 对话 | DeepSeek API |
| Qwen3.5-Plus (`qwen3.5-plus`) | 快速分析（可选） | 阿里云百炼 DashScope |

---

## 文件处理流程

```
用户上传文件
      │
      ▼
┌─────────────────────────────────────────────────┐
│                DocumentParser                   │
│  .pdf  → EnhancedPDFParser                     │
│            ├── pdfplumber: 逐页提取文字+表格     │
│            ├── PyMuPDF:    提取图片+元数据       │
│            └── 输出: text + structured_content  │
│  .docx → python-docx                            │
│  .doc  → win32com 子进程（解决 COM/STA 冲突）   │
│  .html → BeautifulSoup                          │
│  URL   → EnhancedWebParser (requests + BS4)    │
└─────────────────────────────────────────────────┘
      │ text + structured_data
      ▼
┌─────────────────────────────────────────────────┐
│                TextAnalyzer.analyze()            │
│  1. 构建 extra_context（表格/图片数量提示）      │
│  2. 调用 LLMService.analyze_text()              │
│     ├── PDF: 使用 DeepSeek 官方文件格式包装      │
│     │   [file name]: xxx.pdf                    │
│     │   [file content begin] ... [file content end] │
│     └── 其他: 直接发送文本                      │
│  3. 解析 JSON → _process_llm_result()           │
│  4. 失败则降级到 jieba 传统分词                  │
└─────────────────────────────────────────────────┘
      │ keypoints + highlights + summary
      ▼
┌─────────────────────────────────────────────────┐
│               物理标注（可选）                   │
│  PDF  → annotate_pdf()  三层架构（见下文）       │
│  DOCX → annotate_docx() python-docx XML 标注    │
│  HTML → annotate_html() 内联 style 注入         │
└─────────────────────────────────────────────────┘
      │ annotated_url
      ▼
   存入 SQLite → 返回前端
```

---

## Prompt 设计思想

系统提示词围绕 **"穿透式分析"** 核心理念设计，分六个步骤引导模型：

### 核心原则

**1. 反直觉提取**
不提取显而易见的常识或背景，专注"独特主张"、"突发结论"和"关键转折点"——这些才是文档的信息增量。

**2. 零公差引用（最关键约束）**
`point` 和 `evidence.text` 必须是原文中**逐字精确复制**的连续字符串，包括标点、空格、数字。这是 PDF 物理标注的核心依据——字符完全一致，pdfplumber 才能精准定位。

**3. 结构化数量控制**
根据文档长度自动调整论点数量（1-5个），避免短文过度提取和长文遗漏关键点。

### 返回协议设计

```json
{
  "core_arguments": [
    {
      "point": "原文逐字复制的核心主张",
      "point_page": 3,
      "point_context": "包含 point 的完整原句（15-30字，用于消歧定位）",
      "annotation_label": "核心结论",
      "evidence": [
        {
          "text": "原文逐字复制的支撑证据",
          "page": 5,
          "context": "包含 evidence 的完整原句（消歧用）"
        }
      ],
      "importance": 95,
      "rationale": "打分理由"
    }
  ],
  "summary": "一句话概括",
  "title": "文章主旨标题"
}
```

**字段设计意图：**
- `point_page` / `page`：向 pdfplumber 提供页码提示，将搜索范围从全文压缩到 3 页以内，显著提升定位效率
- `point_context`：当同一短语在同页出现多次时，通过上下文句子精确区分，解决定位歧义
- `annotation_label`：4-6 字中文标签，直接渲染到 PDF 左侧竖线旁的边注中
- `importance`（0-100）：95+ 为核心创新观点；80-94 为强力支撑论证；60 以下不列入

### 重要性评分标准

| 分段 | 含义 |
|------|------|
| 95-100 | 核心创新观点、颠覆性结论、独家数据 |
| 80-94  | 强力支撑论证、关键转折点 |
| 60-79  | 辅助性逻辑推导、背景说明 |
| < 60   | 过滤，不列入结果 |

---

## PDF 标注三层架构

PDF 物理标注是系统最复杂的部分，采用三个库分工协作：

```
pdfplumber → reportlab → PyMuPDF
  字符定位    覆盖层绘制   页面合并
```

### Layer 1：pdfplumber 字符级定位

普通的文本搜索（如 `page.search()` ）在中文 PDF 中常因字体编码、连字符、换行分割而失败。系统采用字符级定位算法：

```python
# 提取页面全部非空白字符
chars = page.chars
char_str = ''.join(c['text'] for c in non_blank)

# 去空格匹配目标文本
target_clean = re.sub(r'\s+', '', target_text)
idx = char_str.lower().find(target_clean[:50])

# 按 top 坐标分行（差异 < 4pt 视为同行）
# 为多行长文本分别生成独立 bbox
```

这样即使目标文本跨越多行排版，每行也能生成准确的边界框。

同时利用大模型返回的 `page_hint` 将搜索范围缩小到目标页 ± 1 页，避免全文扫描。

### Layer 2：reportlab 创建透明覆盖层

reportlab 在内存中绘制一个与原 PDF 等尺寸的**全透明覆盖 PDF**，为每处标注绘制：
- 半透明彩色矩形（alpha=0.22）
- 同色实线边框（alpha=0.60）
- 左侧 2.8pt 分类竖线（alpha=0.92）

**坐标系转换**（这是关键细节）：
```python
# pdfplumber 坐标系：左上角原点，top = 距顶部距离（y 向下增）
# reportlab 坐标系：左下角原点，y 向上增
reportlab_y = page_height - pdfplumber_bottom
```

### Layer 3：PyMuPDF 叠加合并

将 reportlab 生成的覆盖层通过 `show_pdf_page()` 叠加到原始 PDF 每一页：

```python
original[pg_num].show_pdf_page(
    original[pg_num].rect, overlay, pg_num
)
original.save(output_path, garbage=4, deflate=True)
```

最终输出的标注 PDF **不破坏原文**，覆盖层是独立的矢量图层，支持文字选中复制。

### 视觉规范

| 类型 | 颜色 | 矩形透明度 | 竖线透明度 | 含义 |
|------|------|-----------|-----------|------|
| 核心论点 | `#ff6b6b` 红色 | 22% | 92% | 文章核心主张 |
| 支撑论据 | `#51cf66` 绿色 | 22% | 92% | 佐证数据/逻辑 |

---

## 快速开始

### 第一次部署（一键安装）

```bash
install.bat
```

脚本会自动：检查 Python/Node.js → 安装 Python 依赖 → 从 `.env.example` 生成 `.env` → 安装前端依赖。

### 配置 API 密钥

编辑 `backend/.env`（首次运行后自动生成）：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
QWEN_API_KEY=your_qwen_api_key_here
```

- DeepSeek Key：https://platform.deepseek.com/
- Qwen Key：https://bailian.console.aliyun.com/

### 启动系统

```bash
start.bat
```

访问 http://localhost:3000

---

## 项目结构

```
GraDesign_one/
├── backend/
│   ├── app.py                  # Flask 主应用，RESTful 路由
│   ├── llm_service.py          # 多提供商 LLM 服务（DeepSeek / Qwen）
│   ├── text_analyzer.py        # 文本分析器：LLM 调用、结果处理、PDF/DOCX 标注
│   ├── pdf_parser_enhanced.py  # 增强 PDF 解析器（文字+表格+图片）
│   ├── document_parser.py      # 文档入口：PDF/DOCX/DOC/HTML/URL 分发
│   ├── web_parser_enhanced.py  # 增强网页解析器
│   ├── database.py             # SQLite 数据库操作
│   ├── exporter.py             # 导出功能（PDF/DOCX）
│   ├── requirements.txt        # Python 依赖
│   ├── .env                    # API 密钥（不提交 Git）
│   └── .env.example            # 密钥配置模板（提交 Git）
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── Navbar.vue       # 顶栏（含 API 引擎切换）
│       │   ├── DocumentViewer.vue # 左侧文档/PDF 查看器
│       │   ├── Sidebar.vue      # 右侧面板（关键点/摘要/统计/AI 对话）
│       │   ├── AiChatTab.vue    # AI 对话窗口（联动当前文档上下文）
│       │   ├── UploadModal.vue  # 上传弹窗
│       │   └── HistoryModal.vue # 历史记录
│       └── stores/
│           └── document.js      # Pinia Store（文档状态、API 选择、聊天）
├── install.bat                  # 首次安装脚本
└── start.bat                    # 日常启动脚本
```

---

## 注意事项

- 文件大小上限：16 MB
- `.doc` 格式解析需要本机安装 Microsoft Word（通过 win32com 调用）
- DeepSeek-R1 响应时间约 30-120 秒（推理模型较慢但质量高）
- `deepseek-reasoner` 不支持 `response_format: json_object`，系统已通过提示词约束输出格式
- 建议使用 Chrome / Edge 浏览器

---

## License

MIT......
