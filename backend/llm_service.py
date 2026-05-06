import os
import re
import json
import time
import requests
from typing import Dict, List, Optional
from dotenv import load_dotenv

from llm_stats import record_llm_call, extract_usage
from prompts import (
    build_analyze_system_prompt,
    build_file_user_prompt,
    build_pdf_text_user_prompt,
    build_generic_user_prompt,
    build_chunk_user_prompt,
    build_merge_user_prompt,
    build_chat_system_prompt,
    MEDIA_SYSTEM_PROMPT,
    MEDIA_INSTRUCTION_HEADER,
    build_media_footer,
)

# 加载 .env 文件（位于当前脚本同目录）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


class LLMService:
    """
    大模型服务 — 全配置从环境变量读取，后端零硬编码

    新增 provider 只需：
      ① 在 PROVIDERS 列表添加名称（如 'openai'）
      ② 在 backend/.env 添加 OPENAI_API_KEY / _API_URL / _MODEL / _TIMEOUT / _DISPLAY_NAME
    """

    # ── 已注册的 provider 名称列表（所有配置从 .env 读取）──
    PROVIDERS = ['deepseek', 'qwen', 'pipellm']

    def __init__(self):
        self.chat_provider = os.environ.get('CHAT_PROVIDER', 'deepseek')
        available = []
        for name in self.PROVIDERS:
            cfg = self._get_provider_config(name)
            if cfg['api_key']:
                available.append(cfg['display_name'])
            else:
                prefix = name.upper()
                print(f'[WARN] {prefix}_API_KEY 未配置，请在 backend/.env 中设置')

        status = '、'.join(available) if available else '无可用 provider'
        print(f'LLM 服务初始化，可用: {status}')

    def _get_provider_config(self, provider: str) -> dict:
        """获取指定 provider 的完整配置（全部从环境变量读取，零硬编码）"""
        prefix = provider.upper()
        # 解析可用模型列表（逗号分隔）
        models_str = os.environ.get(f'{prefix}_MODELS', '')
        models = [m.strip() for m in models_str.split(',') if m.strip()] if models_str else []
        return {
            'provider': provider,
            'api_key': os.environ.get(f'{prefix}_API_KEY', ''),
            'api_url': os.environ.get(f'{prefix}_API_URL', ''),
            'model': os.environ.get(f'{prefix}_MODEL', ''),
            'models': models,
            'file_model': os.environ.get(f'{prefix}_FILE_MODEL', ''),
            'timeout': int(os.environ.get(f'{prefix}_TIMEOUT', '60')),
            'display_name': os.environ.get(f'{prefix}_DISPLAY_NAME', provider),
            'supports_json_format': os.environ.get(f'{prefix}_SUPPORTS_JSON', '').lower() == 'true',
            'supports_file_upload': os.environ.get(f'{prefix}_SUPPORTS_FILE_UPLOAD', '').lower() == 'true',
            # DeepSeek V4 思考模式配置
            'thinking': os.environ.get(f'{prefix}_THINKING', ''),
            'reasoning_effort': os.environ.get(f'{prefix}_REASONING_EFFORT', ''),
        }

    def get_available_providers(self) -> List[Dict]:
        """返回所有可用 provider 及其模型列表（供前端查询）"""
        result = []
        for name in self.PROVIDERS:
            cfg = self._get_provider_config(name)
            if not cfg['api_key']:
                continue
            provider_info = {
                'id': name,
                'name': cfg['display_name'],
                'default_model': cfg['model'],
                'models': cfg['models'] if cfg['models'] else [cfg['model']],
            }
            result.append(provider_info)
        return result

    def is_enabled(self) -> bool:
        return True

    def get_config_info(self) -> Dict:
        return {
            'providers': list(self.PROVIDERS),
            'chat_provider': self.chat_provider
        }

    def _apply_thinking_params(self, data: dict, config: dict):
        """
        为支持思考模式的 provider 添加 thinking / reasoning_effort 参数
        仅当 .env 中配置了 THINKING 字段时才激活（对其他 provider 无影响）
        """
        thinking_mode = config.get('thinking', '')
        if not thinking_mode:
            return

        # 添加 thinking 参数
        data['thinking'] = {'type': thinking_mode}

        # 添加 reasoning_effort 参数
        effort = config.get('reasoning_effort', 'high')
        if effort:
            data['reasoning_effort'] = effort

        # 思考模式下 temperature 等参数不生效，但为兼容不会报错，保留即可
        print(f"  🧠 思考模式: {thinking_mode}, 强度: {effort}")

    def _extract_content(self, result: dict) -> Optional[str]:
        """
        从 API 响应中提取 content，兼容 DeepSeek V4 的 reasoning_content 字段
        思维链内容仅用于日志输出，不影响最终返回
        """
        try:
            message = result['choices'][0]['message']
            reasoning = message.get('reasoning_content', '')
            content = message.get('content', '')

            if reasoning:
                # 截取前100字方便调试查看
                preview = reasoning[:100].replace('\n', ' ')
                print(f"  💭 思维链预览: {preview}...")

            # 清理 V4 可能泄漏到 content 中的 <think> 标签
            if content and '<think>' in content:
                import re as _re
                cleaned = _re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                if cleaned:
                    print(f"  🧹 已清理 content 中的 <think> 标签 ({len(content)}→{len(cleaned)} 字符)")
                    content = cleaned

            return content
        except (KeyError, IndexError) as e:
            print(f"  ⚠️ 解析响应失败: {str(e)}")
            return None

    def _build_system_prompt(self, provider: str) -> str:
        """根据提供商构建系统提示词（委托给 prompts 模块）"""
        config = self._get_provider_config(provider)
        model_ref = config.get('display_name', 'DeepSeek-V4-Pro')
        return build_analyze_system_prompt(model_ref)

    def analyze_text(self, text: str, provider: str = 'deepseek',
                     file_path: Optional[str] = None, file_size: int = 0,
                     image_descriptions: str = '',
                     model_override: str = '') -> Optional[Dict]:
        """
        使用指定 API 提供商分析文档

        优先策略：文件直传 API（上传文件 + prompt） → 降级为文本提取模式

        Args:
            text: 已提取的文本内容（用于降级 + 标注搜索）
            provider: API 提供商 ('deepseek' | 'qwen' | 'pipellm')
            file_path: 原始文件路径（PDF/Word/Markdown 等）
            file_size: 文件大小（字节）
            image_descriptions: 图片独立分析结果（两阶段第一阶段输出）
            model_override: 前端指定的具体模型名（覆盖默认模型）
        """
        config = self._get_provider_config(provider)
        # 如果前端指定了具体模型，覆盖默认模型
        if model_override:
            config['model'] = model_override
            print(f"🎯 使用前端指定模型: {model_override}")
        system_prompt = self._build_system_prompt(provider)

        try:
            # ── 优先方案：文件直传 API ──────────────────────────
            # 仅当 provider 明确支持文件上传时才尝试
            if file_path and os.path.exists(file_path) and config.get('supports_file_upload'):
                file_id = self._upload_file(file_path, config)
                if file_id:
                    file_name = os.path.basename(file_path)
                    user_prompt = build_file_user_prompt(file_name, image_descriptions)

                    # 使用文件专用模型（如 qwen-long）或默认模型
                    file_model = config.get('file_model') or config['model']
                    print(f"📤 文件直传模式：{config['display_name']}（{file_model}）分析 {file_name}")

                    response = self._call_api_with_file(file_id, system_prompt, user_prompt, config, file_model)

                    # 清理已上传的文件
                    self._delete_uploaded_file(file_id, config)

                    if response:
                        result = self._parse_llm_response(response)
                        if result:
                            return result
                    print("⚠️ 文件直传分析失败，降级为文本提取模式")

            # ── 降级方案：文本提取模式 ────────────────────────
            file_name = os.path.basename(file_path) if file_path else ''
            text_len = len(text)

            # 判断是否需要多轮分块分析
            if text_len > self.LONG_TEXT_THRESHOLD:
                print(f"📄 长文档检测：{text_len} 字符 > {self.LONG_TEXT_THRESHOLD} 阈值，启动 Map-Reduce 多轮分析")
                result = self._analyze_long_text(
                    text, config, system_prompt,
                    file_name=file_name,
                    image_descriptions=image_descriptions
                )
                if result:
                    return result
                print("⚠️ Map-Reduce 分析失败，回退到单次截断分析")

            # 短文档 或 Map-Reduce 失败的回退：单次调用
            final_content = text
            if image_descriptions:
                final_content += f"\n\n{'='*50}\n【图片分析结果】\n以下是文档中图片经独立分析后得到的描述，请结合这些图片信息进行整体分析：\n{image_descriptions}\n{'='*50}"

            if file_path and file_path.lower().endswith('.pdf'):
                formatted_content = build_pdf_text_user_prompt(file_name, final_content)
                print(f"📄 文本提取模式：{config['display_name']}（{config['model']}）处理 {file_name} ({text_len} 字符)")
            else:
                formatted_content = build_generic_user_prompt(final_content)
                print(f"📝 文本提取模式：{config['display_name']}（{config['model']}）分析文本 ({text_len} 字符)")

            response = self._call_api(formatted_content, system_prompt, config)

            if response:
                return self._parse_llm_response(response)
            return None
        except Exception as e:
            print(f"分析错误 ({provider}): {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    def chat(self, message: str, document_context: str, chat_history: List[Dict]) -> Optional[str]:
        """
        AI 对话（使用 CHAT_PROVIDER 指定的 provider）
        Args:
            message: 用户消息
            document_context: 当前文档上下文
            chat_history: 对话历史 [{'role': 'user'|'assistant', 'content': str}]
        """
        config = self._get_provider_config(self.chat_provider)
        model_name = config['display_name']

        system_prompt = build_chat_system_prompt(model_name, document_context)

        messages = [{'role': 'system', 'content': system_prompt}]

        # 添加对话历史（最多 10 条）
        for msg in chat_history[-10:]:
            messages.append({'role': msg['role'], 'content': msg['content']})

        messages.append({'role': 'user', 'content': message})

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config["api_key"]}'
        }
        data = {
            'model': config['model'],
            'messages': messages,
            'temperature': 0.7
        }

        # DeepSeek V4 思考模式参数
        self._apply_thinking_params(data, config)

        _t0 = time.perf_counter()
        try:
            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config['timeout']
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            if response.status_code == 200:
                result = response.json()
                content = self._extract_content(result)
                _usage = extract_usage(result)
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=config.get('model', ''),
                    call_type='chat',
                    latency_ms=_latency,
                    prompt_tokens=_usage['prompt_tokens'],
                    completion_tokens=_usage['completion_tokens'],
                    total_tokens=_usage['total_tokens'],
                    status='success',
                    input_chars=len(message),
                    output_chars=len(content) if content else 0,
                )
                return content
            else:
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=config.get('model', ''),
                    call_type='chat',
                    latency_ms=_latency,
                    status='error',
                    input_chars=len(message),
                    error_message=f'HTTP {response.status_code}',
                )
                print(f"Chat API 错误: {response.status_code}, {response.text}")
                return None
        except requests.exceptions.Timeout:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=config.get('model', ''),
                call_type='chat',
                latency_ms=_latency,
                status='timeout',
                input_chars=len(message),
                error_message='timeout',
            )
            print("Chat 请求超时")
            return None
        except Exception as e:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=config.get('model', ''),
                call_type='chat',
                latency_ms=_latency,
                status='error',
                input_chars=len(message),
                error_message=str(e)[:200],
            )
            print(f"Chat 错误: {str(e)}")
            return None

    # ── 文件直传 API 方法 ─────────────────────────────────────

    def _get_base_url(self, config: dict) -> str:
        """从 chat/completions URL 推导出 API base URL"""
        api_url = config['api_url']
        # 移除 /chat/completions 得到 base URL
        for suffix in ['/chat/completions', '/chat']:
            if suffix in api_url:
                return api_url.split(suffix)[0]
        return api_url

    def _upload_file(self, filepath: str, config: dict) -> Optional[str]:
        """
        上传文件到 API 的 /files 端点（OpenAI 兼容格式）
        支持 DashScope、OpenAI 等提供文件上传接口的 API
        返回 file_id 或 None（表示该 provider 不支持文件上传）
        """
        base_url = self._get_base_url(config)
        files_url = f"{base_url}/files"

        try:
            file_name = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                response = requests.post(
                    files_url,
                    headers={'Authorization': f'Bearer {config["api_key"]}'},
                    files={'file': (file_name, f)},
                    data={'purpose': 'file-extract'},
                    timeout=120  # 上传可能较慢
                )

            if response.status_code == 200:
                result = response.json()
                file_id = result.get('id', '')
                if file_id:
                    print(f"  📤 文件上传成功: {file_id} ({file_name})")
                    return file_id
                print(f"  ⚠️ 文件上传返回无 id: {result}")
            else:
                # 404/405 = 该 provider 不支持文件上传，静默降级
                if response.status_code in (404, 405):
                    print(f"  ℹ️ {config['display_name']} 不支持文件上传接口，使用文本提取模式")
                else:
                    print(f"  ⚠️ 文件上传失败: {response.status_code} {response.text[:200]}")
        except requests.exceptions.ConnectionError:
            print(f"  ℹ️ 文件上传接口不可用，使用文本提取模式")
        except Exception as e:
            print(f"  ⚠️ 文件上传异常: {str(e)}")

        return None

    def _call_api_with_file(self, file_id: str, system_prompt: str,
                            user_prompt: str, config: dict, model: str) -> Optional[str]:
        """
        使用文件引用调用 API（fileid:// 格式，DashScope/OpenAI 兼容）
        文件内容由 API 端直接解析，无需本地文本提取
        """
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config["api_key"]}'
        }
        data = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'system', 'content': f'fileid://{file_id}'},
                {'role': 'user', 'content': user_prompt}
            ],
            'temperature': 1.0
        }

        # DeepSeek V4 思考模式参数
        self._apply_thinking_params(data, config)

        if config.get('supports_json_format'):
            data['response_format'] = {'type': 'json_object'}

        _t0 = time.perf_counter()
        try:
            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config.get('timeout', 120)
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            if response.status_code == 200:
                result = response.json()
                content = self._extract_content(result)
                _usage = extract_usage(result)
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=model,
                    call_type='file_upload',
                    latency_ms=_latency,
                    prompt_tokens=_usage['prompt_tokens'],
                    completion_tokens=_usage['completion_tokens'],
                    total_tokens=_usage['total_tokens'],
                    status='success',
                    input_chars=len(user_prompt),
                    output_chars=len(content) if content else 0,
                )
                return content
            else:
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=model,
                    call_type='file_upload',
                    latency_ms=_latency,
                    status='error',
                    input_chars=len(user_prompt),
                    error_message=f'HTTP {response.status_code}',
                )
                print(f"  文件分析 API 错误: {response.status_code}, {response.text[:300]}")
                return None
        except requests.exceptions.Timeout:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=model,
                call_type='file_upload',
                latency_ms=_latency,
                status='timeout',
                input_chars=len(user_prompt),
                error_message='timeout',
            )
            print(f"  文件分析请求超时 ({config.get('timeout', 120)}s)")
            return None
        except Exception as e:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=model,
                call_type='file_upload',
                latency_ms=_latency,
                status='error',
                input_chars=len(user_prompt),
                error_message=str(e)[:200],
            )
            print(f"  文件分析异常: {str(e)}")
            return None

    def _delete_uploaded_file(self, file_id: str, config: dict):
        """删除已上传的文件（清理 API 端存储）"""
        base_url = self._get_base_url(config)
        delete_url = f"{base_url}/files/{file_id}"

        try:
            response = requests.delete(
                delete_url,
                headers={'Authorization': f'Bearer {config["api_key"]}'},
                timeout=10
            )
            if response.status_code == 200:
                print(f"  🗑️ 已清理上传文件: {file_id}")
        except Exception:
            pass  # 清理失败不影响主流程

    # ── 长文档 Map-Reduce 多轮分析 ──────────────────────────

    # 单次 API 调用的字符上限（留 ~2000 给 prompt 和格式包装）
    CHUNK_CHAR_LIMIT = 10000
    # 超过此长度触发分块分析
    LONG_TEXT_THRESHOLD = 12000

    def _split_text_chunks(self, text: str) -> List[str]:
        """
        按页码标记（===== 第 N 页 =====）将长文本智能分块。
        每块不超过 CHUNK_CHAR_LIMIT，优先在页边界处分割。
        """
        page_pattern = re.compile(r'(===== 第 \d+ 页 =====)')
        segments = page_pattern.split(text)

        # 重新组装为 [(页标记, 页内容), ...]
        pages = []
        i = 0
        while i < len(segments):
            seg = segments[i].strip()
            if page_pattern.match(seg):
                content = segments[i + 1] if i + 1 < len(segments) else ''
                pages.append(f"{seg}\n{content.strip()}")
                i += 2
            else:
                if seg:
                    pages.append(seg)
                i += 1

        if not pages:
            return [text]

        # 贪心合并：尽量让每块接近 CHUNK_CHAR_LIMIT
        chunks = []
        current_chunk = []
        current_len = 0

        for page in pages:
            page_len = len(page)
            if current_len + page_len > self.CHUNK_CHAR_LIMIT and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [page]
                current_len = page_len
            else:
                current_chunk.append(page)
                current_len += page_len

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def _build_chunk_prompt(self, chunk_text: str, chunk_idx: int,
                            total_chunks: int, file_name: str = '') -> str:
        """构建单个分块的分析提示词（委托给 prompts 模块）"""
        return build_chunk_user_prompt(chunk_text, chunk_idx, total_chunks, file_name)

    def _build_merge_prompt(self, chunk_results: List[Dict], total_text_len: int) -> str:
        """构建合并多轮结果的提示词"""
        # 汇总所有分块的 core_arguments
        all_arguments = []
        all_key_data = []
        summaries = []
        titles = []

        for i, result in enumerate(chunk_results):
            for arg in result.get('core_arguments', []):
                arg['_from_chunk'] = i + 1
                all_arguments.append(arg)
            all_key_data.extend(result.get('key_data', []))
            if result.get('summary'):
                summaries.append(result['summary'])
            if result.get('title'):
                titles.append(result['title'])

        # 序列化各分块提取的论点
        args_text = json.dumps(all_arguments, ensure_ascii=False, indent=2)
        key_data_text = json.dumps(all_key_data, ensure_ascii=False, indent=2)
        summaries_text = '\n'.join(f'分块{i+1}: {s}' for i, s in enumerate(summaries))

        return build_merge_user_prompt(
            total_text_len=total_text_len,
            chunk_count=len(chunk_results),
            args_text=args_text,
            key_data_text=key_data_text,
            summaries=summaries_text
        )

    def _analyze_long_text(self, text: str, config: dict, system_prompt: str,
                           file_name: str = '', image_descriptions: str = '') -> Optional[Dict]:
        """
        Map-Reduce 长文档分析：
        Map   → 分块独立提取论点
        Reduce → 合并去重，生成最终结果
        """
        chunks = self._split_text_chunks(text)
        total_chunks = len(chunks)
        print(f"📑 长文档分块分析：共 {len(text)} 字符，分为 {total_chunks} 块")

        # ── Map 阶段：逐块分析 ──
        chunk_results = []
        for i, chunk in enumerate(chunks):
            chunk_idx = i + 1
            print(f"  🔍 分析第 {chunk_idx}/{total_chunks} 块 ({len(chunk)} 字符)...")

            user_content = self._build_chunk_prompt(chunk, chunk_idx, total_chunks, file_name)
            response = self._call_api(user_content, system_prompt, config, call_type='chunk')

            if response:
                result = self._parse_llm_response(response)
                if result:
                    args_count = len(result.get('core_arguments', []))
                    print(f"  ✅ 第 {chunk_idx} 块完成，提取 {args_count} 个论点")
                    chunk_results.append(result)
                else:
                    print(f"  ⚠️ 第 {chunk_idx} 块解析失败，跳过")
            else:
                print(f"  ⚠️ 第 {chunk_idx} 块 API 调用失败，跳过")

        if not chunk_results:
            print("❌ 所有分块分析均失败")
            return None

        # 如果只有一块成功，直接返回（无需合并）
        if len(chunk_results) == 1:
            return chunk_results[0]

        # ── Reduce 阶段：合并多块结果 ──
        total_args = sum(len(r.get('core_arguments', [])) for r in chunk_results)
        print(f"🔗 合并阶段：{len(chunk_results)} 块共提取 {total_args} 个论点，开始去重合并...")

        # 追加图片分析结果到合并 prompt
        merge_content = self._build_merge_prompt(chunk_results, len(text))
        if image_descriptions:
            merge_content += f"\n\n【图片分析结果】\n{image_descriptions}"

        merge_response = self._call_api(merge_content, system_prompt, config, call_type='merge')
        if merge_response:
            final_result = self._parse_llm_response(merge_response)
            if final_result:
                final_count = len(final_result.get('core_arguments', []))
                print(f"✅ 合并完成：最终保留 {final_count} 个核心论点")
                return final_result

        # 合并失败时，回退：直接拼接所有分块结果
        print("⚠️ 合并调用失败，使用直接拼接回退策略")
        return self._fallback_merge(chunk_results)

    def _fallback_merge(self, chunk_results: List[Dict]) -> Dict:
        """合并调用失败时的回退策略：直接拼接并按 importance 排序截取"""
        all_args = []
        all_key_data = []
        for r in chunk_results:
            all_args.extend(r.get('core_arguments', []))
            all_key_data.extend(r.get('key_data', []))

        # 按 importance 降序排序，保留 top 8
        all_args.sort(key=lambda x: x.get('importance', 0), reverse=True)
        return {
            'core_arguments': all_args[:8],
            'key_data': all_key_data,
            'summary': chunk_results[0].get('summary', ''),
            'title': chunk_results[0].get('title', '')
        }

    def _call_api(self, user_content: str, system_prompt: str, config: dict,
                  call_type: str = 'analyze') -> Optional[str]:
        """调用指定配置的 API（不再硬截断，由上层控制内容长度）"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config["api_key"]}'
        }
        data = {
            'model': config['model'],
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content}
            ],
            'temperature': 1.0
        }

        # DeepSeek V4 思考模式参数
        self._apply_thinking_params(data, config)

        if config.get('supports_json_format'):
            data['response_format'] = {'type': 'json_object'}

        _t0 = time.perf_counter()
        try:
            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config.get('timeout', 60)
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            if response.status_code == 200:
                result = response.json()
                content = self._extract_content(result)
                # ── 统计埋点 ──
                _usage = extract_usage(result)
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=config.get('model', ''),
                    call_type=call_type,
                    latency_ms=_latency,
                    prompt_tokens=_usage['prompt_tokens'],
                    completion_tokens=_usage['completion_tokens'],
                    total_tokens=_usage['total_tokens'],
                    status='success',
                    input_chars=len(user_content),
                    output_chars=len(content) if content else 0,
                )
                return content
            else:
                _latency = int((time.perf_counter() - _t0) * 1000)
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=config.get('model', ''),
                    call_type=call_type,
                    latency_ms=_latency,
                    status='error',
                    input_chars=len(user_content),
                    error_message=f'HTTP {response.status_code}',
                )
                print(f"API 错误: 状态码={response.status_code}, 响应={response.text}")
                return None
        except requests.exceptions.Timeout:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=config.get('model', ''),
                call_type=call_type,
                latency_ms=_latency,
                status='timeout',
                input_chars=len(user_content),
                error_message='timeout',
            )
            print(f"请求超时 ({config.get('timeout', 60)}s)：大模型响应过慢，请稍后重试。")
            return None
        except Exception as e:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''),
                model=config.get('model', ''),
                call_type=call_type,
                latency_ms=_latency,
                status='error',
                input_chars=len(user_content),
                error_message=str(e)[:200],
            )
            print(f"请求异常: {str(e)}")
            return None

    def _parse_llm_response(self, response: str) -> Optional[Dict]:
        """解析大模型返回的 JSON 结果（增强版：容忍 V4 思考模式可能的混合输出）"""
        try:
            response = response.strip()

            # 清理可能残留的 <think> 标签
            if '<think>' in response:
                response = re.sub(r'<think>[\s\S]*?</think>', '', response).strip()

            # 移除 markdown 代码块包装
            if response.startswith('```json'):
                response = response[7:]
            elif response.startswith('```'):
                response = response[3:]
            if response.endswith('```'):
                response = response[:-3]
            response = response.strip()

            # 尝试直接解析
            try:
                result = json.loads(response)
            except json.JSONDecodeError:
                # 降级：在文本中搜索第一个完整的 JSON 对象
                match = re.search(r'\{[\s\S]*\}', response)
                if match:
                    try:
                        result = json.loads(match.group())
                        print(f"  🔧 从混合文本中提取到 JSON（偏移 {match.start()} 字符）")
                    except json.JSONDecodeError:
                        print(f"解析大模型返回结果失败: 无法提取有效 JSON")
                        print(f"原始响应内容: {response[:500]}")
                        return None
                else:
                    print(f"解析大模型返回结果失败: 未找到 JSON 结构")
                    print(f"原始响应内容: {response[:500]}")
                    return None

            if 'core_arguments' in result and isinstance(result['core_arguments'], list):
                print(f"  ✅ 解析成功：{len(result['core_arguments'])} 个核心论点")
                return result

            # 兼容旧版本结构
            if 'keypoints' in result and isinstance(result['keypoints'], list):
                result['core_arguments'] = [
                    {'point': kp.get('content', ''), 'evidence': kp.get('keywords', [])}
                    for kp in result['keypoints']
                ]
                return result

            print(f"JSON 结果结构不符合预期。字段: {list(result.keys())}")
            print(f"内容详情: {response[:500]}...")
            return None

        except json.JSONDecodeError as e:
            print(f"解析大模型返回结果失败: {str(e)}")
            print(f"原始响应内容: {response[:500]}")
            return None

    def analyze_images(self, image_infos: list, provider: str = 'deepseek',
                       table_infos: list = None) -> str:
        """
        独立分析文档中的图片和表格信息（两阶段处理的第一阶段）
        Args:
            image_infos: 图片信息列表 [{'page': int, 'content': str, 'metadata': dict}, ...]
            provider: API 提供商
            table_infos: 表格信息列表 [{'page': int, 'content': str, 'table_data': list}, ...]
        Returns:
            图片+表格分析描述文本
        """
        if not image_infos and not table_infos:
            return ''

        table_infos = table_infos or []
        config = self._get_provider_config(provider)

        # 构建多媒体分析提示（prompt 来自 prompts 模块集中管理）
        media_prompt = MEDIA_INSTRUCTION_HEADER

        # 图片部分
        for idx, img in enumerate(image_infos or []):
            page = img.get('page', '未知')
            metadata = img.get('metadata', {})
            context = img.get('surrounding_text', '')

            media_prompt += f"--- 图片 {idx + 1}（第 {page} 页）---\n"
            media_prompt += f"格式: {metadata.get('format', '未知').upper()}, 尺寸: {metadata.get('width', 0)}x{metadata.get('height', 0)}\n"
            if context:
                media_prompt += f"图片周围的文本上下文:\n{context}\n"
            media_prompt += "\n"

        # 表格部分
        for idx, tbl in enumerate(table_infos):
            page = tbl.get('page', '未知')
            content = tbl.get('content', '')
            table_data = tbl.get('table_data', [])

            media_prompt += f"--- 表格 {idx + 1}（第 {page} 页）---\n"
            if table_data:
                # 展示表格结构化数据
                for row_idx, row in enumerate(table_data[:20]):  # 最多取 20 行
                    media_prompt += " | ".join(str(cell) for cell in row) + "\n"
                if len(table_data) > 20:
                    media_prompt += f"... (还有 {len(table_data) - 20} 行)\n"
            elif content:
                media_prompt += content[:500] + "\n"
            media_prompt += "\n"

        img_count = len(image_infos or [])
        tbl_count = len(table_infos)
        media_prompt += build_media_footer(img_count, tbl_count)

        try:
            total = img_count + tbl_count
            print(f"🖼️ 使用 {config['display_name']} 独立分析 {img_count} 张图片 + {tbl_count} 个表格...")
            result = self._call_api(
                media_prompt,
                MEDIA_SYSTEM_PROMPT,
                config,
                call_type='media'
            )
            if result:
                print(f"✅ 图片+表格分析完成")
                return result
            return ''
        except Exception as e:
            print(f"图片+表格分析失败: {str(e)}")
            return ''
