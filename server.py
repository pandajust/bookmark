# -*- coding: utf-8 -*-
"""
Bookmark Hub - 后端服务（主入口）

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
from http.server import ThreadingHTTPServer

from backend.db import DB_PATH, init_db
from backend.handler import BookmarkHandler

HOST = '0.0.0.0'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


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
