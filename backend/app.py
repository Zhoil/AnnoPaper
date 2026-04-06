import sys
import os

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 编码无法输出 emoji 导致请求失败
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Docling / HuggingFace 模型缓存路径配置 ─────────────────
# 将模型下载到项目本地目录，避免占用 C 盘空间
# 必须在 import docling 之前设置
backend_dir = os.path.dirname(os.path.abspath(__file__))
hf_cache_dir = os.path.join(backend_dir, '.hf_cache')
os.makedirs(hf_cache_dir, exist_ok=True)
os.environ['HF_HOME'] = hf_cache_dir
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'  # 国内镜像加速
print(f"📦 HuggingFace 模型缓存路径: {hf_cache_dir}")

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from werkzeug.utils import secure_filename
import json
from document_parser import DocumentParser
from text_analyzer import TextAnalyzer
from database import Database

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
            analysis_result=analysis_result
        )
        
        # 返回结果
        return jsonify({
            'success': True,
            'record_id': record_id,
            'filename': filename,
            'title': analysis_result.get('title', filename),
            'content': text_content,
            'keypoints': analysis_result['keypoints'],
            'summary': analysis_result['summary'],
            'statistics': analysis_result['statistics'],
            'highlights': analysis_result['highlights'],
            'annotated_url': annotated_url
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
            analysis_result=analysis_result
        )
        
        return jsonify({
            'success': True,
            'record_id': record_id,
            'filename': url,
            'title': analysis_result.get('title', '网页文章'),
            'content': text_content,
            'keypoints': analysis_result['keypoints'],
            'summary': analysis_result['summary'],
            'statistics': analysis_result['statistics'],
            'highlights': analysis_result['highlights'],
            'annotated_url': annotated_url,
            'is_web': True  # 标记为网页类型
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
    """AI 对话接口（固定使用 DeepSeek-R1）"""
    try:
        data = request.json
        message = data.get('message', '').strip()
        document_context = data.get('document_context', '')
        chat_history = data.get('chat_history', [])

        if not message:
            return jsonify({'error': '消息不能为空'}), 400

        response = analyzer.llm_service.chat(message, document_context, chat_history)

        if response:
            return jsonify({'success': True, 'response': response})
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
