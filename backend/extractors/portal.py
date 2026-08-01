# -*- coding: utf-8 -*-
"""门户首页（公司/学校官网）板块化摘要策略。

门户首页无单一"正文"，内容分散在通知公告、新闻动态等板块中。
本策略提取各板块的标题+链接，生成结构化摘要。
"""

import re
import urllib.parse

from .base import is_noise_attrs, clean_text


# 板块关键词（匹配标题/链接文本，识别板块归属）
SECTION_KEYWORDS = {
    'news': ['新闻', '动态', '资讯', 'news'],
    'notice': ['通知', '公告', 'notice', 'announce'],
    'about': ['关于', '简介', 'about', 'overview'],
    'academic': ['学术', '科研', '研究', 'academic', 'research'],
    'service': ['服务', '办事', 'service'],
}

# 板块显示名称
SECTION_LABELS = {
    'news': '新闻动态',
    'notice': '通知公告',
    'about': '关于我们',
    'academic': '学术科研',
    'service': '服务指南',
}


def extract_portal(html, base_url='', final_url=''):
    """门户首页板块化摘要。返回 (title, description, markdown)。"""
    # 提取页面标题和描述
    title = _extract_title(html)
    description = _extract_description(html)

    # 提取所有带文本的链接
    links = _extract_links(html, base_url)

    # 按板块分类
    sections = _classify_links(links)

    # 生成 Markdown
    md_lines = ['# ' + title]

    if description:
        md_lines.append('')
        md_lines.append('> ' + description)

    has_content = False
    for section_key in ['notice', 'news', 'academic', 'service', 'about']:
        items = sections.get(section_key, [])
        if not items:
            continue
        has_content = True
        label = SECTION_LABELS.get(section_key, section_key)
        md_lines.append('')
        md_lines.append('## ' + label)
        for link_title, link_url in items[:15]:  # 每板块最多 15 条
            md_lines.append('- [{}]({})'.format(link_title, link_url))

    if not has_content and links:
        # 未分类到板块，直接列出有意义的链接
        md_lines.append('')
        md_lines.append('## 页面链接')
        for link_title, link_url in links[:20]:
            md_lines.append('- [{}]({})'.format(link_title, link_url))

    md = '\n'.join(md_lines) + '\n'

    # 截断保护
    if len(md) > 80000:
        md = md[:80000] + '\n\n<!-- 内容已截断 -->\n'

    return title, description, md


def _extract_title(html):
    """提取页面标题。"""
    # og:title 优先
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # <title> 标签
    m = re.search(r'<title>(.*?)</title>', html, re.I | re.DOTALL)
    if m:
        return clean_text(m.group(1).strip())
    return '门户首页'


def _extract_description(html):
    """提取页面描述。"""
    m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return ''


def _extract_links(html, base_url):
    """提取所有带文本的链接，返回 [(text, url), ...]。"""
    # 移除 script/style 内容，避免误提取
    cleaned = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.I | re.DOTALL)
    cleaned = re.sub(r'<style\b[^>]*>.*?</style>', '', cleaned, flags=re.I | re.DOTALL)

    links = []
    seen = set()

    # 匹配 <a href="...">文本</a>
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', cleaned, re.I | re.DOTALL):
        attrs_str = m.group(1)
        inner = m.group(2)

        # 提取 href
        href_m = re.search(r'href=["\']([^"\']*)["\']', attrs_str, re.I)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue

        # 转绝对 URL
        try:
            url = urllib.parse.urljoin(base_url, href)
        except Exception:
            continue

        # 提取链接文本（去标签）
        text = re.sub(r'<[^>]+>', '', inner)
        text = clean_text(text).strip()
        if not text or len(text) < 2 or len(text) > 100:
            continue

        # 去重
        key = (text, url)
        if key in seen:
            continue
        seen.add(key)
        links.append((text, url))

    return links


def _classify_links(links):
    """将链接按板块分类。返回 {section_key: [(text, url), ...]}。"""
    sections = {}
    for text, url in links:
        matched = False
        text_lower = text.lower()
        for section_key, keywords in SECTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    sections.setdefault(section_key, []).append((text, url))
                    matched = True
                    break
            if matched:
                break
    return sections
