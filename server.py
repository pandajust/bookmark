"""
Bookmark Hub - 后端服务

单进程三层架构：
  - 浏览器原生 HTML/CSS/JS  负责交互
  - Python ThreadingHTTPServer  提供静态文件、REST API、网页抓取
  - SQLite  保存收藏、Markdown 与标签

启动：
  python server.py            # 默认 0.0.0.0:8765
  python server.py 9000       # 自定义端口

数据库固定在 data/bookmarks.db，启动只执行 CREATE TABLE IF NOT EXISTS。
"""

import sys
import os
import json
import re
import time
import socket
import sqlite3
import ipaddress
import threading
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from email.utils import formatdate

# ===== 全局配置 =====
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'bookmarks.db')
STATIC_DIR = ROOT_DIR

HOST = '0.0.0.0'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# 抓取限制
FETCH_TIMEOUT = 15            # 单次请求超时（秒）
FETCH_MAX_BYTES = 5 * 1024 * 1024   # 5MB
FETCH_MAX_REDIRECTS = 5
FETCH_USER_AGENT = 'BookmarkHub/1.0 (+https://github.com/local)'

# ===== 数据库 =====

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
    return conn


# ===== 工具函数 =====

def canonicalize_url(raw):
    """规范化 URL：补协议、去 fragment、小写 host。"""
    if not raw:
        return None, None
    s = raw.strip()
    if not s:
        return None, None
    if not re.match(r'^https?://', s, re.I):
        if s.startswith('//'):
            s = 'http:' + s
        else:
            s = 'http://' + s
    try:
        u = urllib.parse.urlparse(s)
    except Exception:
        return None, None
    if u.scheme not in ('http', 'https'):
        return None, None
    host = (u.hostname or '').lower()
    if not host:
        return None, None
    # 重组
    port = u.port
    netloc = host
    if port and not ((u.scheme == 'http' and port == 80) or (u.scheme == 'https' and port == 443)):
        netloc = '{}:{}'.format(host, port)
    if u.username:
        auth = u.username
        if u.password:
            auth += ':' + u.password
        netloc = auth + '@' + netloc
    path = u.path or '/'
    canonical = urllib.parse.urlunparse((u.scheme, netloc, path, u.params, u.query, ''))
    return canonical, host


def is_public_ip(ip_str):
    """检查 IP 是否是公网地址（拒绝私网/环回/链路本地/保留）。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_private:
        return False
    if ip.is_loopback:
        return False
    if ip.is_link_local:
        return False
    if ip.is_reserved:
        return False
    if ip.is_multicast:
        return False
    if ip.is_unspecified:
        return False
    # IPv4 映射的 IPv6
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped and not is_public_ip(str(ip.ipv4_mapped)):
            return False
    return True


def resolve_and_validate_host(hostname):
    """解析主机名并验证所有 IP 都是公网地址。"""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        if not is_public_ip(ip):
            return False
    return True


# ===== HTTP 抓取（带 SSRF 防护） =====

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向时校验目标主机也是公网。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        canonical, host = canonicalize_url(newurl)
        if not canonical or not host:
            raise urllib.error.URLError('Invalid redirect target')
        if not resolve_and_validate_host(host):
            raise urllib.error.URLError('Redirect to non-public host blocked: ' + host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url):
    """安全抓取 HTML，返回 (html, final_url) 或抛出异常。"""
    canonical, host = canonicalize_url(url)
    if not canonical:
        raise ValueError('Invalid URL')
    if not resolve_and_validate_host(host):
        raise ValueError('Host not public or not resolvable: ' + host)

    # 安装自定义 opener
    opener = urllib.request.build_opener(SafeRedirectHandler)

    req = urllib.request.Request(
        canonical,
        headers={
            'User-Agent': FETCH_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        },
        method='GET',
    )

    resp = opener.open(req, timeout=FETCH_TIMEOUT)
    # 检查 Content-Type
    ctype = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
    if ctype and ctype not in ('text/html', 'application/xhtml+xml', 'application/xml', 'text/plain'):
        raise ValueError('Unsupported content type: ' + ctype)

    # 限流读取
    read_bytes = 0
    chunks = []
    while True:
        chunk = resp.read(8192)
        if not chunk:
            break
        read_bytes += len(chunk)
        if read_bytes > FETCH_MAX_BYTES:
            raise ValueError('Response exceeds max size (5MB)')
        chunks.append(chunk)
    html_bytes = b''.join(chunks)

    # 字符集解码
    charset = 'utf-8'
    ctyp = resp.headers.get('Content-Type', '')
    m = re.search(r'charset=([\w\-]+)', ctyp, re.I)
    if m:
        charset = m.group(1)
    try:
        html = html_bytes.decode(charset, errors='replace')
    except LookupError:
        html = html_bytes.decode('utf-8', errors='replace')

    return html, resp.geturl()


# ===== HTML 解析与正文提取 =====

class ContentExtractor(HTMLParser):
    """DOM 树式 HTML 解析与正文评分。

    收集所有候选容器（article/main/section/div/body）的子树，
    按 (正文长度 + 段落数*30 + 标题数*40) / (1 + 链接密度*5) 评分。
    """

    NOISE_TAGS = {'script', 'style', 'noscript', 'iframe', 'form', 'button', 'svg', 'nav', 'header', 'footer', 'aside'}
    NOISE_CLASS_PATTERNS = re.compile(
        r'(?:^|[\s_-])(ads?|adsbygoogle|advert|comment|related|share|social|sidebar|menu|nav|promotion|newsletter|breadcrumb|pagination|popup|cookie|consent|subscribe|recommend)(?:[\s_-]|$)',
        re.I,
    )

    BLOCK_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'pre', 'td', 'th'}
    HEADING_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    CONTAINER_TAGS = {'article', 'main', 'section', 'div', 'body'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': '#root', 'attrs': {}, 'children': [], 'text': '', 'parent': None}
        self.stack = [self.root]
        self.title = ''
        self.description = ''
        self.og_title = ''
        self.og_description = ''
        self._in_title = False
        self._in_head = False
        self._capturing_meta = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == 'head':
            self._in_head = True
            return
        if tag == 'title' and self._in_head:
            self._in_title = True
            return
        if tag == 'meta':
            prop = (attrs_d.get('property') or attrs_d.get('name') or '').lower()
            content = attrs_d.get('content') or ''
            if prop == 'og:title':
                self.og_title = content
            elif prop == 'og:description':
                self.og_description = content
            elif prop == 'description':
                self.description = content
            return

        if tag in self.NOISE_TAGS:
            # 用占位节点不收集文本
            node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': None, 'parent': self.stack[-1]}
            self.stack.append(node)
            return

        cls = attrs_d.get('class', '') or ''
        if self.NOISE_CLASS_PATTERNS.search(cls):
            node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': None, 'parent': self.stack[-1]}
            self.stack.append(node)
            return

        node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': '', 'parent': self.stack[-1]}
        self.stack[-1]['children'].append(node)
        self.stack.append(node)

    def handle_endtag(self, tag):
        if tag == 'head':
            self._in_head = False
            return
        if tag == 'title' and self._in_title:
            self._in_title = False
            return
        # 找到栈上最近的同标签节点并弹出
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        node = self.stack[-1]
        if node.get('text') is None:
            return
        # 跳过纯空白文本节点（HTML 格式化缩进/换行产物）
        # 但保留含有实际内容的文本（包括其周围的空格，用于内联元素间距）
        stripped = data.strip()
        if not stripped:
            return
        node['children'].append({
            'tag': '#text', 'attrs': {}, 'children': [],
            'text': data, 'parent': node,
        })

    # ----- 后处理 -----

    def get_title(self):
        t = (self.og_title or self.title or '').strip()
        return t

    def get_description(self):
        return (self.og_description or self.description or '').strip()

    def _container_text_len(self, node):
        if node.get('text') is None:
            return 0
        total = 0
        for c in node.get('children', []):
            if c['tag'] == '#text':
                total += len((c.get('text', '') or '').strip())
            else:
                total += self._container_text_len(c)
        return total

    def _count_blocks(self, node):
        if node.get('text') is None:
            return 0, 0, 0
        paras = 1 if node['tag'] == 'p' else 0
        headings = 1 if node['tag'] in self.HEADING_TAGS else 0
        links = 1 if node['tag'] == 'a' else 0
        for c in node.get('children', []):
            if c['tag'] == '#text':
                continue
            p, h, l = self._count_blocks(c)
            paras += p
            headings += h
            links += l
        return paras, headings, links

    def find_best_container(self):
        """遍历所有候选容器，返回评分最高的子树根节点。"""
        candidates = []

        def walk(node):
            for c in node['children']:
                if c.get('text') is None:
                    continue
                if c['tag'] in self.CONTAINER_TAGS:
                    candidates.append(c)
                walk(c)

        walk(self.root)
        if not candidates:
            return self.root

        best = None
        best_score = 0
        for c in candidates:
            text_len = self._container_text_len(c)
            if text_len < 200:
                continue
            paras, headings, links = self._count_blocks(c)
            link_density = links / (paras + 1)
            # 评分公式
            score = (text_len + paras * 30 + headings * 40) / (1 + link_density * 5)
            # article/main 加权
            if c['tag'] in ('article', 'main'):
                score *= 1.5
            if score > best_score:
                best_score = score
                best = c
        return best or self.root


# ===== HTML → Markdown 转换 =====

class MarkdownConverter(HTMLParser):
    """受控的 HTML→Markdown 转换器。

    支持：标题(h1-h6)、段落、粗体、斜体、链接、图片、有序/无序列表、
    引用、代码块、分隔线、基础表格。
    其他标签降级为纯文本。
    """

    INLINE_TAGS = {'a', 'strong', 'b', 'em', 'i', 'code', 'img', 'br'}

    def __init__(self, base_url=''):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.lines = []
        self.current_line = ''
        self.list_stack = []          # 每项 ('ul' | 'ol', counter)
        self.in_pre = False
        self.in_blockquote = False
        self.in_table = False
        self.table_rows = []

    def _emit(self, text):
        self.current_line += text

    def _end_line(self):
        if self.list_stack:
            indent = '  ' * (len(self.list_stack) - 1)
            marker = self.list_stack[-1]
            if marker[0] == 'ul':
                self.lines.append(indent + '- ' + self.current_line.lstrip())
            else:
                n = marker[1]
                self.lines.append(indent + '{}. '.format(n) + self.current_line.lstrip())
                self.list_stack[-1] = (marker[0], n + 1)
        else:
            self.lines.append(self.current_line)
        self.current_line = ''

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'iframe', 'svg'):
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            level = int(tag[1])
            if self.current_line.strip():
                self._end_line()
            self._emit('#' * level + ' ')
        elif tag == 'p':
            if self.current_line.strip():
                self._end_line()
        elif tag in ('strong', 'b'):
            self._emit('**')
        elif tag in ('em', 'i'):
            self._emit('*')
        elif tag == 'code' and not self.in_pre:
            self._emit('`')
        elif tag == 'a':
            href = attrs_d.get('href', '')
            if href and self.base_url:
                try:
                    href = urllib.parse.urljoin(self.base_url, href)
                except Exception:
                    pass
            self._pending_href = href
            self._emit('[')
        elif tag == 'img':
            src = attrs_d.get('src', '')
            alt = attrs_d.get('alt', '')
            if src and self.base_url:
                try:
                    src = urllib.parse.urljoin(self.base_url, src)
                except Exception:
                    pass
            self._emit('![{}]({})'.format(alt, src))
        elif tag == 'br':
            self._end_line()
        elif tag == 'hr':
            if self.current_line.strip():
                self._end_line()
            self.lines.append('---')
        elif tag == 'blockquote':
            if self.current_line.strip():
                self._end_line()
            self.in_blockquote = True
        elif tag == 'ul':
            if self.current_line.strip():
                self._end_line()
            self.list_stack.append(('ul', 0))
        elif tag == 'ol':
            if self.current_line.strip():
                self._end_line()
            self.list_stack.append(('ol', 1))
        elif tag == 'li':
            if self.current_line.strip():
                self._end_line()
        elif tag == 'pre':
            if self.current_line.strip():
                self._end_line()
            self.in_pre = True
            lang = ''
            cls = attrs_d.get('class', '')
            m = re.search(r'language-([\w\-]+)', cls)
            if m:
                lang = m.group(1)
            self.lines.append('```' + lang)
        elif tag == 'table':
            if self.current_line.strip():
                self._end_line()
            self.in_table = True
            self.table_rows = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'iframe', 'svg'):
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'):
            if self.current_line.strip():
                self._end_line()
            if not self.list_stack:
                self.lines.append('')
        elif tag in ('strong', 'b'):
            self._emit('**')
        elif tag in ('em', 'i'):
            self._emit('*')
        elif tag == 'code' and not self.in_pre:
            self._emit('`')
        elif tag == 'a':
            href = getattr(self, '_pending_href', '')
            self._emit(']({})'.format(href))
            self._pending_href = ''
        elif tag == 'blockquote':
            if self.current_line.strip():
                self._end_line()
            # 把刚产生的行加前缀
            if self.lines and not self.lines[-1].startswith('> '):
                self.lines[-1] = '> ' + self.lines[-1]
            self.in_blockquote = False
        elif tag in ('ul', 'ol'):
            if self.current_line.strip():
                self._end_line()
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack:
                self.lines.append('')
        elif tag == 'pre':
            if self.current_line.strip():
                self._end_line()
            self.lines.append('```')
            self.in_pre = False
            self.lines.append('')
        elif tag == 'table':
            self._render_table()
            self.in_table = False

    def handle_data(self, data):
        if self.in_pre:
            self.lines.append(data)
        else:
            # 折叠多余空白
            text = re.sub(r'\s+', ' ', data)
            self._emit(text)

    def _render_table(self):
        if not self.table_rows:
            return
        # 简化处理：管道分隔
        rows = self.table_rows
        if rows:
            cols = max(len(r) for r in rows)
            for i, row in enumerate(rows):
                row_padded = row + [''] * (cols - len(row))
                self.lines.append('| ' + ' | '.join(row_padded) + ' |')
                if i == 0:
                    self.lines.append('| ' + ' | '.join(['---'] * cols) + ' |')
            self.lines.append('')

    def get_markdown(self):
        if self.current_line.strip():
            self._end_line()
        # 合并连续空行
        out = '\n'.join(self.lines)
        out = re.sub(r'\n{3,}', '\n\n', out)
        return out.strip() + '\n'


def html_to_markdown(container_node, base_url=''):
    """遍历容器节点，序列化为 Markdown。

    文本存为 #text 子节点，保留与内联元素的正确顺序。
    """
    if not container_node:
        return ''
    converter = MarkdownConverter(base_url=base_url)

    def serialize(node):
        if node.get('text') is None:
            return
        tag = node['tag']
        attrs = node.get('attrs', {})

        if tag == '#root':
            for c in node['children']:
                serialize(c)
            return

        if tag == '#text':
            text = node.get('text', '')
            if text:
                converter.handle_data(text)
            return

        converter.handle_starttag(tag, [(k, v) for k, v in attrs.items()])
        # 按子节点顺序递归，#text 节点和元素节点交错排列
        for c in node['children']:
            serialize(c)
        converter.handle_endtag(tag)

    serialize(container_node)
    return converter.get_markdown()


def extract_content(html, base_url=''):
    """主提取入口。返回 (title, description, markdown)。"""
    parser = ContentExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    title = parser.get_title()
    description = parser.get_description()

    best = parser.find_best_container()
    md = html_to_markdown(best, base_url)

    # 整理：在开头加 H1 标题（如果没有）
    if title and not md.lstrip().startswith('# '):
        md = '# {}\n\n{}'.format(title, md)

    # 截断保护
    if len(md) > 80000:
        md = md[:80000] + '\n\n<!-- 内容已截断 -->\n'

    return title, description, md


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


def set_bookmark_tags(conn, bookmark_id, tag_names):
    """替换某书签的全部标签关联。"""
    conn.execute('DELETE FROM bookmark_tags WHERE bookmark_id = ?', (bookmark_id,))
    seen = set()
    for raw in tag_names or []:
        name = (str(raw) or '').strip()
        if not name:
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

    if not re.match(r'^https?://', url, re.I):
        return None, 'invalid_url', None

    # 宽松规范化：只处理 scheme/host 大小写和去 fragment，不做 DNS 检查
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return None, 'invalid_url', None
    if u.scheme not in ('http', 'https'):
        return None, 'invalid_url', None
    host = (u.hostname or '').lower()
    if not host:
        return None, 'invalid_url', None
    port = u.port
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
    allowed = {'title', 'category', 'description', 'markdown', 'status', 'error', 'url'}
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
    result = []
    for r in rows:
        tags = get_bookmark_tags(conn, r['id'])
        result.append(serialize_bookmark(r, tags))
    return result


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
    result = []
    for r in rows:
        result.append(serialize_bookmark(r, get_bookmark_tags(conn, r['id'])))
    return result


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


# ===== 后台抓取任务 =====

def fetch_and_update(bookmark_id, url):
    """后台抓取并更新书签。失败不删除，仅更新 status=failed。

    注意：不覆盖 title，避免与用户编辑产生时序竞态——
    抓取是异步的，可能在用户 PUT 编辑后才完成，会冲掉用户改的标题。
    如果原 title 为 hostname 兜底（等于 hostname 或为空），则用抓取的真实标题替换。
    """
    conn = db_conn()
    try:
        html, final_url = fetch_html(url)
        title, description, markdown = extract_content(html, base_url=final_url)

        # 仅当原 title 是兜底值（等于 hostname 或为空）时才用抓取的标题覆盖
        row = conn.execute('SELECT title, hostname FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
        patch = {
            'description': description or '',
            'markdown': markdown or '',
            'status': 'saved',
            'error': '',
        }
        if row:
            current_title = (row['title'] or '').strip()
            hostname = (row['hostname'] or '').strip()
            if not current_title or current_title == hostname:
                patch['title'] = title or current_title
        update_bookmark(conn, bookmark_id, patch)
    except Exception as e:
        update_bookmark(conn, bookmark_id, {
            'status': 'failed',
            'error': str(e)[:500],
        })
    finally:
        conn.close()


# ===== HTTP Handler =====

class BookmarkHandler(BaseHTTPRequestHandler):
    server_version = 'BookmarkHub/1.0'

    def log_message(self, fmt, *args):
        # 简化日志
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt % args))

    # ----- 通用响应 -----

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, file_path, mime):
        try:
            with open(file_path, 'rb') as f:
                body = f.read()
        except FileNotFoundError:
            self.send_error(404, 'Not Found')
            return
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return {}

    # ----- 路由 -----

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API
        if path.startswith('/api/'):
            return self._route_get(path, parsed.query)

        # 静态文件
        if path == '/' or path == '':
            return self._send_static(os.path.join(STATIC_DIR, 'index.html'), 'text/html')
        if path == '/favicon.ico':
            return self.send_error(204)

        # 文件映射（防止路径穿越）
        rel = path.lstrip('/')
        if '..' in rel.split('/'):
            return self.send_error(403)
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(STATIC_DIR):
            return self.send_error(403)
        if os.path.isfile(target):
            mime = self._guess_mime(target)
            return self._send_static(target, mime)
        self.send_error(404, 'Not Found')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/'):
            return self._route_post(path)
        self.send_error(404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/'):
            return self._route_put(path)
        self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/'):
            return self._route_delete(path)
        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ----- GET 路由 -----

    def _route_get(self, path, query):
        conn = db_conn()
        try:
            if path == '/api/bookmarks':
                qs = urllib.parse.parse_qs(query)
                q = (qs.get('q') or [''])[0]
                cat = (qs.get('category') or ['all'])[0]
                tag = (qs.get('tag') or [None])[0]
                if q or (cat and cat != 'all') or tag:
                    data = search_bookmarks(conn, q, cat, tag)
                else:
                    data = list_bookmarks(conn)
                return self._send_json(200, {'bookmarks': data})

            m = re.match(r'^/api/bookmarks/(\d+)$', path)
            if m:
                bid = int(m.group(1))
                b = get_bookmark(conn, bid)
                if not b:
                    return self._send_json(404, {'error': 'Not found'})
                return self._send_json(200, {'bookmark': b})

            if path == '/api/tags':
                return self._send_json(200, {'tags': list_tags(conn)})

            if path == '/api/stats':
                return self._send_json(200, {'counts': category_counts(conn)})

            return self._send_json(404, {'error': 'Unknown endpoint'})
        finally:
            conn.close()

    # ----- POST 路由 -----

    def _route_post(self, path):
        conn = db_conn()
        try:
            if path == '/api/bookmarks':
                body = self._read_body()
                bm, err, existing = create_bookmark(conn, body)
                if err == 'duplicate':
                    return self._send_json(409, {
                        'error': 'URL already exists',
                        'bookmark': existing,
                    })
                if err == 'invalid_url':
                    return self._send_json(400, {'error': 'Invalid URL'})

                # 后台启动抓取
                t = threading.Thread(
                    target=fetch_and_update,
                    args=(bm['id'], bm['url']),
                    daemon=True
                )
                t.start()
                return self._send_json(201, {'bookmark': bm})

            if path == '/api/extract':
                body = self._read_body()
                url = (body.get('url') or '').strip()
                canonical, host = canonicalize_url(url)
                if not canonical:
                    return self._send_json(400, {'error': 'Invalid URL'})
                try:
                    html, final_url = fetch_html(canonical)
                    title, description, markdown = extract_content(html, base_url=final_url)
                    return self._send_json(200, {
                        'success': True,
                        'title': title,
                        'description': description,
                        'markdown': markdown,
                        'final_url': final_url,
                    })
                except Exception as e:
                    return self._send_json(200, {
                        'success': False,
                        'error': str(e),
                    })

            if path == '/api/bookmarks/retry':
                body = self._read_body()
                bid = body.get('id')
                b = get_bookmark(conn, bid)
                if not b:
                    return self._send_json(404, {'error': 'Not found'})
                update_bookmark(conn, bid, {'status': 'pending', 'error': ''})
                t = threading.Thread(
                    target=fetch_and_update,
                    args=(bid, b['url']),
                    daemon=True
                )
                t.start()
                return self._send_json(200, {'ok': True})

            return self._send_json(404, {'error': 'Unknown endpoint'})
        finally:
            conn.close()

    # ----- PUT 路由 -----

    def _route_put(self, path):
        conn = db_conn()
        try:
            m = re.match(r'^/api/bookmarks/(\d+)$', path)
            if not m:
                return self._send_json(404, {'error': 'Unknown endpoint'})
            bid = int(m.group(1))
            body = self._read_body()
            # 如果包含 url，重新规范化
            if 'url' in body:
                canonical, host = canonicalize_url(body['url'])
                if not canonical:
                    return self._send_json(400, {'error': 'Invalid URL'})
                body['canonical_url'] = canonical
            updated = update_bookmark(conn, bid, body)
            if not updated:
                return self._send_json(404, {'error': 'Not found'})
            return self._send_json(200, {'bookmark': updated})
        finally:
            conn.close()

    # ----- DELETE 路由 -----

    def _route_delete(self, path):
        conn = db_conn()
        try:
            m = re.match(r'^/api/bookmarks/(\d+)$', path)
            if not m:
                return self._send_json(404, {'error': 'Unknown endpoint'})
            bid = int(m.group(1))
            ok = delete_bookmark(conn, bid)
            return self._send_json(200, {'ok': ok})
        finally:
            conn.close()

    @staticmethod
    def _guess_mime(path):
        ext = os.path.splitext(path)[1].lower()
        return {
            '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
            '.json': 'application/json', '.svg': 'image/svg+xml',
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.ico': 'image/x-icon',
            '.woff': 'font/woff', '.woff2': 'font/woff2',
            '.md': 'text/markdown',
        }.get(ext, 'application/octet-stream')


# ===== 启动 =====

def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), BookmarkHandler)
    print('=' * 60)
    print('  Bookmark Hub')
    print('  数据库: {}'.format(DB_PATH))
    print('  监听:   http://{}:{}/'.format('127.0.0.1' if HOST == '0.0.0.0' else HOST, PORT))
    print('  前端:   http://127.0.0.1:{}/'.format(PORT))
    print('  Ctrl+C 退出')
    print('=' * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在关闭...')
        server.shutdown()


if __name__ == '__main__':
    main()
