# -*- coding: utf-8 -*-
"""微信公众号文章提取策略。

利用稳定的容器锚点（#js_content / .rich_media_content）定位正文，
过滤赞赏、二维码、推荐阅读等微信特有噪声。
"""

import re
import urllib.parse

from .parser import ContentExtractor
from .markdown import html_to_markdown
from .base import clean_text


# 微信正文容器选择器（优先级从高到低）
WEIXIN_CONTAINER_SELECTORS = [
    ('id', 'js_content'),
    ('class', 'rich_media_content'),
]

# 微信特有噪声 class（补充 base.py 的通用词表）
WEIXIN_NOISE_PATTERNS = re.compile(
    r'(?:qr_code_pc|reward_area|like_area|weapp_card|vote_area|'
    r'rich_media_tool|related_articles|comment_wrp|pay_for_reading|'
    r'mp_profile_card|profile_container|qr_code_pc_wrap|reward_qrcode|'
    r'link_share_app|js_like_container|js_tags)',
    re.I,
)

# 微信错误页关键词（链接失效/被反爬时返回"参数错误"等）
WEIXIN_ERROR_KEYWORDS = re.compile(
    r'参数错误|页面不存在|已被删除|已被作者删除|该内容已被发布者删除|访问频繁|系统繁忙'
)


def _is_weixin_noise(attrs_d):
    """检查是否是微信特有的噪声元素。"""
    cls = (attrs_d.get('class', '') or '').lower()
    elem_id = (attrs_d.get('id', '') or '').lower()
    combined = cls + ' ' + elem_id
    return bool(WEIXIN_NOISE_PATTERNS.search(combined))


def _find_weixin_container(parser):
    """通过微信专用选择器查找正文容器。"""
    def walk(node):
        for c in node['children']:
            if c.get('text') is None:
                continue
            attrs = c.get('attrs', {})
            for attr_key, attr_val in WEIXIN_CONTAINER_SELECTORS:
                # 防御属性值显式为 None 的情况（与 parser.py 一致）
                if (attrs.get(attr_key) or '').lower() == attr_val.lower():
                    return c
            result = walk(c)
            if result:
                return result
        return None

    return walk(parser.root)


def _is_weixin_error_page(md, title):
    """检测微信错误页（链接失效/被反爬时返回"参数错误"等）。

    判定条件：
    - markdown 为空
    - 标题为空（微信文章必有标题，空标题通常意味着页面结构异常）
    - 内容很短（<50字符）且包含错误关键词
    """
    if not md or not md.strip():
        return True
    stripped = md.strip()
    # 标题为空：微信文章必有标题，空标题通常意味着页面异常；同时要求内容短以避免误伤
    if not title or not title.strip():
        return len(stripped) < 50
    # 内容很短且包含错误关键词
    if len(stripped) < 50 and WEIXIN_ERROR_KEYWORDS.search(stripped):
        return True
    return False


def extract_weixin(html, base_url='', final_url=''):
    """微信公众号文章提取。返回 (title, description, markdown)。"""
    parser = ContentExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    title = parser.get_title()
    description = parser.get_description()

    # 优先用微信专用容器锚点
    container = _find_weixin_container(parser)
    if not container:
        # 兜底用通用评分算法
        container = parser.find_best_container()

    md = html_to_markdown(container, base_url)

    # 检测微信错误页（"参数错误"等），避免把错误页当作正文返回
    if _is_weixin_error_page(md, title):
        return (
            '微信文章无法访问',
            '文章可能已删除或链接失效',
            '# 微信文章无法访问\n\n该文章可能已被删除或链接失效。',
        )

    # 不强制加 H1
    if title and not re.match(r'^\s*#{1,6}\s', md):
        md = '# {}\n\n{}'.format(title, md)

    # 图片 URL 代理化（微信 mmbiz.qpic.cn 有 Referer 校验，必须走代理）
    md = _proxy_image_urls(md, base_url)

    # 截断保护
    if len(md) > 80000:
        md = md[:80000] + '\n\n<!-- 内容已截断 -->\n'

    return title, description, md


def _proxy_image_urls(md, base_url):
    """将图片 URL 替换为后端代理 URL。"""
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
