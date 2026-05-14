import sqlite3
import json
from datetime import datetime
import os

class Database:
    """数据库管理类"""
    
    def __init__(self, db_path='analysis.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """初始化数据库 + 兼容旧版 schema 迁移"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建分析记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_text TEXT NOT NULL,
                analysis_result TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_hash TEXT,
                recommend_cache TEXT,
                recommend_flag INTEGER DEFAULT 0,
                recommend_updated_at TIMESTAMP,
                recommend_last_click_at TIMESTAMP
            )
        ''')

        # 迁移：对旧版表缺失的列补成 ALTER
        cursor.execute('PRAGMA table_info(analysis_records)')
        existing_cols = {row[1] for row in cursor.fetchall()}
        migrations = [
            ('file_hash', 'TEXT'),
            ('recommend_cache', 'TEXT'),
            ('recommend_flag', 'INTEGER DEFAULT 0'),
            ('recommend_updated_at', 'TIMESTAMP'),
            ('recommend_last_click_at', 'TIMESTAMP'),
        ]
        for col, col_type in migrations:
            if col not in existing_cols:
                try:
                    cursor.execute(f'ALTER TABLE analysis_records ADD COLUMN {col} {col_type}')
                    print(f'[DB] 迁移：新增列 {col}')
                except sqlite3.OperationalError as e:
                    print(f'[DB] 迁移列 {col} 跳过: {e}')

        # 索引：file_hash 查找加速
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_hash ON analysis_records(file_hash)')

        # ── RAG 段落索引表（解析完成时预构建，chat 时按问题动态召回）──
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_rag_index (
                analysis_id INTEGER PRIMARY KEY,
                chunks_json TEXT NOT NULL,
                bm25_blob BLOB NOT NULL,
                chunk_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    # ── RAG 索引持久化 ──
    def save_rag_index(self, analysis_id, chunks_json, bm25_blob, chunk_count):
        """保存（或覆盖）指定分析记录的 BM25 索引。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO document_rag_index
                (analysis_id, chunks_json, bm25_blob, chunk_count, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (analysis_id, chunks_json, bm25_blob, chunk_count))
        conn.commit()
        conn.close()

    def load_rag_index(self, analysis_id):
        """读取指定分析记录的 BM25 索引原始字段。未命中返回 None。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT chunks_json, bm25_blob, chunk_count
            FROM document_rag_index WHERE analysis_id = ?
        ''', (analysis_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            'chunks_json': row[0],
            'bm25_blob': row[1],
            'chunk_count': row[2]
        }

    def delete_rag_index(self, analysis_id):
        """删除指定分析记录的 RAG 索引（随记录删除同步调用）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM document_rag_index WHERE analysis_id = ?', (analysis_id,))
        conn.commit()
        conn.close()
    
    def save_analysis(self, filename, original_text, analysis_result, file_hash=None):
        """保存分析结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO analysis_records (filename, original_text, analysis_result, file_hash)
            VALUES (?, ?, ?, ?)
        ''', (filename, original_text, json.dumps(analysis_result, ensure_ascii=False), file_hash))
        
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return record_id

    def find_by_hash(self, file_hash):
        """按文件哈希查找已解析的记录。命中则返回完整 record。"""
        if not file_hash:
            return None
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM analysis_records WHERE file_hash = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (file_hash,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return self.get_record(row[0])

    # ── 文献推荐缓存操作 ──
    def get_recommend_state(self, record_id):
        """返回推荐缓存状态：{flag, cache_json, updated_at, last_click_at}。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT recommend_flag, recommend_cache, recommend_updated_at, recommend_last_click_at
            FROM analysis_records WHERE id = ?
        ''', (record_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            'flag': int(row[0] or 0),
            'cache': row[1],
            'updated_at': row[2],
            'last_click_at': row[3]
        }

    def save_recommend_cache(self, record_id, cache_dict):
        """写入推荐缓存并置 flag=1，更新时间戳。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE analysis_records
            SET recommend_cache = ?, recommend_flag = 1, recommend_updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (json.dumps(cache_dict, ensure_ascii=False), record_id))
        conn.commit()
        conn.close()

    def touch_recommend_click(self, record_id):
        """更新最后一次点击时间（用于 10s 点击疲劳）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE analysis_records SET recommend_last_click_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (record_id,))
        conn.commit()
        conn.close()

    def invalidate_recommend(self, record_id):
        """将 flag 置 0，使下次请求重新生成。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE analysis_records SET recommend_flag = 0 WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
    
    def get_history(self, page=1, per_page=10):
        """获取历史记录列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取总数
        cursor.execute('SELECT COUNT(*) FROM analysis_records')
        total = cursor.fetchone()[0]
        
        # 获取分页数据
        offset = (page - 1) * per_page
        cursor.execute('''
            SELECT id, filename, created_at, analysis_result
            FROM analysis_records
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset))
        
        rows = cursor.fetchall()
        records = []
        
        for row in rows:
            analysis_result = json.loads(row[3])
            records.append({
                'id': row[0],
                'filename': row[1],
                'created_at': row[2],
                'title': analysis_result.get('title', row[1]),
                'keypoint_count': len(analysis_result.get('keypoints', [])),
                'word_count': analysis_result.get('statistics', {}).get('word_count', 0)
            })
        
        conn.close()
        
        return {
            'records': records,
            'total': total
        }
    
    def get_record(self, record_id):
        """获取单条记录详情"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, filename, original_text, analysis_result, created_at
            FROM analysis_records
            WHERE id = ?
        ''', (record_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        analysis_result = json.loads(row[3])
        
        return {
            'id': row[0],
            'filename': row[1],
            'content': row[2],
            'title': analysis_result.get('title', row[1]),
            'keypoints': analysis_result.get('keypoints', []),
            'summary': analysis_result.get('summary', {}),
            'statistics': analysis_result.get('statistics', {}),
            'highlights': analysis_result.get('highlights', []),
            'annotated_url': analysis_result.get('annotated_url'), # 提取标注URL
            'genre': analysis_result.get('genre'),  # 文体检测结果透传
            'argument_logic_graph': analysis_result.get('argument_logic_graph', {'nodes': [], 'edges': []}),
            'created_at': row[4],
            'analysis_result': analysis_result
        }
    
    def delete_record(self, record_id):
        """删除记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM analysis_records WHERE id = ?', (record_id,))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def search_records(self, keyword):
        """搜索记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, filename, created_at, analysis_result
            FROM analysis_records
            WHERE filename LIKE ? OR original_text LIKE ?
            ORDER BY created_at DESC
        ''', (f'%{keyword}%', f'%{keyword}%'))
        
        rows = cursor.fetchall()
        records = []
        
        for row in rows:
            analysis_result = json.loads(row[3])
            records.append({
                'id': row[0],
                'filename': row[1],
                'created_at': row[2],
                'title': analysis_result.get('title', row[1])
            })
        
        conn.close()
        
        return records
