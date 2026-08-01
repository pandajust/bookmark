# -*- coding: utf-8 -*-
"""文章/博客/新闻页提取策略。

增强版评分算法：id/class 白名单优先 + JSON-LD 解析 + 链接文本密度 + 不强制 H1。
"""

import re
import urllib.parse

from .parser import ContentExtractor
from .markdown import html_to_markdown
from .base import clean_text


def detect_page_type(html, host=''):
    """判定页面类型：article / portal / video。

    判定信号：
    - video: URL host 匹配视频平台
    - portal: <article> 数量少 + 链接密度高 + 无长文本容器
    - article: 默认
    """
    if host:
        if 'bilibili.com' in host or 'douyin.com' in host:
            return 'video'

    # 统计 <article> 标签数量
    article_count = len(re.findall(r'<article\b', html, re.I))

    # 统计 <a> 标签数量
    link_count = len(re.findall(r'<a\b', html, re.I))

    # 统计 <p> 标签数量
    p_count = len(re.findall(r'<p\b', html, re.I))

    # 门户首页特征：article 少、链接多、段落少
    if article_count <= 1 and p_count < 10 and link_count > 30:
        # 进一步检查是否有长文本块
        text_blocks = re.findall(r'>([^<]{100,})<', html)
        if len(text_blocks) < 3:
            return 'portal'

    return 'article'


def _extract_json_ld_metadata(json_ld_list):
    """从 JSON-LD 列表中提取作者、发布时间等元信息。"""
    author = ''
    date_published = ''
    for item in json_ld_list:
        if not isinstance(item, dict):
            continue
        # 支持 Article / NewsArticle / BlogPosting 等类型
        if not author:
            author_data = item.get('author') or item.get('creator') or {}
            if isinstance(author_data, dict):
                author = author_data.get('name', '')
            elif isinstance(author_data, str):
                author = author_data
        if not date_published:
            date_published = item.get('datePublished') or item.get('dateCreated') or ''
    return author, date_published


def extract_article(html, base_url=''):
    """文章页提取主入口。返回 (title, description, markdown)。"""
    parser = ContentExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    title = parser.get_title()
    description = parser.get_description()

    # JSON-LD 元信息
    json_ld = parser.get_json_ld()
    author, date_published = _extract_json_ld_metadata(json_ld)

    best = parser.find_best_container()
    md = html_to_markdown(best, base_url)

    # 不强制加 H1：仅当容器内无任何标题时才补
    if title and not re.match(r'^\s*#{1,6}\s', md):
        md = '# {}\n\n{}'.format(title, md)

    # 补充作者和发布时间（如果有）
    header_parts = []
    if author:
        header_parts.append('**作者**: {}'.format(author))
    if date_published:
        header_parts.append('**发布时间**: {}'.format(date_published))
    if header_parts:
        meta_line = '\n'.join(header_parts)
        # 插入到标题之后
        if md.startswith('# '):
            lines = md.split('\n', 2)
            if len(lines) >= 2:
                md = lines[0] + '\n\n' + meta_line + '\n\n' + (lines[2] if len(lines) > 2 else '')
            else:
                md = md + '\n\n' + meta_line
        else:
            md = meta_line + '\n\n' + md

    # 图片 URL 代理化
    md = _proxy_image_urls(md, base_url)

    # 截断保护
    if len(md) > 80000:
        md = md[:80000] + '\n\n<!-- 内容已截断 -->\n'

    return title, description, md


def _proxy_image_urls(md, base_url):
    """将图片 URL 替换为后端代理 URL，避免跨域问题。"""
    if not base_url:
        return md

    def proxy_img_url(m):
        original = m.group(2)
        if not original or original.startswith('data:'):
            return m.group(0)
        try:
            abs_url = urllib.parse.urljoin(base_url, original)
        except Exception:
            return m.group(0)
        encoded = urllib.parse.quote(abs_url, safe='')
        return '![{}]({})'.format(m.group(1), '/api/img?url=' + encoded)

    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', proxy_img_url, md)
