"""
LLM API 调用统计模块 —— 仅用于后台分析，不对外暴露。

记录每次 API 调用的耗时、token 用量、provider / model 等信息，
写入独立的 SQLite 数据库 llm_stats.db，便于后续离线分析（pandas / SQL 查询）。

使用方式：
    from llm_stats import record_llm_call

    record_llm_call(
        provider='deepseek',
        model='deepseek-chat',
        call_type='analyze',          # analyze | chat | recommend | media | chunk | merge | file_upload
        latency_ms=3200,
        prompt_tokens=1500,
        completion_tokens=800,
        total_tokens=2300,
        status='success',             # success | error | timeout
        input_chars=12000,
        output_chars=3500,
        error_message='',
        extra_json='',                # 可选：任意附加 JSON 字符串
    )
"""

import os
import sqlite3
import threading
import json
from datetime import datetime
from typing import Optional

# 统计数据库路径：与主数据库同级目录
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'llm_stats.db')

# 线程锁：保证多线程安全写入
_lock = threading.Lock()

# ── 懒初始化标志 ──
_initialized = False


def _ensure_table():
    """首次调用时创建统计表（幂等）"""
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        conn = sqlite3.connect(_DB_PATH)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS llm_call_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT    NOT NULL,          -- ISO-8601 时间戳
                provider      TEXT    NOT NULL DEFAULT '',
                model         TEXT    NOT NULL DEFAULT '',
                call_type     TEXT    NOT NULL DEFAULT '',  -- analyze / chat / recommend / media / chunk / merge / file_upload
                latency_ms    INTEGER DEFAULT 0,           -- 调用耗时（毫秒）
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens  INTEGER DEFAULT 0,
                status        TEXT    NOT NULL DEFAULT 'success',  -- success / error / timeout
                input_chars   INTEGER DEFAULT 0,           -- 输入文本字符数
                output_chars  INTEGER DEFAULT 0,           -- 输出文本字符数
                error_message TEXT    DEFAULT '',
                extra_json    TEXT    DEFAULT ''            -- 预留：任意附加信息 JSON
            )
        ''')
        # 为常用查询建索引
        conn.execute('CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_call_log(ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_llm_provider ON llm_call_log(provider)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_llm_call_type ON llm_call_log(call_type)')
        conn.commit()
        conn.close()
        _initialized = True


def record_llm_call(
    provider: str = '',
    model: str = '',
    call_type: str = '',
    latency_ms: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    status: str = 'success',
    input_chars: int = 0,
    output_chars: int = 0,
    error_message: str = '',
    extra_json: str = '',
):
    """
    写入一条 LLM 调用统计记录。

    该函数内部做了异常保护，绝不会抛出异常影响主业务流程。
    """
    try:
        _ensure_table()
        ts = datetime.now().isoformat(timespec='milliseconds')
        with _lock:
            conn = sqlite3.connect(_DB_PATH)
            conn.execute(
                '''INSERT INTO llm_call_log
                   (ts, provider, model, call_type, latency_ms,
                    prompt_tokens, completion_tokens, total_tokens,
                    status, input_chars, output_chars, error_message, extra_json)
                   VALUES (?,?,?,?,?, ?,?,?, ?,?,?,?,?)''',
                (ts, provider, model, call_type, latency_ms,
                 prompt_tokens, completion_tokens, total_tokens,
                 status, input_chars, output_chars, error_message, extra_json)
            )
            conn.commit()
            conn.close()
    except Exception as e:
        # 统计写入失败不能影响主流程，只打印警告
        print(f'[llm_stats] 写入统计失败: {e}')


def extract_usage(api_response: dict) -> dict:
    """
    从 OpenAI 兼容格式的 API 响应中提取 token 用量。

    返回：{prompt_tokens, completion_tokens, total_tokens}
    若字段不存在则默认为 0。
    """
    usage = api_response.get('usage') or {}
    return {
        'prompt_tokens': int(usage.get('prompt_tokens', 0) or 0),
        'completion_tokens': int(usage.get('completion_tokens', 0) or 0),
        'total_tokens': int(usage.get('total_tokens', 0) or 0),
    }
