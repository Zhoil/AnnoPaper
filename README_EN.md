# AnnoPaper Intelligent Reading

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/语言-中文-red?logo=googletranslate&logoColor=white" alt="中文" /></a>
  <a href="backend/requirements.txt"><img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python" /></a>
  <a href="backend/app.py"><img src="https://img.shields.io/badge/Flask-Backend-000000?logo=flask&logoColor=white" alt="Flask" /></a>
  <a href="frontend/package.json"><img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" /></a>
  <a href="frontend/package.json"><img src="https://img.shields.io/badge/Node.js-16%2B-339933?logo=nodedotjs&logoColor=white" alt="Node.js" /></a>
  <a href="https://platform.deepseek.com/"><img src="https://img.shields.io/badge/DeepSeek--R1-LLM-6C47FF?logo=openai&logoColor=white" alt="DeepSeek-R1" /></a>
  <img src="https://img.shields.io/badge/Version-v3.0.0-orange.svg" alt="Version" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
</p>

> An AI-powered document deep analysis and physical annotation system built with Vue 3 + Flask + DeepSeek-R1 / Qwen3.6-Plus / PipeLLM multi-engine architecture

---

## Tech Stack

### Frontend
| Technology | Purpose |
|-----------|---------|
| Vue 3 (Composition API) | Reactive UI framework |
| Pinia | Global state management (documents, API selection, chat history) |
| Vite | Build tool with hot module replacement |
| Axios | HTTP requests |
| Marked | AI chat Markdown rendering |

### Backend
| Technology | Purpose |
|-----------|---------|
| Flask | RESTful API server |
| SQLite | Persistent storage for analysis records |
| python-dotenv | Environment variable management (API key isolation) |
| jieba | Chinese word segmentation (keyword statistics fallback) |
| Docling | Advanced document structure extraction (optional OCR) |

### PDF Processing (Three-Library Pipeline)
| Technology | Role |
|-----------|------|
| **PyMuPDF (fitz)** | Image extraction, metadata reading, PDF page overlay/merge, Docling fallback |
| **pdfplumber** | Character-level precise coordinate extraction, table recognition |
| **reportlab** | Transparent highlight overlay creation (vector graphics rendering) |

### LLM APIs (Three Switchable Engines)
| Model | Purpose | Endpoint |
|-------|---------|----------|
| DeepSeek-R1 (`deepseek-reasoner`) | Document deep analysis (default), AI chat | DeepSeek API |
| Qwen3.6-Plus (`qwen3.6-plus`) | Fast analysis (optional), file upload | Alibaba Cloud DashScope |
| PipeLLM (multi-model) | Third-party multi-engine selection (GPT-5.4 / Claude, etc.) | OpenAI-compatible API |

---

## Core Features

- **Multi-Model AI Analysis**: One-click engine switching between DeepSeek / Qwen / PipeLLM; PipeLLM supports model dropdown selection
- **PDF Physical Annotation**: Character-level coordinate positioning via pdfplumber, precise highlighting on original PDFs, generating downloadable annotated documents
- **Multi-Format Support**: PDF, DOCX, DOC, HTML files and web URLs with unified cross-format analysis
- **Two-Phase Analysis**: Phase 1 independently analyzes images and tables → Phase 2 full-text deep analysis (with chart context)
- **Map-Reduce for Long Documents**: Auto-chunking for long documents → multi-round LLM calls → result merging, bypassing token limits
- **Key Data Extraction**: Automatically identifies core experimental data and comparison metrics, displayed as cards
- **Professional Word Cloud**: LLM-extracted core domain terminology, rendered by importance weight
- **AI Chat**: Context-aware Q&A window linked to the current document
- **Docling Enhanced Parsing**: Advanced document structure extraction with optional OCR, memory protection + automatic PyMuPDF fallback
- **Non-Body Filtering**: Automatically filters references, appendices, author info, institutional metadata, and other non-body content

---

## Document Processing Pipeline

```
User uploads file
      │
      ▼
┌─────────────────────────────────────────────────┐
│                DocumentParser                   │
│  .pdf  → EnhancedPDFParser / DoclingParser      │
│            ├── pdfplumber: extract text+tables  │
│            ├── PyMuPDF:    extract images+meta  │
│            ├── Docling:    deep structure (opt) │
│            └── output: text + structured_content│
│  .docx → python-docx                            │
│  .doc  → win32com subprocess (solves COM/STA)  │
│  .html → BeautifulSoup                          │
│  URL   → EnhancedWebParser (requests + BS4)    │
└─────────────────────────────────────────────────┘
      │ text + structured_data
      ▼
┌─────────────────────────────────────────────────┐
│            TextAnalyzer.analyze()               │
│                                                 │
│  ── Phase 1: Image + Table Analysis ──          │
│  Extract image_items and table_items            │
│  → LLMService.analyze_images(table_infos=...)  │
│  → Generate media descriptions for Phase 2     │
│                                                 │
│  ── Phase 2: Full-Text Deep Analysis ──         │
│  Build prompt + extra_context (with chart info) │
│  → LLMService.analyze_text()                   │
│    ├── Short docs: single LLM call             │
│    └── Long docs: Map-Reduce chunked calls     │
│  → Parse JSON result                            │
│  → _process_llm_result() match to source text  │
│  → Fallback to jieba segmentation on failure   │
└─────────────────────────────────────────────────┘
      │ keypoints + summary + key_data
      │ + top_terms + statistics + highlights
      ▼
┌─────────────────────────────────────────────────┐
│               Physical Annotation (optional)    │
│  PDF  → annotate_pdf()  three-layer architecture│
│  DOCX → annotate_docx() python-docx XML markup │
│  HTML → annotate_html() inline style injection  │
└─────────────────────────────────────────────────┘
      │ annotated_url
      ▼
   Store in SQLite → Return to frontend
```

---

## Prompt Engineering Design

The system prompt is built around the core concept of **"penetrating analysis"**:

### Core Principles

**1. Counter-Intuitive Extraction**
Skip obvious common knowledge or background. Focus on the document's "unique claims", "unexpected conclusions", and "critical turning points" — these represent the true information gain.

**2. Zero-Tolerance Quoting (Most Critical Constraint)**
`point` and `evidence.text` must be **verbatim character-for-character copies** from the original text, including punctuation, spaces, and numbers. This is the foundation of PDF physical annotation — only an exact character match allows pdfplumber to locate it precisely.

**3. Adaptive Quantity Control**
Automatically adjust the number of arguments (1–5) based on document length, avoiding over-extraction for short texts and missed key points for long ones.

### Response Protocol Design

```json
{
  "core_arguments": [
    {
      "point": "Verbatim copy of the core claim from source",
      "point_page": 3,
      "point_context": "Complete sentence containing point (15-30 chars)",
      "annotation_label": "Core Conclusion",
      "evidence": [
        {
          "text": "Verbatim copy of supporting evidence",
          "page": 5,
          "context": "Complete sentence containing evidence"
        }
      ],
      "importance": 95,
      "rationale": "Reason for the score"
    }
  ],
  "key_data": [
    {
      "label": "Metric name",
      "value": "94.5%",
      "numeric": 94.5,
      "unit": "%",
      "type": "percentage",
      "is_comparison": true,
      "context": "Data context description",
      "page": 5
    }
  ],
  "top_terms": [
    {
      "term": "Domain terminology",
      "weight": 95,
      "category": "Core Technology"
    }
  ],
  "summary": "One-sentence summary",
  "title": "Article title reflecting core thesis"
}
```

**Field Design Intent:**
- `point_page` / `page`: Page hint for pdfplumber, compressing search scope to 3 pages
- `point_context`: Disambiguates when the same phrase appears multiple times on a page
- `annotation_label`: 4–6 character label rendered in the PDF annotation sidebar
- `importance` (0–100): 95+ = core innovation; 80–94 = strong support; below 60 = filtered out
- `key_data`: Strictly filtered core quantitative data with `is_comparison` flag for comparison data
- `top_terms`: LLM-extracted domain terminology for word cloud, weighted by importance, excluding names/institutions/stopwords

### Importance Scoring Criteria

| Range | Meaning |
|-------|---------|
| 95-100 | Core innovative viewpoint, groundbreaking conclusion, exclusive data |
| 80-94  | Strong supporting argument, critical turning point |
| 60-79  | Auxiliary logical reasoning, background context |
| < 60   | Filtered out, not included in results |

---

## PDF Annotation: Three-Layer Architecture

PDF physical annotation is the most complex part of the system, using three libraries in a coordinated pipeline:

```
pdfplumber → reportlab → PyMuPDF
  Locate text  Draw overlay  Merge pages
```

### Layer 1: pdfplumber Character-Level Location

Standard text search (e.g., `page.search()`) frequently fails on Chinese PDFs due to font encoding, ligatures, and line-break splits. The system uses a character-level location algorithm:

```python
# Extract all non-whitespace characters from the page
chars = page.chars
char_str = ''.join(c['text'] for c in non_blank)

# Strip whitespace and match target text
target_clean = re.sub(r'\s+', '', target_text)
idx = char_str.lower().find(target_clean[:50])

# Group by top coordinate (diff < 4pt = same line)
# Generate independent bbox for each line of multi-line text
```

Even if target text spans multiple typeset lines, each line gets an accurate bounding box.

The LLM-returned `page_hint` further narrows the search to target page ± 1, eliminating full-document scans.

### Layer 2: reportlab Transparent Overlay

reportlab draws a **fully transparent overlay PDF** in memory matching the original PDF dimensions. For each annotation, it renders:
- Semi-transparent colored rectangle (alpha=0.22)
- Solid colored border (alpha=0.60)
- Left classification bar line, 2.8pt width (alpha=0.92)

**Coordinate system conversion** (critical detail):
```python
# pdfplumber: top-left origin, top = distance from page top (y increases downward)
# reportlab:  bottom-left origin, y increases upward
reportlab_y = page_height - pdfplumber_bottom
```

### Layer 3: PyMuPDF Page Merge

The reportlab overlay is composited onto each page of the original PDF via `show_pdf_page()`:

```python
original[pg_num].show_pdf_page(
    original[pg_num].rect, overlay, pg_num
)
original.save(output_path, garbage=4, deflate=True)
```

The annotated PDF **does not alter the original text** — the overlay is an independent vector layer, and text remains selectable and copyable.

### Visual Specification

| Type | Color | Rectangle Alpha | Bar Alpha | Meaning |
|------|-------|----------------|-----------|---------|
| Core Argument | `#ff6b6b` Red | 22% | 92% | Document's core claim |
| Supporting Evidence | `#51cf66` Green | 22% | 92% | Data / logical support |

---

## Quick Start

### First-time Setup (One-Click Install)

```bash
install.bat
```

The script automatically: checks Python/Node.js → installs Python dependencies → generates `.env` from `.env.example` → installs frontend dependencies.

### Configure API Keys

Edit `backend/.env` (auto-generated on first run):

```env
# Configure at least one provider to get started
DEEPSEEK_API_KEY=your_deepseek_api_key_here
QWEN_API_KEY=your_qwen_api_key_here
PIPELLM_API_KEY=your_pipellm_api_key_here
```

- DeepSeek Key: https://platform.deepseek.com/
- Qwen Key: https://bailian.console.aliyun.com/
- PipeLLM Key: Obtain from the service provider

### Start the System

```bash
start.bat
```

Open http://localhost:3000

---

## Project Structure

```
GraDesign_one/
├── backend/
│   ├── app.py                  # Flask main app, RESTful routes + /api/providers
│   ├── llm_service.py          # Multi-provider LLM service (DeepSeek / Qwen / PipeLLM)
│   ├── text_analyzer.py        # Text analyzer: two-phase analysis, Map-Reduce, PDF annotation
│   ├── pdf_parser_enhanced.py  # Enhanced PDF parser (text + tables + images)
│   ├── pdf_parser_docling.py   # Docling PDF parser (structure extraction + fallback)
│   ├── document_parser.py      # Document dispatcher: PDF/DOCX/DOC/HTML/URL routing
│   ├── web_parser_enhanced.py  # Enhanced web page parser
│   ├── database.py             # SQLite database operations
│   ├── exporter.py             # Export functionality (PDF/DOCX)
│   ├── requirements.txt        # Python dependencies
│   ├── .env                    # API keys (not committed to Git)
│   └── .env.example            # Key configuration template (committed to Git)
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── Navbar.vue          # Top bar (three-engine toggle + PipeLLM model selector)
│       │   ├── DocumentViewer.vue  # Left panel: document/PDF viewer
│       │   ├── Sidebar.vue         # Right panel container
│       │   ├── MainContent.vue     # Main content area layout
│       │   ├── KeypointsTab.vue    # Keypoint cards (arguments + evidence expand)
│       │   ├── SummaryTab.vue      # Summary + key data cards
│       │   ├── StatisticsTab.vue   # Statistics + data comparison chart + word cloud
│       │   ├── AiChatTab.vue       # AI chat window (linked to document context)
│       │   ├── UploadModal.vue     # Upload modal (file + URL)
│       │   ├── HistoryModal.vue    # History records
│       │   ├── LoadingOverlay.vue  # Loading overlay
│       │   └── ToastContainer.vue  # Global notification container
│       ├── stores/
│       │   └── document.js         # Pinia Store (document state, API/model selection, chat)
│       └── composables/
│           └── useToast.js         # Toast notification utility
├── install.bat                 # First-time installation script
└── start.bat                   # Daily startup script
```

---

## Notes

- File size limit: 16 MB (PDFs > 50 MB automatically fall back to PyMuPDF parsing)
- `.doc` format parsing requires Microsoft Word installed locally (via win32com)
- DeepSeek-R1 response time: ~30–120 seconds (reasoning model is slower but higher quality)
- `deepseek-reasoner` does not support `response_format: json_object`; output format is enforced via prompt engineering
- PipeLLM does not support file upload; only Qwen supports `file_upload` mode
- Recommended browsers: Chrome / Edge

---

## License

MIT
