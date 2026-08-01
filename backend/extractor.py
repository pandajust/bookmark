# -*- coding: utf-8 -*-
"""内容提取、HTML→Markdown 转换、URL 规范化与 SSRF 防护。"""

import re
import socket
import ipaddress
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser

# 抓取限制
FETCH_TIMEOUT = 15            # 单次请求超时（秒）
FETCH_MAX_BYTES = 5 * 1024 * 1024   # 5MB
FETCH_MAX_REDIRECTS = 5
FETCH_USER_AGENT = 'BookmarkHub/1.0 (+https://github.com/local)'


# ===== URL 规范化与 SSRF 防护 =====

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
        self._in_pre = False
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

        if tag == 'pre':
            self._in_pre = True

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
        if tag == 'pre':
            self._in_pre = False
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
        # 但在 <pre> 中保留所有空白（代码缩进/换行是语义的一部分）
        stripped = data.strip()
        if not stripped and not self._in_pre:
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
        """遍历所有候选容器，返回评分最高的子树根节点。

        改进：如果最佳容器的兄弟节点也包含大量文本（>30%），
        则回溯到父级容器，避免多 section 文章丢失内容。
        """
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
            score = (text_len + paras * 30 + headings * 40) / (1 + link_density * 5)
            if c['tag'] in ('article', 'main'):
                score *= 1.5
            if score > best_score:
                best_score = score
                best = c

        if not best:
            # 所有候选都 < 200 字，选文本最多的
            best = max(candidates, key=lambda c: self._container_text_len(c))
            return best

        # 检查兄弟节点是否也有大量文本：如果兄弟文本量 > 最佳容器的 30%，
        # 说明内容分散在多个容器中，回溯到父级以包含全部内容
        parent = best.get('parent')
        if parent and parent != self.root:
            best_text = self._container_text_len(best)
            sibling_text = 0
            for child in parent.get('children', []):
                if child is not best and child.get('text') is not None:
                    sibling_text += self._container_text_len(child)
            if best_text > 0 and sibling_text > best_text * 0.3:
                return parent

        return best


# ===== HTML → Markdown 转换 =====

class MarkdownConverter(HTMLParser):
    """受控的 HTML→Markdown 转换器。

    支持：标题(h1-h6)、段落、粗体、斜体、链接、图片、有序/无序列表、
    引用、代码块、分隔线、基础表格。
    其他标签降级为纯文本。
    """

    INLINE_TAGS = {'a', 'strong', 'b', 'em', 'i', 'code', 'img', 'br'}

    # 图片懒加载属性名（按优先级排序）
    IMG_LAZY_ATTRS = ['data-src', 'data-original', 'data-lazy-src', 'data-actualsrc',
                      'data-lazy', 'data-url', 'data-srcset']
    # 无效图片 src 模式（1x1 占位图、data URI 占位等）
    IMG_INVALID_PATTERNS = re.compile(
        r'^(?:data:image/(?:gif|svg)\+xml|about:blank|\s*$)'
        r'|1x1|pixel|placeholder|blank\.gif|loading\.gif|lazy',
        re.I,
    )
    MAX_IMAGES = 10

    def __init__(self, base_url=''):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.lines = []
        self.current_line = ''
        self.list_stack = []          # 每项 ('ul' | 'ol', counter)
        self.in_pre = False
        self.pre_buffer = ''
        self.in_blockquote = False
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = ''
        self.in_cell = False
        self.image_count = 0

    def _emit(self, text):
        if self.in_cell:
            self.current_cell += text
        elif self.in_pre:
            self.pre_buffer += text
        else:
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
            src = self._extract_img_src(attrs_d)
            alt = attrs_d.get('alt', '') or attrs_d.get('title', '')
            if src and self.base_url:
                try:
                    src = urllib.parse.urljoin(self.base_url, src)
                except Exception:
                    pass
            if src and not self.IMG_INVALID_PATTERNS.search(src):
                if self.image_count < self.MAX_IMAGES:
                    self.image_count += 1
                    # 图片独占一行，确保不被段落合并吞掉
                    if self.current_line.strip():
                        self._end_line()
                    self._emit('![{}]({})'.format(alt, src))
                    self._end_line()
        elif tag == 'br':
            if self.in_cell:
                self.current_cell += ' '
            else:
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
            self.pre_buffer = ''
            lang = ''
            cls = attrs_d.get('class', '')
            m = re.search(r'language-([\w\-]+)', cls)
            if m:
                lang = m.group(1)
            self.lines.append('```' + lang)
        elif tag in ('div', 'section', 'article', 'main', 'figure', 'thead', 'tbody', 'tfoot'):
            if not self.in_cell and self.current_line.strip():
                self._end_line()
        elif tag == 'figcaption':
            if not self.in_cell and self.current_line.strip():
                self._end_line()
            self._emit('*')
        elif tag == 'table':
            if self.current_line.strip():
                self._end_line()
            self.in_table = True
            self.table_rows = []
        elif tag == 'tr':
            self.current_row = []
        elif tag in ('td', 'th'):
            self.current_cell = ''
            self.in_cell = True

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
            if self.pre_buffer:
                self.lines.append(self.pre_buffer.rstrip('\n'))
            self.lines.append('```')
            self.in_pre = False
            self.pre_buffer = ''
            self.lines.append('')
        elif tag == 'table':
            self._render_table()
            self.in_table = False
        elif tag in ('td', 'th'):
            self.current_row.append(self.current_cell.strip())
            self.in_cell = False
        elif tag == 'tr':
            if self.current_row:
                self.table_rows.append(self.current_row)
        elif tag == 'figcaption':
            self._emit('*')
            if not self.in_cell:
                self._end_line()
        elif tag in ('div', 'section', 'article', 'main', 'figure', 'thead', 'tbody', 'tfoot'):
            if not self.in_cell and self.current_line.strip():
                self._end_line()

    def handle_data(self, data):
        if self.in_pre:
            self.pre_buffer += data
        else:
            # 折叠多余空白
            text = re.sub(r'\s+', ' ', data)
            self._emit(text)

    def _extract_img_src(self, attrs_d):
        """从 img 标签属性中提取真实图片 URL。

        优先级：data-src 等懒加载属性 > src > srcset（取第一项）。
        过滤掉 1x1 占位图、data URI 占位图等无效值。
        """
        # 1. 检查懒加载属性（按优先级）
        for attr in self.IMG_LAZY_ATTRS:
            val = attrs_d.get(attr, '')
            if val and not self.IMG_INVALID_PATTERNS.search(val):
                # data-srcset 格式: "url1 1x, url2 2x"
                if attr == 'data-srcset' and ' ' in val:
                    val = val.split(',')[0].strip().split(' ')[0]
                return val

        # 2. 检查 srcset 属性
        srcset = attrs_d.get('srcset', '')
        if srcset and not self.IMG_INVALID_PATTERNS.search(srcset):
            first = srcset.split(',')[0].strip().split(' ')[0]
            if first and not self.IMG_INVALID_PATTERNS.search(first):
                return first

        # 3. 回退到 src
        src = attrs_d.get('src', '')
        if src and self.IMG_INVALID_PATTERNS.search(src):
            return ''
        return src

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

    # 将图片 URL 替换为后端代理 URL，避免浏览器跨域 ORB 拦截
    if base_url:
        def proxy_img_url(m):
            original = m.group(2)
            if not original or original.startswith('data:'):
                return m.group(0)
            # 确保是绝对 URL
            try:
                abs_url = urllib.parse.urljoin(base_url, original)
            except Exception:
                return m.group(0)
            encoded = urllib.parse.quote(abs_url, safe='')
            return '![{}]({})'.format(m.group(1), '/api/img?url=' + encoded)

        md = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', proxy_img_url, md)

    # 截断保护
    if len(md) > 80000:
        md = md[:80000] + '\n\n<!-- 内容已截断 -->\n'

    return title, description, md
