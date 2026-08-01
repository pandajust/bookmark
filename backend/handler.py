# -*- coding: utf-8 -*-
"""HTTP 请求处理：路由分发、静态文件、API、图片代理、后台抓取。"""

import os
import sys
import json
import re
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from .db import (
    db_conn,
    create_bookmark,
    update_bookmark,
    delete_bookmark,
    get_bookmark,
    list_bookmarks,
    list_tags,
    search_bookmarks,
    category_counts,
)
from .extractor import (
    canonicalize_url,
    resolve_and_validate_host,
    fetch_html,
    SafeRedirectHandler,
    FETCH_USER_AGENT,
    FETCH_TIMEOUT,
    FETCH_MAX_BYTES,
)
from .extractors import extract_content

# 本文件位于 backend/ 子包内，静态文件（index.html/js/css）在项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = ROOT_DIR


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
        title, description, markdown = extract_content(html, base_url=final_url, final_url=final_url)

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

            if path == '/api/img':
                return self._serve_image_proxy(query)

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
                    title, description, markdown = extract_content(html, base_url=final_url, final_url=final_url)
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
            # 如果包含 url，重新规范化并同步 canonical_url / hostname
            if 'url' in body:
                canonical, host = canonicalize_url(body['url'])
                if not canonical:
                    return self._send_json(400, {'error': 'Invalid URL'})
                body['canonical_url'] = canonical
                if host:
                    body['hostname'] = host
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

    def _serve_image_proxy(self, query):
        """代理外部图片，避免浏览器跨域 ORB 拦截。"""
        qs = urllib.parse.parse_qs(query)
        url = (qs.get('url') or [''])[0]
        if not url:
            return self.send_error(400, 'Missing url parameter')

        canonical, host = canonicalize_url(url)
        if not canonical or not host:
            return self.send_error(400, 'Invalid url')
        if not resolve_and_validate_host(host):
            return self.send_error(403, 'Blocked host')

        try:
            opener = urllib.request.build_opener(SafeRedirectHandler)
            req = urllib.request.Request(canonical, headers={
                'User-Agent': FETCH_USER_AGENT,
                'Accept': 'image/*,*/*;q=0.8',
            }, method='GET')
            resp = opener.open(req, timeout=FETCH_TIMEOUT)

            ctype = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
            if not ctype.startswith('image/'):
                ctype = 'image/jpeg'

            data = resp.read(FETCH_MAX_BYTES)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_error(502, 'Image fetch failed')
