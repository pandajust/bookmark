# -*- coding: utf-8 -*-
"""数据库操作：连接、初始化、书签与标签 CRUD。"""

import os
import time
import sqlite3
import urllib.parse

# ===== 路径配置 =====
# 本文件位于 backend/ 子包内，项目根目录为上一级
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'bookmarks.db')

# ===== 标签长度限制 =====
MAX_TAG_LEN = 20


def _tag_len(s):
    """计算标签长度：中文算2，ASCII算1"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    hostname TEXT NOT NULL,
    description TEXT,
    markdown TEXT,
    category TEXT NOT NULL DEFAULT 'tech',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmark_tags (
    bookmark_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (bookmark_id, tag_id),
    FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_category ON bookmarks(category);
CREATE INDEX IF NOT EXISTS idx_bookmarks_created_at ON bookmarks(created_at);
CREATE INDEX IF NOT EXISTS idx_bookmarks_hostname ON bookmarks(hostname);
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.commit()
    conn.close()


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    # 并发写入时等待 5s 而非立即抛 "database is locked"
    conn.execute('PRAGMA busy_timeout = 5000')
    return conn


# ===== 业务逻辑 =====

def serialize_bookmark(row, tags=None):
    """将 sqlite Row 转为前端 JSON。"""
    return {
        'id': row['id'],
        'url': row['url'],
        'canonical_url': row['canonical_url'],
        'title': row['title'],
        'hostname': row['hostname'],
        'description': row['description'] or '',
        'markdown': row['markdown'] or '',
        'category': row['category'],
        'status': row['status'],
        'error': row['error'] or '',
        'tags': tags if tags is not None else [],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


def get_bookmark_tags(conn, bookmark_id):
    cur = conn.execute(
        '''SELECT t.id, t.name, t.display_name FROM tags t
           JOIN bookmark_tags bt ON bt.tag_id = t.id
           WHERE bt.bookmark_id = ? ORDER BY t.name''',
        (bookmark_id,)
    )
    return [{'id': r['id'], 'name': r['display_name']} for r in cur.fetchall()]


def get_bookmark_tags_batch(conn, bookmark_ids):
    """批量查询多个书签的标签，返回 {bookmark_id: [{'id','name'}, ...]}。

    用一条 SQL JOIN 替代逐条查询，解决 list_bookmarks / search_bookmarks 的 N+1 问题。
    """
    result = {bid: [] for bid in bookmark_ids}
    if not bookmark_ids:
        return result
    placeholders = ','.join('?' * len(bookmark_ids))
    cur = conn.execute(
        '''SELECT bt.bookmark_id, t.id, t.name, t.display_name
           FROM bookmark_tags bt
           JOIN tags t ON t.id = bt.tag_id
           WHERE bt.bookmark_id IN ({})
           ORDER BY bt.bookmark_id, t.name'''.format(placeholders),
        tuple(bookmark_ids)
    )
    for r in cur.fetchall():
        bid = r['bookmark_id']
        if bid in result:
            result[bid].append({'id': r['id'], 'name': r['display_name']})
    return result


def set_bookmark_tags(conn, bookmark_id, tag_names):
    """替换某书签的全部标签关联。

    单个标签长度限制：中文算 2 个单位，ASCII 算 1 个单位，总长不超过
    MAX_TAG_LEN（默认 20，即最多 20 个英文或 10 个中文）。超限的标签跳过，不报错。
    """
    conn.execute('DELETE FROM bookmark_tags WHERE bookmark_id = ?', (bookmark_id,))
    seen = set()
    for raw in tag_names or []:
        name = (str(raw) or '').strip()
        if not name:
            continue
        if _tag_len(name) > MAX_TAG_LEN:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        # 插入或获取 tag
        cur = conn.execute('SELECT id FROM tags WHERE name = ?', (key,))
        r = cur.fetchone()
        if r:
            tag_id = r['id']
        else:
            cur = conn.execute(
                'INSERT INTO tags (name, display_name) VALUES (?, ?)',
                (key, name)
            )
            tag_id = cur.lastrowid
        conn.execute(
            'INSERT OR IGNORE INTO bookmark_tags (bookmark_id, tag_id) VALUES (?, ?)',
            (bookmark_id, tag_id)
        )


def create_bookmark(conn, payload):
    """创建书签，重复 canonical_url 返回 (None, 'duplicate', existing)。

    注意：只做 http/https 格式校验，不做 DNS/连通性预检查。
    DNS 解析失败、超时、404 等抓取失败场景由后台 fetch_and_update 线程
    写入 failed 状态，保证收藏"一定被保存"，抓取错误只影响正文是否为空。
    """
    url = (payload.get('url') or '').strip()
    title = (payload.get('title') or '').strip()
    category = (payload.get('category') or 'tech').strip()
    tags = payload.get('tags') or []

    # URL 校验增强：解析 scheme/host，拒绝空 host、无点号 host、含空格的误粘贴文本
    if ' ' in url:
        return None, 'invalid_url', None
    try:
        u = urllib.parse.urlparse(url)
        port = u.port  # 非数字端口会抛 ValueError
    except Exception:
        return None, 'invalid_url', None
    if u.scheme not in ('http', 'https'):
        return None, 'invalid_url', None
    host = (u.hostname or '').lower()
    if not host or '.' not in host:
        return None, 'invalid_url', None

    # 宽松规范化：只处理 scheme/host 大小写和去 fragment，不做 DNS 检查
    netloc = host
    if port and not ((u.scheme == 'http' and port == 80) or (u.scheme == 'https' and port == 443)):
        netloc = '{}:{}'.format(host, port)
    path = u.path or '/'
    canonical = urllib.parse.urlunparse((u.scheme, netloc, path, u.params, u.query, ''))

    # 检查重复
    cur = conn.execute('SELECT * FROM bookmarks WHERE canonical_url = ?', (canonical,))
    existing = cur.fetchone()
    if existing:
        return None, 'duplicate', serialize_bookmark(existing, get_bookmark_tags(conn, existing['id']))

    if not title:
        # hostname 兜底（显示用，不含 www.）
        title = host[4:] if host.startswith('www.') else host

    now = int(time.time() * 1000)
    cur = conn.execute(
        '''INSERT INTO bookmarks
           (url, canonical_url, title, hostname, description, markdown, category, status, error, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (url, canonical, title, host, '', '', category, 'pending', '', now, now)
    )
    bookmark_id = cur.lastrowid
    set_bookmark_tags(conn, bookmark_id, tags)
    conn.commit()

    row = conn.execute('SELECT * FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
    return serialize_bookmark(row, get_bookmark_tags(conn, bookmark_id)), None, None


def update_bookmark(conn, bookmark_id, patch):
    row = conn.execute('SELECT * FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
    if not row:
        return None
    allowed = {'title', 'category', 'description', 'markdown', 'status', 'error',
               'url', 'canonical_url', 'hostname'}
    updates = []
    params = []
    for k, v in patch.items():
        if k in allowed:
            updates.append('{} = ?'.format(k))
            params.append(v)
    if updates:
        updates.append('updated_at = ?')
        params.append(int(time.time() * 1000))
        params.append(bookmark_id)
        conn.execute('UPDATE bookmarks SET {} WHERE id = ?'.format(', '.join(updates)), params)

    if 'tags' in patch:
        set_bookmark_tags(conn, bookmark_id, patch['tags'])

    conn.commit()
    row = conn.execute('SELECT * FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
    return serialize_bookmark(row, get_bookmark_tags(conn, bookmark_id))


def list_bookmarks(conn):
    rows = conn.execute('SELECT * FROM bookmarks ORDER BY created_at DESC').fetchall()
    ids = [r['id'] for r in rows]
    tags_map = get_bookmark_tags_batch(conn, ids)
    return [serialize_bookmark(r, tags_map.get(r['id'], [])) for r in rows]


def get_bookmark(conn, bid):
    r = conn.execute('SELECT * FROM bookmarks WHERE id = ?', (bid,)).fetchone()
    if not r:
        return None
    return serialize_bookmark(r, get_bookmark_tags(conn, bid))


def delete_bookmark(conn, bid):
    conn.execute('DELETE FROM bookmarks WHERE id = ?', (bid,))
    conn.commit()
    return True


def list_tags(conn):
    # INNER JOIN 自动过滤掉无关联的孤儿标签（书签删除后留下的空标签）
    cur = conn.execute(
        '''SELECT t.id, t.display_name, COUNT(bt.bookmark_id) AS cnt
           FROM tags t
           INNER JOIN bookmark_tags bt ON bt.tag_id = t.id
           GROUP BY t.id
           HAVING cnt > 0
           ORDER BY cnt DESC, t.name'''
    )
    return [{'id': r['id'], 'name': r['display_name'], 'count': r['cnt']} for r in cur.fetchall()]


def search_bookmarks(conn, query, category=None, tag=None):
    q = '%' + query + '%' if query else None
    sql = '''SELECT DISTINCT b.* FROM bookmarks b
             LEFT JOIN bookmark_tags bt ON bt.bookmark_id = b.id
             LEFT JOIN tags t ON t.id = bt.tag_id
             WHERE 1=1'''
    params = []
    if q:
        sql += ' AND (b.title LIKE ? OR b.url LIKE ? OR b.markdown LIKE ? OR b.description LIKE ? OR t.display_name LIKE ?)'
        params.extend([q, q, q, q, q])
    if category and category != 'all':
        sql += ' AND b.category = ?'
        params.append(category)
    if tag:
        sql += ' AND t.display_name = ?'
        params.append(tag)
    sql += ' ORDER BY b.created_at DESC'
    rows = conn.execute(sql, params).fetchall()
    ids = [r['id'] for r in rows]
    tags_map = get_bookmark_tags_batch(conn, ids)
    return [serialize_bookmark(r, tags_map.get(r['id'], [])) for r in rows]


def category_counts(conn):
    rows = conn.execute('SELECT category, COUNT(*) AS cnt FROM bookmarks GROUP BY category').fetchall()
    counts = {'all': 0, 'tech': 0, 'design': 0, 'read': 0, 'tool': 0}
    total = 0
    for r in rows:
        if r['category'] in counts:
            counts[r['category']] = r['cnt']
        total += r['cnt']
    counts['all'] = total
    return counts
