# -*- coding: utf-8 -*-
"""DOM 树解析与正文容器评分。

ContentExtractor 构建 DOM 树，收集 meta 信息，
通过文本密度、段落、标题、链接密度等信号评分选出最佳正文容器。
"""

import re
from html.parser import HTMLParser

from .base import (
    NOISE_TAGS,
    CONTAINER_TAGS,
    HEADING_TAGS,
    is_noise_attrs,
    is_hidden_element,
)


class ContentExtractor(HTMLParser):
    """DOM 树式 HTML 解析与正文评分。

    收集所有候选容器（article/main/section/div/body）的子树，
    按 (文本长度 + 段落数*25 + 标题数*35) / (1 + 链接文本密度*8) 评分。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': '#root', 'attrs': {}, 'children': [], 'text': '', 'parent': None}
        self.stack = [self.root]
        self.title = ''
        self.description = ''
        self.og_title = ''
        self.og_description = ''
        self.og_image = ''
        self._in_title = False
        self._in_head = False
        self._in_pre = False
        # JSON-LD 结构化数据
        self.json_ld_scripts = []
        self._in_json_ld = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)

        if tag == 'head':
            self._in_head = True
            return
        if tag == 'title' and self._in_head:
            self._in_title = True
            return
        if tag == 'meta':
            self._collect_meta(attrs_d)
            return

        # JSON-LD 结构化数据
        if tag == 'script' and attrs_d.get('type') == 'application/ld+json':
            self._in_json_ld = True
            return

        if tag in NOISE_TAGS:
            node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': None, 'parent': self.stack[-1]}
            self.stack.append(node)
            return

        # class/id 噪声过滤
        if is_noise_attrs(attrs_d):
            node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': None, 'parent': self.stack[-1]}
            self.stack.append(node)
            return

        # 隐藏元素过滤（display:none / visibility:hidden / opacity:0）
        if is_hidden_element(attrs_d):
            node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': None, 'parent': self.stack[-1]}
            self.stack.append(node)
            return

        if tag == 'pre':
            self._in_pre = True

        node = {'tag': tag, 'attrs': attrs_d, 'children': [], 'text': '', 'parent': self.stack[-1]}
        self.stack[-1]['children'].append(node)
        self.stack.append(node)

    def _collect_meta(self, attrs_d):
        prop = (attrs_d.get('property') or attrs_d.get('name') or '').lower()
        content = attrs_d.get('content') or ''
        if prop == 'og:title':
            self.og_title = content
        elif prop == 'og:description':
            self.og_description = content
        elif prop == 'og:image':
            self.og_image = content
        elif prop == 'description':
            self.description = content

    def handle_endtag(self, tag):
        if tag == 'head':
            self._in_head = False
            return
        if tag == 'title' and self._in_title:
            self._in_title = False
            return
        if tag == 'pre':
            self._in_pre = False
        if tag == 'script' and self._in_json_ld:
            self._in_json_ld = False
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
        if self._in_json_ld:
            self.json_ld_scripts.append(data)
            return
        node = self.stack[-1]
        if node.get('text') is None:
            return
        # 跳过纯空白文本节点，但在 <pre> 中保留
        stripped = data.strip()
        if not stripped and not self._in_pre:
            return
        node['children'].append({
            'tag': '#text', 'attrs': {}, 'children': [],
            'text': data, 'parent': node,
        })

    # ----- 后处理 -----

    def get_title(self):
        return (self.og_title or self.title or '').strip()

    def get_description(self):
        return (self.og_description or self.description or '').strip()

    def get_json_ld(self):
        """解析 JSON-LD 脚本，返回 dict 列表。"""
        import json
        results = []
        for raw in self.json_ld_scripts:
            try:
                data = json.loads(raw.strip())
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, ValueError):
                continue
        return results

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

    def _count_signals(self, node):
        """递归统计段落数、标题数、链接数、链接文本长度。"""
        if node.get('text') is None:
            return 0, 0, 0, 0
        paras = 1 if node['tag'] == 'p' else 0
        headings = 1 if node['tag'] in HEADING_TAGS else 0
        links = 1 if node['tag'] == 'a' else 0
        link_text = 0
        if node['tag'] == 'a':
            link_text = self._container_text_len(node)
        for c in node.get('children', []):
            if c['tag'] == '#text':
                continue
            p, h, l, lt = self._count_signals(c)
            paras += p
            headings += h
            links += l
            link_text += lt
        return paras, headings, links, link_text

    def _find_anchor_container(self):
        """通过 id/class 白名单查找正文容器，优先于评分。"""
        from .base import ARTICLE_CONTAINER_SELECTORS

        def walk(node):
            for c in node['children']:
                if c.get('text') is None:
                    continue
                for attr_key, attr_val in ARTICLE_CONTAINER_SELECTORS:
                    # 用 `or ''` 双重守卫：attrs 可能存在但属性值显式为 None（导致 .lower() 崩溃）
                    if (c.get('attrs', {}).get(attr_key) or '').lower() == attr_val.lower():
                        return c
                result = walk(c)
                if result:
                    return result
            return None

        return walk(self.root)

    def find_best_container(self):
        """遍历所有候选容器，返回评分最高的子树根节点。

        改进：
        1. 优先用 id/class 白名单锚点定位
        2. 链接密度改为"链接文本长度/容器文本长度"
        3. 动态文本阈值
        4. 兄弟节点文本 >30% 则回溯父级
        """
        # 1. 白名单锚点优先
        anchor = self._find_anchor_container()
        if anchor and self._container_text_len(anchor) > 50:
            return anchor

        # 2. 评分算法
        candidates = []

        def walk(node):
            for c in node['children']:
                if c.get('text') is None:
                    continue
                if c['tag'] in CONTAINER_TAGS:
                    candidates.append(c)
                walk(c)

        walk(self.root)
        if not candidates:
            return self.root

        # 动态阈值：取全文文本的 10%，最低 80 字
        total_text = self._container_text_len(self.root)
        min_text = max(80, min(200, total_text // 10))

        best = None
        best_score = 0
        for c in candidates:
            text_len = self._container_text_len(c)
            if text_len < min_text:
                continue
            paras, headings, links, link_text = self._count_signals(c)
            # 链接密度：链接文本占容器文本的比例
            link_density = link_text / max(text_len, 1)
            score = (text_len + paras * 25 + headings * 35) / (1 + link_density * 8)
            if c['tag'] in ('article', 'main'):
                score *= 1.5
            elif c['tag'] == 'section':
                score *= 1.2
            if score > best_score:
                best_score = score
                best = c

        if not best:
            best = max(candidates, key=lambda c: self._container_text_len(c))
            return best

        # 3. 兄弟节点文本 >30% 则回溯父级
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
