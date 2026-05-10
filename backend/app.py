import sys
import os

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 编码无法输出 emoji 导致请求失败
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── 模型缓存路径统一配置（Docling + MinerU，全部落盘 D:\ 项目本地）──
# 必须在 import docling / mineru 之前设置
backend_dir = os.path.dirname(os.path.abspath(__file__))

# Docling 系模型（通过 HuggingFace）
hf_cache_dir = os.path.join(backend_dir, '.hf_cache')
os.makedirs(hf_cache_dir, exist_ok=True)
os.environ['HF_HOME'] = hf_cache_dir
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'  # 国内镜像加速

# MinerU 模型（默认走 ModelScope，国内更稳；也可改 'huggingface'、'local'）
mineru_cache_dir = os.path.join(backend_dir, '.mineru_cache')
os.makedirs(mineru_cache_dir, exist_ok=True)
os.environ.setdefault('MINERU_MODEL_SOURCE', 'modelscope')
os.environ['MODELSCOPE_CACHE'] = mineru_cache_dir
# 若切换到 huggingface 源，MinerU 会复用同一个 HF_HOME，无需额外配置
print(f"📦 模型缓存路径 → HF: {hf_cache_dir}")
print(f"📦 模型缓存路径 → MinerU({os.environ['MINERU_MODEL_SOURCE']}): {mineru_cache_dir}")

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import json
import hashlib
from document_parser import DocumentParser
from text_analyzer import TextAnalyzer
from database import Database
from logic_builder import build_logic_tree
from scholar_api import recommend_for_record
from llm_recommender import recommend_with_llm
import rag_indexer

# ── 文献推荐缓存常量 ──
RECOMMEND_TTL_SECONDS = 2 * 24 * 3600   # 2 天缓存
RECOMMEND_CLICK_COOLDOWN = 10           # 10s 点击疲劳


def _parse_db_ts(ts):
    """将 SQLite 的 CURRENT_TIMESTAMP 字符串解析为 datetime，失败返回 None。"""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(str(ts), fmt)
        except Exception:
            continue
    return None


def _compute_file_hash(filepath):
    """对上传文件二进制内容计算 SHA256。"""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _compute_text_hash(text):
    """对网页文本计算 SHA256。"""
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _record_to_upload_response(record, extra=None):
    """将历史 record 构造成 /api/upload 相同格式的响应。"""
    payload = {
        'success': True,
        'from_cache': True,
        'record_id': record['id'],
        'filename': record.get('filename'),
        'title': record.get('title'),
        'content': record.get('content'),
        'keypoints': record.get('keypoints', []),
        'summary': record.get('summary', {}),
        'statistics': record.get('statistics', {}),
        'highlights': record.get('highlights', []),
        'annotated_url': record.get('annotated_url')
    }
    if extra:
        payload.update(extra)
    return payload

app = Flask(__name__)
CORS(app)

# 配置
UPLOAD_FOLDER = 'uploads'
ANNOTATED_FOLDER = 'annotated'
PARSED_FOLDER = 'parsed_output'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'html', 'htm', 'md', 'markdown'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ANNOTATED_FOLDER'] = ANNOTATED_FOLDER
app.config['PARSED_FOLDER'] = PARSED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# 确保目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ANNOTATED_FOLDER, exist_ok=True)
os.makedirs(PARSED_FOLDER, exist_ok=True)

def _build_rag_index_safe(record_id, structured_content, text_content):
    """将解析产物构建为 RAG 索引并落库。失败不阻断主流程。"""
    try:
        chunks = rag_indexer.build_chunks(structured_content or [], text_content or '')
        if not chunks:
            print(f'[RAG] 无可用 chunks，跳过索引构建 id={record_id}')
            return
        built = rag_indexer.build_index(chunks)
        if not built:
            print(f'[RAG] BM25 索引构建返回空 id={record_id}')
            return
        chunks_json, bm25_blob, cnt = built
        db.save_rag_index(record_id, chunks_json, bm25_blob, cnt)
        rag_indexer.invalidate_cache(record_id)
        print(f'[RAG] 索引已入库 id={record_id} chunks={cnt}')
    except Exception as e:
        print(f'⚠️ RAG 索引构建失败（不影响主流程）: {e}')


@app.route('/files/<path:filename>')
def serve_file(filename):
    """提供已标注文件的访问"""
    return send_from_directory(app.config['ANNOTATED_FOLDER'], filename)

# 初始化组件
parser = DocumentParser()
analyzer = TextAnalyzer()
db = Database()

def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _save_parsed_output(unique_filename, text_content, structured_content, metadata):
    """
    将解析后的文本结构及内容保存到 parsed_output/ 目录，方便查看调试。
    生成两个文件：
      - {name}_text.txt      纯文本内容（LLM 分析用的完整文本）
      - {name}_structure.json 结构化数据（文本块、表格、图片、元数据）
    """
    try:
        base_name = os.path.splitext(unique_filename)[0]
        parsed_dir = app.config['PARSED_FOLDER']

        # 1. 保存纯文本
        text_path = os.path.join(parsed_dir, f"{base_name}_text.txt")
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text_content)

        # 2. 保存结构化数据（JSON）
        structure_path = os.path.join(parsed_dir, f"{base_name}_structure.json")
        structure_data = {
            'metadata': metadata,
            'total_items': len(structured_content),
            'text_blocks': [],
            'tables': [],
            'images': []
        }

        for item in structured_content:
            item_type = item.get('type', 'unknown')
            entry = {
                'page': item.get('page'),
                'content': item.get('content', ''),
            }
            if item.get('bbox'):
                entry['bbox'] = item['bbox']
            if item.get('metadata'):
                entry['metadata'] = item['metadata']
            if item.get('surrounding_text'):
                entry['surrounding_text'] = item['surrounding_text']
            if item.get('table_data'):
                entry['table_data'] = item['table_data']

            if item_type == 'text':
                structure_data['text_blocks'].append(entry)
            elif item_type == 'table':
                structure_data['tables'].append(entry)
            elif item_type == 'image':
                structure_data['images'].append(entry)

        with open(structure_path, 'w', encoding='utf-8') as f:
            json.dump(structure_data, f, ensure_ascii=False, indent=2)

        print(f"📁 解析结果已保存: {text_path}, {structure_path}")
    except Exception as e:
        print(f"⚠️ 保存解析结果失败: {str(e)}")

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """处理文件上传和分析"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有文件上传'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': '不支持的文件格式'}), 400
        
        # 保存文件
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        # ── 文档哈希去重：相同内容已解析过则直接返回数据库结果 ──
        try:
            file_hash = _compute_file_hash(filepath)
        except Exception as e:
            print(f'⚠️ 计算文件哈希失败: {e}')
            file_hash = None

        if file_hash:
            existing = db.find_by_hash(file_hash)
            if existing:
                print(f'✅ 命中文档缓存 id={existing["id"]} hash={file_hash[:10]}…')
                # 删除刚保存的重复文件，避免磁盘膨胀
                try:
                    os.remove(filepath)
                except Exception:
                    pass
                return jsonify(_record_to_upload_response(existing))

        # 解析文档
        parse_result = parser.parse(filepath)
        
        if not parse_result:
            return jsonify({'error': '文档解析失败'}), 500
        
        text_content = parse_result['text']
        structured_content = parse_result.get('structured_content', [])
        metadata = parse_result.get('metadata', {})

        if not text_content:
            ext = os.path.splitext(filename)[1].lower()
            if ext == '.doc':
                return jsonify({'error': '无法解析 .doc 文件。请确认 Microsoft Word 已安装，或将文件另存为 .docx 格式后重新上传。'}), 500
            return jsonify({'error': '文档内容为空'}), 500

        # ── 保存解析结果到 parsed_output/ 以便查看 ──
        _save_parsed_output(unique_filename, text_content, structured_content, metadata)

        api_provider = request.form.get('api_provider', 'deepseek')
        api_model = request.form.get('api_model', '')
        analysis_result = analyzer.analyze(text_content, structured_data={
            'filepath': filepath,
            'structured_content': structured_content,
            'metadata': metadata
        }, api_provider=api_provider, api_model=api_model)
        
        # 如果是 PDF，生成带标注的副本
        annotated_url = None
        if filename.lower().endswith('.pdf'):
            annotated_filename = f"annotated_{unique_filename}"
            annotated_path = os.path.join(app.config['ANNOTATED_FOLDER'], annotated_filename)
            
            # 执行标注并获取页码映射
            meta_map = analyzer.annotate_pdf(filepath, analysis_result['highlights'], annotated_path)
            
            # 将页码信息存入 keypoints
            for kp in analysis_result['keypoints']:
                match = next((m for m in meta_map if m['id'] == kp['id']), None)
                if match:
                    kp['page'] = match['page']
            
            annotated_url = f"http://localhost:5000/files/{annotated_filename}"
        
        # 如果是 Docx，生成带标注的副本
        elif filename.lower().endswith('.docx'):
            annotated_filename = f"annotated_{unique_filename}"
            annotated_path = os.path.join(app.config['ANNOTATED_FOLDER'], annotated_filename)
            
            # 执行 Docx XML 标注
            success = analyzer.annotate_docx(filepath, analysis_result['highlights'], annotated_path)
            if success:
                annotated_url = f"http://localhost:5000/files/{annotated_filename}"
        
        # 保存到数据库 (包含标注后的 URL)
        analysis_result['annotated_url'] = annotated_url
        record_id = db.save_analysis(
            filename=filename,
            original_text=text_content,
            analysis_result=analysis_result,
            file_hash=file_hash
        )

        # ── 预构建 RAG 段落索引（失败不阻断主流程） ──
        _build_rag_index_safe(record_id, structured_content, text_content)
        
        # 返回结果
        return jsonify({
            'success': True,
            'from_cache': False,
            'record_id': record_id,
            'filename': filename,
            'title': analysis_result.get('title', filename),
            'content': text_content,
            'keypoints': analysis_result['keypoints'],
            'summary': analysis_result['summary'],
            'statistics': analysis_result['statistics'],
            'highlights': analysis_result['highlights'],
            'annotated_url': annotated_url,
            'genre': analysis_result.get('genre')  # 文体检测结果
        })
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': f'处理失败: {str(e)}'}), 500

@app.route('/api/upload-url', methods=['POST'])
def upload_url():
    """处理网页URL上传和分析（支持HTML标注）"""
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': '没有提供URL'}), 400
        
        # 解析网页
        parse_result = parser.parse_url(url)
        
        if not parse_result:
            return jsonify({'error': '网页解析失败'}), 500
        
        text_content = parse_result['text']
        original_html = parse_result.get('html')
        structured_content = parse_result.get('structured_content', [])
        metadata = parse_result.get('metadata', {})

        if not text_content:
            return jsonify({'error': '网页内容为空'}), 500

        # ── 网页文本哈希去重 ──
        url_hash = _compute_text_hash(url + '\n' + text_content[:2000])
        existing = db.find_by_hash(url_hash)
        if existing:
            print(f'✅ 命中网页缓存 id={existing["id"]} hash={url_hash[:10]}…')
            return jsonify(_record_to_upload_response(existing, {'is_web': True}))

        # 分析文本（传入结构化信息和 API 提供商）
        api_provider = data.get('api_provider', 'deepseek')
        api_model = data.get('api_model', '')
        analysis_result = analyzer.analyze(text_content, structured_data={
            'structured_content': structured_content,
            'metadata': metadata
        }, api_provider=api_provider, api_model=api_model)
        
        # 如果有HTML，生成标注版网页
        annotated_html = None
        annotated_url = None
        if original_html:
            try:
                # 使用增强版解析器标注HTML
                annotated_html = parser.enhanced_web_parser.annotate_html(analysis_result['highlights'])
                
                # 保存标注后的HTML文件
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                annotated_filename = f"annotated_web_{timestamp}.html"
                annotated_path = os.path.join(app.config['ANNOTATED_FOLDER'], annotated_filename)
                
                with open(annotated_path, 'w', encoding='utf-8') as f:
                    f.write(annotated_html)
                
                annotated_url = f"http://localhost:5000/files/{annotated_filename}"
                print(f"✅ 网页HTML标注完成: {annotated_url}")
            except Exception as e:
                print(f"⚠️ 网页HTML标注失败: {str(e)}")
        
        # 保存到数据库
        analysis_result['annotated_url'] = annotated_url
        record_id = db.save_analysis(
            filename=url,
            original_text=text_content,
            analysis_result=analysis_result,
            file_hash=url_hash
        )

        # ── 预构建 RAG 段落索引（失败不阻断主流程） ──
        _build_rag_index_safe(record_id, structured_content, text_content)
        
        return jsonify({
            'success': True,
            'from_cache': False,
            'record_id': record_id,
            'filename': url,
            'title': analysis_result.get('title', '网页文章'),
            'content': text_content,
            'keypoints': analysis_result['keypoints'],
            'summary': analysis_result['summary'],
            'statistics': analysis_result['statistics'],
            'highlights': analysis_result['highlights'],
            'annotated_url': annotated_url,
            'is_web': True,  # 标记为网页类型
            'genre': analysis_result.get('genre')  # 文体检测结果
        })
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': f'处理失败: {str(e)}'}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史记录列表"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        history = db.get_history(page, per_page)
        
        return jsonify({
            'success': True,
            'history': history['records'],
            'total': history['total'],
            'page': page,
            'per_page': per_page
        })
    
    except Exception as e:
        return jsonify({'error': f'获取历史记录失败: {str(e)}'}), 500

@app.route('/api/history/<int:record_id>', methods=['GET'])
def get_history_detail(record_id):
    """获取历史记录详情"""
    try:
        record = db.get_record(record_id)
        
        if not record:
            return jsonify({'error': '记录不存在'}), 404
        
        return jsonify({
            'success': True,
            'record': record
        })
    
    except Exception as e:
        return jsonify({'error': f'获取记录详情失败: {str(e)}'}), 500

@app.route('/api/history/<int:record_id>', methods=['DELETE'])
def delete_history(record_id):
    """删除历史记录"""
    try:
        success = db.delete_record(record_id)
        
        if not success:
            return jsonify({'error': '删除失败'}), 500

        # 同步清理 RAG 索引与内存缓存
        try:
            db.delete_rag_index(record_id)
            rag_indexer.invalidate_cache(record_id)
        except Exception as e:
            print(f'⚠️ 清理 RAG 索引失败: {e}')
        
        return jsonify({
            'success': True,
            'message': '删除成功'
        })
    
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/export/<int:record_id>', methods=['GET'])
def export_record(record_id):
    """导出分析结果"""
    try:
        format_type = request.args.get('format', 'pdf')
        record = db.get_record(record_id)
        
        if not record:
            return jsonify({'error': '记录不存在'}), 404
        
        from exporter import Exporter
        exporter = Exporter()
        
        if format_type == 'pdf':
            file_path = exporter.export_to_pdf(record)
        elif format_type == 'docx':
            file_path = exporter.export_to_docx(record)
        else:
            return jsonify({'error': '不支持的导出格式'}), 400
        
        from flask import send_file
        return send_file(file_path, as_attachment=True)
    
    except Exception as e:
        return jsonify({'error': f'导出失败: {str(e)}'}), 500

@app.route('/api/compare', methods=['POST'])
def compare_documents():
    """比较多个文档（扩展功能）"""
    try:
        data = request.json
        record_ids = data.get('record_ids', [])
        
        if len(record_ids) < 2:
            return jsonify({'error': '至少需要两个文档进行比较'}), 400
        
        records = [db.get_record(rid) for rid in record_ids]
        
        # 比较分析
        comparison = analyzer.compare_documents(records)
        
        return jsonify({
            'success': True,
            'comparison': comparison
        })
    
    except Exception as e:
        return jsonify({'error': f'比较失败: {str(e)}'}), 500


@app.route('/api/chat', methods=['POST'])
def chat():
    """AI 对话接口：若带 analysis_id 则启用 BM25 检索增强。"""
    try:
        data = request.json
        message = data.get('message', '').strip()
        document_context = data.get('document_context', '')
        chat_history = data.get('chat_history', [])
        analysis_id = data.get('analysis_id')

        if not message:
            return jsonify({'error': '消息不能为空'}), 400

        # ── RAG 检索增强：按问题动态召回相关段落拼入 document_context ──
        rag_hits = []
        if analysis_id is not None:
            try:
                aid = int(analysis_id)
                loaded = rag_indexer.load_index(aid, db)
                if loaded:
                    chunks, bm25 = loaded
                    rag_hits = rag_indexer.retrieve(message, chunks, bm25, top_k=5)
            except (TypeError, ValueError):
                pass
            except Exception as e:
                print(f'⚠️ RAG 检索失败（降级到截断上下文）: {e}')

        if rag_hits:
            retrieved_block = rag_indexer.format_context(rag_hits)
            if document_context:
                document_context = f"{document_context}\n\n===== 从文档中检索到的相关段落 =====\n{retrieved_block}"
            else:
                document_context = f"===== 从文档中检索到的相关段落 =====\n{retrieved_block}"

        response = analyzer.llm_service.chat(message, document_context, chat_history)

        if response:
            return jsonify({
                'success': True,
                'response': response,
                'rag_used': bool(rag_hits),
                'rag_hits': [
                    {'idx': h.get('idx'), 'page': h.get('page'),
                     'source_type': h.get('source_type'), 'score': h.get('score')}
                    for h in rag_hits
                ]
            })
        else:
            return jsonify({'error': 'AI 响应失败，请稍后重试'}), 500

    except Exception as e:
        print(f"Chat 错误: {str(e)}")
        return jsonify({'error': f'对话失败: {str(e)}'}), 500

@app.route('/api/providers', methods=['GET'])
def get_providers():
    """返回所有可用 provider 及其模型列表（供前端动态渲染）"""
    try:
        providers = analyzer.llm_service.get_available_providers()
        return jsonify({'success': True, 'providers': providers})
    except Exception as e:
        return jsonify({'error': f'获取 provider 列表失败: {str(e)}'}), 500


@app.route('/api/logic/<int:record_id>', methods=['GET'])
def get_logic_tree(record_id):
    """获取文档的论证链路（论点→论据），返回 Mermaid 源码与结构化树。"""
    try:
        record = db.get_record(record_id)
        if not record:
            return jsonify({'error': '记录不存在'}), 404

        max_points = request.args.get('max_points', 6, type=int)
        max_evidence = request.args.get('max_evidence', 3, type=int)
        logic = build_logic_tree(record, max_points=max_points, max_evidence_per_point=max_evidence)
        return jsonify({'success': True, 'logic': logic})
    except Exception as e:
        print(f"⚠️ 论证链路生成失败: {e}")
        return jsonify({'error': f'论证链路生成失败: {str(e)}'}), 500


@app.route('/api/recommend/<int:record_id>', methods=['GET'])
def get_recommendations(record_id):
    """LLM 驱动的文献推荐，配合 2 天 DB 缓存 + 10s 点击疲劳 + flag 标记。

    查询参数：
      - max: 1~12（默认 6）
      - provider: LLM 提供商，默认 deepseek
      - force=1: 跳过 TTL 和 flag 判断强制重新生成（仍受 10s 点击疲劳保护）
    """
    try:
        record = db.get_record(record_id)
        if not record:
            return jsonify({'error': '记录不存在'}), 404

        max_results = request.args.get('max', 6, type=int)
        max_results = max(1, min(max_results, 12))
        provider = request.args.get('provider', 'deepseek')
        force = request.args.get('force', '0') == '1'

        state = db.get_recommend_state(record_id) or {}
        now = datetime.now()

        # ── 规则1：10s 点击疲劳 ──
        # 时间间隔很短且有缓存：直接返回缓存；无缓存：直接返回 429 提示「冷却中」
        last_click = _parse_db_ts(state.get('last_click_at'))
        if last_click:
            elapsed = (now - last_click).total_seconds()
            if 0 <= elapsed < RECOMMEND_CLICK_COOLDOWN:
                if state.get('flag') == 1 and state.get('cache'):
                    try:
                        cached = json.loads(state['cache'])
                    except Exception:
                        cached = {'query': '', 'results': [], 'sources': {}}
                    cached['success'] = True
                    cached['from_cache'] = True
                    cached['cache_reason'] = 'click_throttle'
                    cached['cooldown_remaining'] = int(RECOMMEND_CLICK_COOLDOWN - elapsed)
                    return jsonify(cached)
                # 没有缓存但处于冷却期：拒绝频繁调用
                return jsonify({
                    'success': True,
                    'query': '',
                    'results': [],
                    'sources': {},
                    'from_cache': False,
                    'cooldown_remaining': int(RECOMMEND_CLICK_COOLDOWN - elapsed),
                    'warning': f'点击过于频繁，请 {int(RECOMMEND_CLICK_COOLDOWN - elapsed)}s 后再试'
                }), 200

        # 更新点击时间戳（无论后续是否命中缓存）
        db.touch_recommend_click(record_id)

        # ── 规则2：flag=1 且未超过 2 天 → 直读缓存 ──
        if not force and state.get('flag') == 1 and state.get('cache'):
            updated_at = _parse_db_ts(state.get('updated_at'))
            if updated_at and (now - updated_at).total_seconds() < RECOMMEND_TTL_SECONDS:
                try:
                    cached = json.loads(state['cache'])
                    cached['success'] = True
                    cached['from_cache'] = True
                    cached['cache_reason'] = 'ttl_hit'
                    return jsonify(cached)
                except Exception as e:
                    print(f'⚠️ 缓存解析失败，将重新生成: {e}')

        # ── 规则3：flag=0 或 TTL 过期 → 调用 LLM 重新生成 ──
        try:
            result = recommend_with_llm(
                record,
                analyzer.llm_service,
                provider=provider,
                max_results=max_results
            )
        except Exception as e:
            print(f'⚠️ LLM 推荐失败，降级到传统 scholar_api: {e}')
            result = recommend_for_record(record, max_results=max_results)

        # 写入缓存（即使 results 为空也保存，避免下次频繁重试；用户可 force=1 刷新）
        try:
            db.save_recommend_cache(record_id, result)
        except Exception as e:
            print(f'⚠️ 写入推荐缓存失败: {e}')

        return jsonify({'success': True, 'from_cache': False, **result})
    except Exception as e:
        print(f"⚠️ 文献推荐失败: {e}")
        return jsonify({'success': True, 'query': '', 'results': [], 'sources': {},
                        'from_cache': False, 'warning': str(e)})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
