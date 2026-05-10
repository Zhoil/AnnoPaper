"""
一次性脚本：为 analysis_records 表中已有的历史记录回填 RAG 索引。

用法：
    cd backend
    python -m scripts.rebuild_rag_index           # 为所有缺失索引的记录构建
    python -m scripts.rebuild_rag_index --force   # 强制重建全部记录的索引
    python -m scripts.rebuild_rag_index --id 12   # 仅处理指定 id

说明：
- 旧记录无 structured_content（未持久化到 DB），仅能基于 original_text 按段落切分
- 新上传文档会在 app.py 的上传流程自动构建索引，无需再跑本脚本
"""

import os
import sys
import argparse
import sqlite3

# 允许直接 `python scripts/rebuild_rag_index.py` 或 `python -m scripts.rebuild_rag_index`
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from database import Database  # noqa: E402
import rag_indexer  # noqa: E402


def _list_all_ids(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id FROM analysis_records ORDER BY id ASC')
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids


def _has_index(db_path: str, analysis_id: int) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM document_rag_index WHERE analysis_id = ?', (analysis_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def _fetch_text(db_path: str, analysis_id: int):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT original_text FROM analysis_records WHERE id = ?', (analysis_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def rebuild(target_ids, force: bool, db_path: str):
    db = Database(db_path=db_path)
    ok, skip, fail = 0, 0, 0
    for aid in target_ids:
        if not force and _has_index(db_path, aid):
            skip += 1
            continue
        text = _fetch_text(db_path, aid)
        if not text:
            print(f'[SKIP] id={aid} 无原文')
            skip += 1
            continue
        try:
            chunks = rag_indexer.build_chunks([], text)
            if not chunks:
                print(f'[SKIP] id={aid} 未能切分出 chunks')
                skip += 1
                continue
            built = rag_indexer.build_index(chunks)
            if not built:
                print(f'[FAIL] id={aid} BM25 构建失败（检查 rank_bm25 是否已安装）')
                fail += 1
                continue
            chunks_json, bm25_blob, cnt = built
            db.save_rag_index(aid, chunks_json, bm25_blob, cnt)
            rag_indexer.invalidate_cache(aid)
            print(f'[OK]   id={aid} chunks={cnt}')
            ok += 1
        except Exception as e:
            print(f'[FAIL] id={aid} {e}')
            fail += 1
    print(f'\n完成：成功 {ok}，跳过 {skip}，失败 {fail}')


def main():
    parser = argparse.ArgumentParser(description='回填 document_rag_index 索引')
    parser.add_argument('--force', action='store_true', help='强制重建（覆盖已有索引）')
    parser.add_argument('--id', type=int, default=None, help='仅处理指定 analysis_id')
    parser.add_argument('--db', type=str, default=os.path.join(_BACKEND_DIR, 'analysis.db'),
                        help='数据库文件路径，默认 backend/analysis.db')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f'数据库不存在: {args.db}')
        sys.exit(1)

    if args.id is not None:
        target_ids = [args.id]
    else:
        target_ids = _list_all_ids(args.db)
    print(f'待处理记录数: {len(target_ids)}  force={args.force}')
    rebuild(target_ids, args.force, args.db)


if __name__ == '__main__':
    main()
