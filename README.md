<div align="center">
  <img src="images/AnnoPaper.png" alt="AnnoPaper智阅" width="180" />
  <h1>AnnoPaper智阅</h1>
  <p>
    <a href="README_EN.md"><img src="https://img.shields.io/badge/Language-English-blue?logo=googletranslate&logoColor=white" alt="English" /></a>
    <a href="backend/requirements.txt"><img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python" /></a>
    <a href="backend/app.py"><img src="https://img.shields.io/badge/Flask-Backend-000000?logo=flask&logoColor=white" alt="Flask" /></a>
    <a href="frontend/package.json"><img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" /></a>
    <a href="frontend/package.json"><img src="https://img.shields.io/badge/Node.js-16%2B-339933?logo=nodedotjs&logoColor=white" alt="Node.js" /></a>
    <a href="https://platform.deepseek.com/"><img src="https://img.shields.io/badge/DeepSeek--R1-LLM-6C47FF?logo=openai&logoColor=white" alt="DeepSeek-R1" /></a>
    <img src="https://img.shields.io/badge/Version-v3.0.0-orange.svg" alt="Version" />
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
  </p>
  <p><strong>基于 Vue 3 + Flask + Docling 结构化解析 + 多模型 LLM 引擎的 AI 文档深度分析与物理标注系统</strong></p>
  <p>📚 Docling 驱动文档结构化解析 · 🎯 字符级精准坐标定位标注 · 🧠 多模型 AI 深度分析 · 📄 PDF/DOCX/HTML/URL 全格式支持</p>
</div>

> 💡 **Docling** 作为本项目的**核心文档解析引擎**，提供了高级文档结构化提取能力（支持 OCR），能够智能识别表格、图片、公式等复杂元素，并自动输出结构化内容，显著提升了对复杂学术论文和报告的解析精度。当 Docling 不可用时，系统自动降级到 PyMuPDF 基础解析，确保服务弹性。

---

## 技术栈

### 整体架构示意图
![AnnoPaper 架构图](images/architecture.png)

### 前端
| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 响应式 UI 框架 |
| Pinia | 全局状态管理（文档、API 选择、聊天记录） |
| Vite | 构建与热更新 |
| Axios | HTTP 请求 |
| Marked | AI 对话 Markdown 渲染 |

### 后端
| 技术 | 用途 |
|------|------|
| Flask | RESTful API 服务 |
| SQLite | 分析记录持久化存储 |
| python-dotenv | 环境变量管理（API 密钥隔离） |
| jieba | 中文分词（关键词统计备用） |
| Docling | 高级文档结构化解析（OCR 可选） |

### PDF 处理（三库协同）
| 技术 | 职责 |
|------|------|
| **PyMuPDF (fitz)** | 图片提取、元数据读取、PDF 页面叠加合并、Docling 降级备选 |
| **pdfplumber** | 字符级精确坐标提取、表格识别 |
| **reportlab** | 创建透明高亮覆盖层（矢量图形绘制） |

### 大模型 API（三引擎可切换）
| 模型 | 用途 | 接口 |
|------|------|------|
| DeepSeek-R1 (`deepseek-reasoner`) | 文档深度分析（默认）、AI 对话 | DeepSeek API |
| Qwen3.6-Plus (`qwen3.6-plus`) | 快速分析（可选）、文件直传 | 阿里云百炼 DashScope |
| PipeLLM（多模型） | 第三方多引擎选择（GPT-5.4 / Claude 等） | OpenAI 兼容 API |

---

## 核心功能

- **多模型 AI 分析**：前端一键切换 DeepSeek / Qwen / PipeLLM 引擎，PipeLLM 支持模型下拉选择
- **PDF 物理标注**：基于 pdfplumber 字符级坐标定位，在原始 PDF 上精确高亮关键句，生成可下载的标注文档
- **多格式支持**：PDF、DOCX、DOC、HTML 文件及网页 URL，跨格式统一分析
- **两阶段分析**：阶段 1 独立分析图片和表格内容 → 阶段 2 全文深度分析（含图表上下文）
- **Map-Reduce 长文档处理**：超长文档自动分块 → 多轮 LLM 调用 → 结果合并，突破 token 限制
- **关键数据提取**：自动识别核心实验数据与对比指标，卡片化展示
- **专业词云**：LLM 提取文档核心专业术语，按重要性权重渲染词云
- **AI 对话**：联动当前文档上下文的智能问答窗口
- **Docling 增强解析**：支持 Docling 高级文档结构化提取，OCR 可选，内存保护 + PyMuPDF 自动降级
- **非正文过滤**：自动过滤参考文献、附录、作者信息、机构元数据等非正文内容

---

## 文件处理流程

```
用户上传文件
      │
      ▼
┌─────────────────────────────────────────────────┐
│                DocumentParser                   │
│  .pdf  → EnhancedPDFParser / DoclingParser      │
│            ├── pdfplumber: 逐页提取文字+表格     │
│            ├── PyMuPDF:    提取图片+元数据       │
│            ├── Docling:    结构化深度解析（可选） │
│            └── 输出: text + structured_content  │
│  .docx → python-docx                            │
│  .doc  → win32com 子进程（解决 COM/STA 冲突）   │
│  .html → BeautifulSoup                          │
│  URL   → EnhancedWebParser (requests + BS4)    │
└─────────────────────────────────────────────────┘
      │ text + structured_data
      ▼
┌─────────────────────────────────────────────────┐
│            TextAnalyzer.analyze()               │
│                                                 │
│  ── 阶段 1：图片 + 表格独立分析 ──              │
│  提取 image_items 和 table_items                │
│  → LLMService.analyze_images(table_infos=...)  │
│  → 生成多媒体描述作为阶段 2 额外上下文          │
│                                                 │
│  ── 阶段 2：全文深度分析 ──                     │
│  构建 prompt + extra_context（含图表分析结果）   │
│  → LLMService.analyze_text()                   │
│    ├── 短文档: 单次 LLM 调用                    │
│    └── 长文档: Map-Reduce 分块多轮调用          │
│  → 解析 JSON 结果                               │
│  → _process_llm_result() 匹配原文               │
│  → 失败则降级到 jieba 传统分词                  │
└─────────────────────────────────────────────────┘
      │ keypoints + summary + key_data
      │ + top_terms + statistics + highlights
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

系统提示词围绕 **"穿透式分析"** 核心理念设计：

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
  "key_data": [
    {
      "label": "指标名称",
      "value": "94.5%",
      "numeric": 94.5,
      "unit": "%",
      "type": "percentage",
      "is_comparison": true,
      "context": "数据上下文说明",
      "page": 5
    }
  ],
  "top_terms": [
    {
      "term": "专业术语",
      "weight": 95,
      "category": "核心技术"
    }
  ],
  "summary": "一句话概括",
  "title": "文章主旨标题"
}
```

**字段设计意图：**
- `point_page` / `page`：向 pdfplumber 提供页码提示，将搜索范围从全文压缩到 3 页以内
- `point_context`：当同一短语在同页出现多次时，通过上下文句子精确区分
- `annotation_label`：4-6 字中文标签，直接渲染到 PDF 左侧竖线旁的边注中
- `importance`（0-100）：95+ 为核心创新观点；80-94 为强力支撑论证；60 以下不列入
- `key_data`：严格筛选的核心量化数据，含 `is_comparison` 标记对比数据
- `top_terms`：LLM 提取的专业术语词云，按 `weight` 权重排序，排除人名/机构/虚词

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
# 至少配置一个 provider 即可使用
DEEPSEEK_API_KEY=your_deepseek_api_key_here
QWEN_API_KEY=your_qwen_api_key_here
PIPELLM_API_KEY=your_pipellm_api_key_here
```

- DeepSeek Key：https://platform.deepseek.com/
- Qwen Key：https://bailian.console.aliyun.com/
- PipeLLM Key：向服务商获取

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
│   ├── app.py                  # Flask 主应用，RESTful 路由 + /api/providers
│   ├── llm_service.py          # 多提供商 LLM 服务（DeepSeek / Qwen / PipeLLM）
│   ├── text_analyzer.py        # 文本分析器：两阶段分析、Map-Reduce、PDF 标注
│   ├── pdf_parser_enhanced.py  # 增强 PDF 解析器（文字+表格+图片）
│   ├── pdf_parser_docling.py   # Docling PDF 解析器（结构化提取+降级）
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
│       │   ├── Navbar.vue          # 顶栏（三引擎切换 + PipeLLM 模型选择）
│       │   ├── DocumentViewer.vue  # 左侧文档/PDF 查看器
│       │   ├── Sidebar.vue         # 右侧面板容器
│       │   ├── MainContent.vue     # 主内容区布局
│       │   ├── KeypointsTab.vue    # 关键点卡片（论点+论据展开）
│       │   ├── SummaryTab.vue      # 摘要 + 关键数据卡片
│       │   ├── StatisticsTab.vue   # 统计信息 + 数据对比图 + 词云
│       │   ├── AiChatTab.vue       # AI 对话窗口（联动文档上下文）
│       │   ├── UploadModal.vue     # 上传弹窗（文件 + URL）
│       │   ├── HistoryModal.vue    # 历史记录
│       │   ├── LoadingOverlay.vue  # 加载覆盖层
│       │   └── ToastContainer.vue  # 全局通知容器
│       ├── stores/
│       │   └── document.js         # Pinia Store（文档状态、API/模型选择、聊天）
│       └── composables/
│           └── useToast.js         # Toast 通知工具
├── install.bat                 # 首次安装脚本
└── start.bat                   # 日常启动脚本
```

---

## 注意事项

- 文件大小上限：16 MB（>50 MB 的 PDF 自动降级到 PyMuPDF 解析）
- `.doc` 格式解析需要本机安装 Microsoft Word（通过 win32com 调用）
- DeepSeek-R1 响应时间约 30-120 秒（推理模型较慢但质量高）
- `deepseek-reasoner` 不支持 `response_format: json_object`，系统已通过提示词约束输出格式
- PipeLLM 不支持文件直传，仅 Qwen 支持 `file_upload` 模式
- 建议使用 Chrome / Edge 浏览器

---

## License

MIT
