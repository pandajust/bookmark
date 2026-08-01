# -*- coding: utf-8 -*-
"""网络层：URL 规范化、SSRF 防护、HTTP 抓取。

内容提取逻辑已迁移至 backend.extractors 子包。
本模块只负责"把 HTML 安全地取回来"。
"""

import re
import socket
import ipaddress
import gzip
import zlib
import urllib.parse
import urllib.request
import urllib.error

from .extractors.base import detect_charset

# 抓取限制
FETCH_TIMEOUT = 15                       # 单次请求超时（秒）
FETCH_MAX_BYTES = 5 * 1024 * 1024        # 5MB
FETCH_MAX_REDIRECTS = 5
FETCH_USER_AGENT = 'BookmarkHub/1.0 (+https://github.com/local)'


# ===== URL 规范化 =====

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


# ===== SSRF 防护 =====

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
    """安全抓取 HTML，返回 (html, final_url) 或抛出异常。

    charset 检测优先级：HTTP Content-Type > <meta charset> > utf-8。
    """
    canonical, host = canonicalize_url(url)
    if not canonical:
        raise ValueError('Invalid URL')
    if not resolve_and_validate_host(host):
        raise ValueError('Host not public or not resolvable: ' + host)

    opener = urllib.request.build_opener(SafeRedirectHandler)

    req = urllib.request.Request(
        canonical,
        headers={
            'User-Agent': FETCH_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            # 只声明接受 gzip/deflate，避免服务器返回 brotli（Python 标准库不支持）
            'Accept-Encoding': 'gzip, deflate',
        },
        method='GET',
    )

    resp = opener.open(req, timeout=FETCH_TIMEOUT)
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

    # 解压：根据 Content-Encoding 头处理 gzip/deflate
    content_encoding = (resp.headers.get('Content-Encoding') or '').lower().strip()
    if content_encoding == 'gzip':
        try:
            html_bytes = gzip.decompress(html_bytes)
        except Exception:
            pass  # 解压失败则用原始数据
    elif content_encoding == 'deflate':
        try:
            html_bytes = zlib.decompress(html_bytes)
        except Exception:
            # 部分 deflate 流缺少 zlib 头，尝试 raw deflate
            try:
                html_bytes = zlib.decompress(html_bytes, -zlib.MAX_WBITS)
            except Exception:
                pass

    # charset 检测（增强版：HTTP 头 > meta 标签 > utf-8）
    http_content_type = resp.headers.get('Content-Type', '')
    charset = detect_charset(html_bytes, http_content_type)
    try:
        html = html_bytes.decode(charset, errors='replace')
    except LookupError:
        html = html_bytes.decode('utf-8', errors='replace')

    return html, resp.geturl()
