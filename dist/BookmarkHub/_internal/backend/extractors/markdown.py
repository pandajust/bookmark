# -*- coding: utf-8 -*-
"""HTML → Markdown 转换器。

受控的 HTML→Markdown 转换，支持标题、段落、粗体、斜体、链接、图片、
有序/无序列表、引用、代码块、分隔线、基础表格。
第二阶段应用噪声过滤，剔除容器内的贴纸/浮层等噪声元素。
"""

import re
import urllib.parse
from html.parser import HTMLParser

from .base import is_noise_attrs, is_hidden_element, clean_text, filter_markdown_lines


class MarkdownConverter(HTMLParser):
    """HTML → Markdown 转换器。

    与 parser.ContentExtractor 解析的 DOM 树配合使用，
    也可独立解析 HTML 片段。
    """

    # 图片懒加载属性名（按优先级排序）
    IMG_LAZY_ATTRS = [
        'data-src', 'data-original', 'data-lazy-src', 'data-actualsrc',
        'data-lazy', 'data-url', 'data-srcset', 'data-gif-url',
    ]
    # 无效图片 src 模式（1x1 占位图、data URI 占位等）
    # 注意：移除了 'lazy' 关键词，避免误伤合法 URL 中含 lazy 的图片
    IMG_INVALID_PATTERNS = re.compile(
        r'^(?:data:image/(?:gif|svg)\+xml|about:blank|\s*$)'
        r'|1x1|pixel|placeholder|blank\.gif|loading\.gif',
        re.I,
    )
    MAX_IMAGES = 10

    def __init__(self, base_url=''):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.lines = []
        self.current_line = ''
        self.list_stack = []
        self.in_pre = False
        self.pre_buffer = ''
        self.in_blockquote = False
        self._bq_start = 0  # blockquote 起始行号
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = ''
        self.in_cell = False
        self.image_count = 0
        # 噪声跳过栈：遇到噪声元素时压栈，其子树不渲染
        self._skip_stack = []

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

        # 噪声过滤：第二阶段也剔除贴纸/浮层等噪声
        if self._skip_stack:
            if tag in ('script', 'style'):
                return
            self._skip_stack.append(tag)
            return
        if is_noise_attrs(attrs_d):
            self._skip_stack.append(tag)
            return
        # 隐藏元素过滤
        if is_hidden_element(attrs_d):
            self._skip_stack.append(tag)
            return

        if tag in ('script', 'style', 'noscript', 'iframe', 'svg'):
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            level = int(tag[1])
            if self.current_line.strip():
                self._end_line()
            # 列表内的标题不输出 ### 标记，避免 "- ### 标题" 污染
            if not self.list_stack:
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
            self._handle_img(attrs_d)
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
            self._bq_start = len(self.lines)
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

    def _handle_img(self, attrs_d):
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
                if self.current_line.strip():
                    self._end_line()
                self._emit('![{}]({})'.format(alt, src))
                self._end_line()

    def _extract_img_src(self, attrs_d):
        """从 img 标签属性中提取真实图片 URL。

        优先级：懒加载属性 > srcset > src。
        过滤 1x1 占位图、data URI 占位图，以及 width/height=1 的装饰图。
        """
        # 过滤 1x1 装饰图
        w = attrs_d.get('width', '')
        h = attrs_d.get('height', '')
        if w == '1' or h == '1':
            return ''

        # 1. 懒加载属性
        for attr in self.IMG_LAZY_ATTRS:
            val = attrs_d.get(attr, '')
            if val and not self.IMG_INVALID_PATTERNS.search(val):
                if attr in ('data-srcset', 'data-srcset') and ' ' in val:
                    val = val.split(',')[0].strip().split(' ')[0]
                return val

        # 2. srcset 属性
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

    def handle_endtag(self, tag):
        # 噪声跳过栈弹出
        if self._skip_stack:
            if tag == self._skip_stack[-1]:
                self._skip_stack.pop()
            return

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
            # 修复：对 blockquote 内所有行加前缀，而非仅最后一行
            for i in range(self._bq_start, len(self.lines)):
                if not self.lines[i].startswith('> '):
                    self.lines[i] = '> ' + self.lines[i]
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
        if self._skip_stack:
            return
        if self.in_pre:
            self.pre_buffer += data
        else:
            # 折叠空白 + 文本清理
            text = clean_text(re.sub(r'\s+', ' ', data))
            if text:
                self._emit(text)

    def _render_table(self):
        if not self.table_rows:
            return
        rows = self.table_rows
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
        out = '\n'.join(self.lines)
        out = clean_text(out)
        # 行级过滤：移除 JSON 配置行和装饰符号行
        out = filter_markdown_lines(out)
        # 合并连续空行
        out = re.sub(r'\n{3,}', '\n\n', out)

        # --- Markdown 噪声清理 ---
        # 辅助：从 s[start]='(' 起返回匹配 ')' 的位置（含），找不到返回 -1
        def _find_balanced_paren(s, start):
            depth = 0
            for j in range(start, len(s)):
                if s[j] == '(':
                    depth += 1
                elif s[j] == ')':
                    depth -= 1
                    if depth == 0:
                        return j
            return -1

        # 1. 脚注链接：[*](url) / [†](url) / [1](url) / [12](url) → 删除
        #    先用简单正则清理 URL 无圆括号的常见情况
        out = re.sub(r'\[[*†‡§¶#†‡]\]\([^)]*\)', '', out)
        out = re.sub(r'\[\d+\]\([^)]*\)', '', out)
        #    再用平衡匹配处理 URL 内含圆括号的脚注链接
        result = []
        i = 0
        n = len(out)
        while i < n:
            if out[i] == '[':
                bracket_end = out.find(']', i + 1)
                if bracket_end > 0 and bracket_end + 1 < n and out[bracket_end + 1] == '(':
                    paren_end = _find_balanced_paren(out, bracket_end + 1)
                    if paren_end > 0:
                        text = out[i + 1:bracket_end]
                        url = out[bracket_end + 2:paren_end]
                        # 脚注链接判定：文本是符号/短数字（≤3字符），且 URL 为短锚点
                        if len(text) <= 3 and (not url or len(url) < 30):
                            result.append('')
                            i = paren_end + 1
                            continue
            result.append(out[i])
            i += 1
        out = ''.join(result)

        # 2. 断裂链接 ](url) → 删除（缺少匹配的 [）
        #    使用平衡括号匹配，处理 URL 内含圆括号的情况
        #    仅当 ]( 之前无匹配的 [text] 结构时才删除
        cleaned = []
        i = 0
        n = len(out)
        while i < n:
            if out[i] == ']' and i + 1 < n and out[i + 1] == '(':
                paren_end = _find_balanced_paren(out, i + 1)
                if paren_end > 0:
                    # 向前查找是否有匹配的 [（到行首或前一个 ](url) 为止）
                    line_start = out.rfind('\n', 0, i) + 1
                    preceding = out[line_start:i]
                    # 去掉已处理的合法 [text](url) 段后，检查是否仍有未闭合 [
                    has_open_bracket = False
                    j = 0
                    while j < len(preceding):
                        if preceding[j] == '[':
                            # 检查这个 [ 是否有对应的 ](url) 或 ]( 后续
                            close_bracket = preceding.find(']', j + 1)
                            if close_bracket > 0:
                                # 有匹配的 ] ，且之后紧跟 ( 就是合法链接
                                if close_bracket + 1 < len(preceding) and preceding[close_bracket + 1] == '(':
                                    # 这是合法 [text](url)，略过这段
                                    # 找到其 URL 的闭合 )
                                    k = close_bracket + 2
                                    depth = 1
                                    while k < len(preceding) and depth > 0:
                                        if preceding[k] == '(':
                                            depth += 1
                                        elif preceding[k] == ')':
                                            depth -= 1
                                        k += 1
                                    if depth == 0:
                                        j = k
                                        continue
                                else:
                                    # 孤立 [text]，视为已被清理过的碎片
                                    pass
                            has_open_bracket = True
                            break
                        j += 1
                    if not has_open_bracket:
                        # 断裂链接，删除 ](url)
                        cleaned.append('')
                        i = paren_end + 1
                        continue
            cleaned.append(out[i])
            i += 1
        out = ''.join(cleaned)

        # 3. 孤立脚注标记 [*] / [†] / [1] / [12]（后非 ( ）→ 删除
        out = re.sub(r'\[[*†‡§¶#†‡]\](?!\()', '', out)
        out = re.sub(r'\[\d+\](?!\()', '', out)

        # 4. 列表项内的 ### 标记 → 移除
        out = re.sub(r'^(\s*[-*+]\s+)#{1,6}\s+', r'\1', out, flags=re.MULTILINE)

        # 5. 残留短脚注形式 [char/digit]（无 ( ）→ 删除
        out = re.sub(r'\[[*†‡§¶#†‡\d]+\]', '', out)

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
        for c in node['children']:
            serialize(c)
        converter.handle_endtag(tag)

    serialize(container_node)
    return converter.get_markdown()
