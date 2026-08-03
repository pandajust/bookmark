# -*- coding: utf-8 -*-
"""
Bookmark Hub - 桌面应用主入口

架构：
  - pywebview 提供原生桌面窗口（系统 WebView2 渲染前端，非外部浏览器）
  - Python ThreadingHTTPServer 后台线程提供静态文件、REST API、网页抓取
  - SQLite 保存收藏、Markdown 与标签

运行模式：
  打包后（frozen）：启动原生桌面窗口，关闭窗口即退出整个程序，无控制台黑框
  开发模式：python server.py 启动 HTTP 服务并打开系统浏览器，带控制台日志

开发模式启动：
  python server.py            # 默认 127.0.0.1:8765，自动打开浏览器
  python server.py 9000       # 自定义端口
  python server.py --no-open  # 不自动打开浏览器
"""

import os
import re
import sys
import time
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from backend.db import DB_PATH, DATA_DIR, init_db
from backend.handler import BookmarkHandler

# 是否为 PyInstaller 打包后的运行环境
IS_FROZEN = getattr(sys, 'frozen', False)

# 只允许本机访问，避免安全风险
HOST = '127.0.0.1'
PORT = 8765
AUTO_OPEN = True

# 开发模式下解析命令行参数：支持 [端口] [--no-open] 任意顺序
if not IS_FROZEN:
    for a in sys.argv[1:]:
        if a.isdigit():
            PORT = int(a)
        elif a.lower() in ('--no-open', '-n', '--no-browser'):
            AUTO_OPEN = False


def _find_free_port(start=8765, end=8790):
    """在指定范围内寻找可用端口，避免端口被占用导致启动失败。"""
    import socket
    for p in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, p))
                return p
        except OSError:
            continue
    return start  # 兜底，交给 ThreadingHTTPServer 抛错


def _open_browser_later(url, delay=0.8):
    """延迟打开浏览器，确保 HTTP Server 已启动（仅开发模式使用）。"""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Thread(target=_open, daemon=True)
    t.start()


def _start_server(port):
    """启动 HTTP 服务器（后台守护线程）。返回 server 实例。"""
    server = ThreadingHTTPServer((HOST, port), BookmarkHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def _sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', name or 'bookmark').strip()
    name = name.rstrip('. ')
    return name[:80] or 'bookmark'


class JsApi:
    """前端可通过 window.pywebview.api.xxx 调用的方法集。"""

    def save_markdown_dialog(self, suggested_name, markdown_content):
        """弹出系统保存文件对话框（优先 tkinter，失败再用 pywebview）。
        返回 { ok, path, dir, filename, error }，取消则返回 { ok:false, canceled:true }
        """
        fname = _sanitize_filename(suggested_name) + '.md'
        fpath = None
        err = None

        # 方案 1：tkinter.filedialog（Python 标准库，打包后稳定可用）
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            try:
                root.withdraw()
                root.attributes('-topmost', True)
                try:
                    root.after(0, lambda: root.attributes('-topmost', False))
                except Exception:
                    pass
                fpath = filedialog.asksaveasfilename(
                    title='导出 Markdown',
                    defaultextension='.md',
                    initialfile=fname,
                    initialdir=self._get_default_dir(),
                    filetypes=[('Markdown 文件', '*.md'), ('所有文件', '*.*')],
                )
            finally:
                try:
                    root.destroy()
                except Exception:
                    pass
        except Exception as e:
            err = 'tk: ' + str(e)
            fpath = None

        # 方案 2：pywebview 原生（兜底）
        if not fpath:
            try:
                import webview
                global window
                if window is not None:
                    result = window.create_file_dialog(
                        dialog_type=webview.SAVE_DIALOG,
                        directory=self._get_default_dir(),
                        file_name=fname,
                        save_filename=fname,
                        file_types=('Markdown 文件 (*.md)|*.md|所有文件 (*.*)|*.*',),
                    )
                    if result:
                        fpath = result if isinstance(result, str) else result[0]
            except Exception as e2:
                if not err:
                    err = 'pywebview: ' + str(e2)
                else:
                    err += '; pywebview: ' + str(e2)

        # 用户取消
        if not fpath:
            return {'ok': False, 'canceled': True}

        # 保证 .md 后缀
        try:
            if not fpath.lower().endswith('.md') and '.' not in os.path.basename(fpath):
                fpath += '.md'
            os.makedirs(os.path.dirname(fpath) or '.', exist_ok=True)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(markdown_content or '')
            return {
                'ok': True,
                'path': fpath,
                'dir': os.path.dirname(fpath),
                'filename': os.path.basename(fpath),
            }
        except Exception as e:
            return {'ok': False, 'error': '写入失败：' + str(e)}

    @staticmethod
    def _get_default_dir():
        """默认打开目录：桌面 → 下载 → 用户目录 → 当前目录。"""
        home = os.path.expanduser('~')
        for d in [
            os.path.join(home, 'Desktop'),
            os.path.join(home, '桌面'),
            os.path.join(home, 'Downloads'),
            os.path.join(home, '下载'),
        ]:
            if os.path.isdir(d):
                return d
        return home or os.getcwd()

    def open_folder_in_explorer(self, folder_path):
        """在资源管理器中打开指定文件夹。返回结果并包含路径用于 Toast 提示。"""
        try:
            if not folder_path or not os.path.isdir(folder_path):
                return {'ok': False, 'error': '路径不存在：' + str(folder_path)}
            if os.name == 'nt':
                os.startfile(folder_path)  # noqa: attr-defined
            elif sys.platform == 'darwin':
                os.system('open "{}"'.format(folder_path))
            else:
                os.system('xdg-open "{}"'.format(folder_path))
            return {'ok': True, 'dir': folder_path}
        except Exception as e:
            return {'ok': False, 'error': str(e)}


def _run_desktop(port):
    """桌面应用模式：pywebview 原生窗口。关闭窗口即退出。"""
    import webview
    global window

    front_url = 'http://{}:{}/'.format(HOST, port)
    server = _start_server(port)
    api = JsApi()

    # 创建原生桌面窗口，加载本地服务页面
    window = webview.create_window(
        title='Bookmark Hub — 书签管理器',
        url=front_url,
        width=1280,
        height=840,
        min_size=(960, 600),
        text_select=False,
        js_api=api,
    )

    def _on_closed():
        # 窗口关闭时停止服务器，确保进程干净退出
        try:
            server.shutdown()
        except Exception:
            pass

    window.events.closed += _on_closed

    # start() 阻塞直到所有窗口关闭
    try:
        webview.start()
    except Exception:
        # WebView2 运行时不可用时回退到系统浏览器
        try:
            webbrowser.open(front_url)
        except Exception:
            pass
        server.serve_forever()


def _run_dev(port):
    """开发模式：HTTP 服务器 + 控制台日志 + 可选打开浏览器。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db()
    server = ThreadingHTTPServer((HOST, port), BookmarkHandler)
    front_url = 'http://{}:{}/'.format(HOST, port)
    print('=' * 60)
    print('  Bookmark Hub  (书签管理器) — 开发模式')
    print('  数据库: {}'.format(DB_PATH))
    print('  访问地址: {}'.format(front_url))
    if AUTO_OPEN:
        print('  正在打开浏览器...（若未自动打开请手动复制上述地址）')
    print('  Ctrl+C 退出')
    print('=' * 60)
    if AUTO_OPEN:
        _open_browser_later(front_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在关闭...')
        server.shutdown()


def main():
    if IS_FROZEN:
        # 桌面应用模式：确保数据目录存在，寻找可用端口，启动原生窗口
        os.makedirs(DATA_DIR, exist_ok=True)
        init_db()
        port = _find_free_port()
        _run_desktop(port)
    else:
        _run_dev(PORT)


if __name__ == '__main__':
    main()
