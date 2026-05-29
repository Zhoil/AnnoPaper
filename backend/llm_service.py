import os
import re
import json
import time
import random
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
            # 部分网关（如 api.gpt.ge）对 gemini reasoning 模型首包较慢、易吃满 max_tokens，需走 stream 才稳定
            'supports_stream': os.environ.get(f'{prefix}_SUPPORTS_STREAM', '').lower() == 'true',
            # stream 白名单：逗号分隔；定义后仅命中列表的模型走 stream，其余直接 non-stream（gpt-5.x/claude 在 api.gpt.ge 上 non-stream 更稳）
            'stream_models': [m.strip() for m in os.environ.get(f'{prefix}_STREAM_MODELS', '').split(',') if m.strip()],
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

    def _post_stream(self, url: str, headers: dict, data: dict, timeout: int) -> dict:
        """
        发送流式（SSE）请求并汇总结果，统一模拟非流式的返回结构。
        适用于类似 `api.gpt.ge` 的网关（gemini reasoning 模型 non-stream 首包慢、易截断，需 stream）。

        返回结构：
            {
              'status_code': int,
              'error': Optional[str],   # 非 200 时的错误文本
              'result': dict            # 模拟 OpenAI 非流式的响应体 (成功时)
            }
        """
        data = dict(data)  # 浅拷贝，避免污染调用方
        data['stream'] = True

        try:
            resp = requests.post(url, headers=headers, json=data, timeout=timeout, stream=True)
        except requests.exceptions.Timeout:
            raise
        except Exception:
            raise

        # 强制 UTF-8 解码，避免 api.gpt.ge 对 Gemini 返回体走 Latin-1 造成中文乱码
        resp.encoding = 'utf-8'

        if resp.status_code != 200:
            # 非 200 不是 SSE，直接读文本
            try:
                err_text = resp.text[:500]
            except Exception:
                err_text = ''
            return {'status_code': resp.status_code, 'error': err_text, 'result': None}

        merged_content = ''
        merged_reasoning = ''
        finish_reason = None
        usage = None
        model_name = data.get('model', '')
        response_id = ''

        try:
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if obj.get('id'):
                    response_id = obj['id']
                if obj.get('model'):
                    model_name = obj['model']
                if obj.get('usage'):
                    usage = obj['usage']

                for ch in obj.get('choices', []) or []:
                    delta = ch.get('delta') or {}
                    message = ch.get('message') or {}
                    piece = delta.get('content') or message.get('content') or ''
                    if piece:
                        merged_content += piece
                    rpiece = delta.get('reasoning_content') or message.get('reasoning_content') or ''
                    if rpiece:
                        merged_reasoning += rpiece
                    if ch.get('finish_reason'):
                        finish_reason = ch['finish_reason']
        finally:
            resp.close()

        simulated = {
            'id': response_id,
            'model': model_name,
            'object': 'chat.completion',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': merged_content,
                    'reasoning_content': merged_reasoning,
                },
                # 保留真实 finish_reason（None 表示流可能被中断），供上层判断断流
                'finish_reason': finish_reason,
            }],
        }
        if usage:
            simulated['usage'] = usage
        return {'status_code': 200, 'error': None, 'result': simulated}

    # 网关“负载类”故障关键字：命中时视为可重试、可降级
    _LOAD_ERROR_HINTS = (
        'no available accounts',
        'rate limit', 'rate_limit',
        'overloaded', 'try again',
        'server is busy', 'too many requests',
        'upstream', 'no available channel',
    )
    # 负载类HTTP状态码
    _LOAD_STATUS_CODES = (429, 500, 502, 503, 504)

    def _stream_or_fallback(self, config: dict, headers: dict, data: dict, timeout: int) -> dict:
        """
        弹性调用 PipeLLM 类网关（当前默认网关：api.gpt.ge）：
          ① 模型在 stream_models 白名单中（如 gemini-3.1-pro-preview 等 reasoning 模型）→ 先用 stream，失败后降级到 non-stream；
          ② 模型不在白名单中（如 gpt-5.5 / gpt-5.4 / claude-opus-4-7 / claude-opus-4-7-low）→ 直接走 non-stream 重试（这些模型 non-stream 秒级响应更稳）。
        返回结构：{'status_code', 'error', 'result'}
        """
        try:
            stream_retries = int(os.environ.get('PIPELLM_STREAM_RETRY_MAX', '3'))
        except Exception:
            stream_retries = 3
        try:
            nonstream_retries = int(os.environ.get('PIPELLM_NONSTREAM_RETRY_MAX', '3'))
        except Exception:
            nonstream_retries = 3

        model_name = data.get('model') or config.get('model') or ''
        white = config.get('stream_models') or []
        # 白名单留空 = 所有模型都用 stream；定义后只要模型名字命中其中一个前缀或全名
        use_stream = (not white) or any(model_name == w or model_name.startswith(w) for w in white)

        last = {'status_code': 0, 'error': 'not started', 'result': None}

        # ── 阶段 A：stream 重试（仅白名单模型）──
        if use_stream:
            for i in range(stream_retries):
                try:
                    res = self._post_stream(config['api_url'], headers, data, timeout)
                except requests.exceptions.Timeout:
                    raise
                except Exception as e:
                    last = {'status_code': -1, 'error': str(e)[:300], 'result': None}
                else:
                    if res.get('status_code') == 200 and res.get('result') is not None:
                        try:
                            choice0 = res['result']['choices'][0]
                            content = (choice0.get('message') or {}).get('content') or ''
                            finish = choice0.get('finish_reason')
                        except Exception:
                            content, finish = '', None
                        if content and finish in ('stop', 'end_turn'):
                            return res
                        if content:
                            last = {'status_code': 200, 'error': f'stream truncated (finish_reason={finish!r})', 'result': res['result']}
                        else:
                            last = {'status_code': 200, 'error': 'empty content from stream', 'result': res['result']}
                    else:
                        last = res

                if i < stream_retries - 1:
                    sleep_s = 0.6 * (2 ** i) + random.random() * 0.4
                    print(f"  ⏳ {config.get('display_name','LLM')} stream 第 {i+1}/{stream_retries} 次失败 (code={last.get('status_code')})，{sleep_s:.1f}s 后重试")
                    time.sleep(sleep_s)
        else:
            print(f"  ➡️ {config.get('display_name','LLM')} 模型 {model_name} 不在 stream 白名单，直接使用 non-stream")

        # ── 阶段 B：non-stream 重试（白名单模型所有 stream 失败后的降级路径，或非白名单模型的主路径）──
        if use_stream:
            print(f"  ♻️ {config.get('display_name','LLM')} stream 全部失败，降级到 non-stream")
        ns_data = dict(data)
        ns_data['stream'] = False
        for j in range(nonstream_retries):
            try:
                r = requests.post(config['api_url'], headers=headers, json=ns_data, timeout=timeout)
            except requests.exceptions.Timeout:
                raise
            except Exception as e:
                last = {'status_code': -1, 'error': f'non-stream exc: {e}'[:300], 'result': None}
            else:
                # 强制 UTF-8，避免网关对 Gemini 返回体按 Latin-1 解码导致 JSON 中文乱码
                r.encoding = 'utf-8'
                if r.status_code == 200:
                    try:
                        j_obj = r.json()
                        choices = j_obj.get('choices') or []
                        if choices and (choices[0].get('message') or {}).get('content'):
                            return {'status_code': 200, 'error': None, 'result': j_obj}
                        last = {'status_code': 200, 'error': 'empty content (non-stream)', 'result': None}
                    except Exception as e:
                        # 部分网关忽略 stream=false，还是返 SSE 文本
                        sse_res = self._parse_sse_text(r.text, model_hint=ns_data.get('model', ''))
                        if sse_res is not None:
                            try:
                                choice0 = sse_res['choices'][0]
                                content = (choice0.get('message') or {}).get('content') or ''
                                finish = choice0.get('finish_reason')
                                if content and finish in ('stop', 'end_turn'):
                                    return {'status_code': 200, 'error': None, 'result': sse_res}
                                last = {'status_code': 200, 'error': f'non-stream-sse truncated (finish_reason={finish!r})', 'result': sse_res}
                            except Exception:
                                last = {'status_code': 200, 'error': 'non-stream-sse parse error', 'result': None}
                        else:
                            last = {'status_code': 200, 'error': f'non-stream parse: {e}'[:300], 'result': None}
                else:
                    last = {'status_code': r.status_code, 'error': r.text[:300], 'result': None}

            err_text = (last.get('error') or '').lower()
            code = last.get('status_code') or 0
            retriable = (
                any(h in err_text for h in self._LOAD_ERROR_HINTS)
                or code in self._LOAD_STATUS_CODES
                or 'empty content' in err_text
                or 'truncated' in err_text
            )
            if not retriable:
                break
            if j < nonstream_retries - 1:
                sleep_s = 0.8 * (2 ** j) + random.random() * 0.5
                print(f"  ⏳ {config.get('display_name','LLM')} non-stream 第 {j+1}/{nonstream_retries} 次失败 (code={code})，{sleep_s:.1f}s 后重试")
                time.sleep(sleep_s)

        return last

    def _parse_sse_text(self, text: str, model_hint: str = '') -> Optional[dict]:
        """将一段 SSE 完整文本（包含多行 data:）解析为非流式风格的 result dict。"""
        if not text or 'data:' not in text:
            return None
        merged_content, merged_reasoning = '', ''
        model_name, response_id, usage, finish_reason = model_hint, '', None, None
        for raw in text.splitlines():
            line = raw.strip()
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                break
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if obj.get('id'):
                response_id = obj['id']
            if obj.get('model'):
                model_name = obj['model']
            if obj.get('usage'):
                usage = obj['usage']
            for ch in obj.get('choices', []) or []:
                delta = ch.get('delta') or {}
                msg = ch.get('message') or {}
                piece = delta.get('content') or msg.get('content') or ''
                if piece:
                    merged_content += piece
                rp = delta.get('reasoning_content') or msg.get('reasoning_content') or ''
                if rp:
                    merged_reasoning += rp
                if ch.get('finish_reason'):
                    finish_reason = ch['finish_reason']
        if not merged_content:
            return None
        result = {
            'id': response_id, 'model': model_name, 'object': 'chat.completion',
            'choices': [{
                'index': 0,
                'message': {'role': 'assistant', 'content': merged_content, 'reasoning_content': merged_reasoning},
                'finish_reason': finish_reason or 'stop',
            }],
        }
        if usage:
            result['usage'] = usage
        return result

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

    def _build_system_prompt(self, provider: str, genre_hint: str = '') -> str:
        """根据提供商构建系统提示词（委托给 prompts 模块）

        Args:
            provider: API 提供商
            genre_hint: 文体检测结果生成的定制分析指引
        """
        config = self._get_provider_config(provider)
        model_ref = config.get('display_name', 'DeepSeek-V4-Pro')
        return build_analyze_system_prompt(model_ref, genre_hint=genre_hint)

    def analyze_text(self, text: str, provider: str = 'deepseek',
                     file_path: Optional[str] = None, file_size: int = 0,
                     image_descriptions: str = '',
                     model_override: str = '',
                     genre_hint: str = '') -> Optional[Dict]:
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
            genre_hint: 文体检测结果生成的定制分析指引（注入 system prompt）
        """
        config = self._get_provider_config(provider)
        # 如果前端指定了具体模型，覆盖默认模型
        if model_override:
            config['model'] = model_override
            print(f"🎯 使用前端指定模型: {model_override}")
        system_prompt = self._build_system_prompt(provider, genre_hint=genre_hint)

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
            if config.get('supports_stream'):
                stream_res = self._stream_or_fallback(config, headers, data, config['timeout'])
                _latency = int((time.perf_counter() - _t0) * 1000)
                if stream_res['status_code'] == 200 and stream_res['result'] is not None:
                    result = stream_res['result']
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
                        error_message=f"HTTP {stream_res['status_code']}",
                    )
                    print(f"Chat API 错误(stream): {stream_res['status_code']}, {stream_res.get('error', '')}")
                    return None

            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config['timeout']
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            # 强制 UTF-8 解码，规避网关对某些模型（如 Gemini）返回体按 Latin-1 解码的乱码问题
            response.encoding = 'utf-8'

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

    def chat_stream(self, message: str, document_context: str, chat_history: list,
                    deep_thinking: bool = False):
        """
        AI 对话流式接口（生成器）—— 逐 chunk yield SSE 事件。

        Yields: (event_type, data_dict)
          - ('thinking', {'text': '...'})
          - ('content',  {'text': '...'})
          - ('done',     {'usage': {...}})
          - ('error',    {'message': '...'})
        """
        config = self._get_provider_config(self.chat_provider)
        model_name = config['display_name']
        system_prompt = build_chat_system_prompt(model_name, document_context)

        messages = [{'role': 'system', 'content': system_prompt}]
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
            'stream': True,
        }

        if deep_thinking:
            self._apply_thinking_params(data, config)
        else:
            data['temperature'] = 0.7

        _t0 = time.perf_counter()
        try:
            resp = requests.post(
                config['api_url'], headers=headers, json=data,
                timeout=config['timeout'], stream=True
            )
            resp.encoding = 'utf-8'

            if resp.status_code != 200:
                err_text = ''
                try:
                    err_text = resp.text[:500]
                except Exception:
                    pass
                yield ('error', {'message': f'API 返回 {resp.status_code}: {err_text}'})
                return

            usage = None
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if obj.get('usage'):
                    usage = obj['usage']

                for ch in obj.get('choices', []) or []:
                    delta = ch.get('delta') or {}
                    # 思考过程片段
                    reasoning_piece = delta.get('reasoning_content') or ''
                    if reasoning_piece:
                        yield ('thinking', {'text': reasoning_piece})
                    # 正式回答片段
                    content_piece = delta.get('content') or ''
                    if content_piece:
                        yield ('content', {'text': content_piece})

            resp.close()

            # 完成事件
            _latency = int((time.perf_counter() - _t0) * 1000)
            usage_info = {}
            if usage:
                usage_info = {
                    'prompt_tokens': usage.get('prompt_tokens', 0),
                    'completion_tokens': usage.get('completion_tokens', 0),
                    'total_tokens': usage.get('total_tokens', 0),
                }
            record_llm_call(
                provider=config.get('provider', ''),
                model=config.get('model', ''),
                call_type='chat_stream',
                latency_ms=_latency,
                prompt_tokens=usage_info.get('prompt_tokens', 0),
                completion_tokens=usage_info.get('completion_tokens', 0),
                total_tokens=usage_info.get('total_tokens', 0),
                status='success',
                input_chars=len(message),
            )
            yield ('done', {'usage': usage_info, 'latency_ms': _latency})

        except requests.exceptions.Timeout:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''), model=config.get('model', ''),
                call_type='chat_stream', latency_ms=_latency, status='timeout',
                input_chars=len(message), error_message='timeout',
            )
            yield ('error', {'message': '请求超时，请稍后重试'})
        except Exception as e:
            _latency = int((time.perf_counter() - _t0) * 1000)
            record_llm_call(
                provider=config.get('provider', ''), model=config.get('model', ''),
                call_type='chat_stream', latency_ms=_latency, status='error',
                input_chars=len(message), error_message=str(e)[:200],
            )
            yield ('error', {'message': f'对话失败: {str(e)}'})

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
        注：调用 API 时使用文件专用模型名（如 qwen-long），
             但统计埋点统一记录为配置中的主模型名（如 qwen3.6-plus），
             以便 llm_stats.db 聚合时不会被 file_model 别名拆成多条。
        """
        # 用于埋点统计的规范模型名（文件直传要和普通 chat 调用聚合到同一模型）
        stat_model = config.get('model') or model
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
            if config.get('supports_stream'):
                stream_res = self._stream_or_fallback(config, headers, data, config.get('timeout', 120))
                _latency = int((time.perf_counter() - _t0) * 1000)
                if stream_res['status_code'] == 200 and stream_res['result'] is not None:
                    result = stream_res['result']
                    content = self._extract_content(result)
                    _usage = extract_usage(result)
                    record_llm_call(
                        provider=config.get('provider', ''),
                        model=stat_model,
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
                        model=stat_model,
                        call_type='file_upload',
                        latency_ms=_latency,
                        status='error',
                        input_chars=len(user_prompt),
                        error_message=f"HTTP {stream_res['status_code']}",
                    )
                    print(f"  文件分析 API 错误(stream): {stream_res['status_code']}, {stream_res.get('error', '')[:300]}")
                    return None

            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config.get('timeout', 120)
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            # 强制 UTF-8 解码，规避 Gemini 等模型网关返回体的乱码问题
            response.encoding = 'utf-8'

            if response.status_code == 200:
                result = response.json()
                content = self._extract_content(result)
                _usage = extract_usage(result)
                record_llm_call(
                    provider=config.get('provider', ''),
                    model=stat_model,
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
                    model=stat_model,
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
                model=stat_model,
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
                model=stat_model,
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
            if config.get('supports_stream'):
                stream_res = self._stream_or_fallback(config, headers, data, config.get('timeout', 60))
                _latency = int((time.perf_counter() - _t0) * 1000)
                if stream_res['status_code'] == 200 and stream_res['result'] is not None:
                    result = stream_res['result']
                    content = self._extract_content(result)
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
                    record_llm_call(
                        provider=config.get('provider', ''),
                        model=config.get('model', ''),
                        call_type=call_type,
                        latency_ms=_latency,
                        status='error',
                        input_chars=len(user_content),
                        error_message=f"HTTP {stream_res['status_code']}",
                    )
                    print(f"API 错误(stream): 状态码={stream_res['status_code']}, 响应={stream_res.get('error', '')}")
                    return None

            response = requests.post(
                config['api_url'],
                headers=headers,
                json=data,
                timeout=config.get('timeout', 60)
            )
            _latency = int((time.perf_counter() - _t0) * 1000)

            # 强制 UTF-8 解码，规避 Gemini 等模型网关返回体的乱码问题
            response.encoding = 'utf-8'

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
