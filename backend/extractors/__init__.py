# -*- coding: utf-8 -*-
"""内容提取器包：站点感知 + 页面类型判定的策略分发。

入口函数 extract_content 根据 URL host 和页面特征选择提取策略：
- 微信公众号（mp.weixin.qq.com）→ weixin 策略
- B站（bilibili.com）→ video 策略（JSON 解析）
- 抖音（douyin.com）→ video 策略（JSON 解析）
- 通用文章/博客/新闻 → article 策略（增强评分算法）
- 门户首页（公司/学校）→ portal 策略（板块化摘要）

新增站点支持只需在 SITE_STRATEGIES 注册或新增策略模块，
无需改动 extract_content 分发逻辑。
"""

import urllib.parse

from .article import extract_article, detect_page_type
from .weixin import extract_weixin
from .video import extract_bilibili, extract_douyin
from .portal import extract_portal


# 站点 → 策略函数映射表
# 新增站点支持只需在此注册
SITE_STRATEGIES = [
    # (host 子串, 策略函数)
    ('mp.weixin.qq.com', extract_weixin),
    ('bilibili.com', extract_bilibili),
    ('douyin.com', extract_douyin),
    ('iesdouyin.com', extract_douyin),
]


def extract_content(html, base_url='', final_url=''):
    """主分发器：根据 URL 和页面特征选择提取策略。

    Args:
        html: HTML 原文
        base_url: 基础 URL（用于解析相对链接）
        final_url: 最终 URL（经重定向后，用于 host 判断）

    Returns:
        (title, description, markdown) 三元组
    """
    host = ''
    path = ''
    if final_url:
        try:
            parsed = urllib.parse.urlparse(final_url)
            host = (parsed.hostname or '').lower()
            path = parsed.path or ''
        except Exception:
            pass

    # 1. 站点特例分发
    for host_pattern, strategy_fn in SITE_STRATEGIES:
        if host_pattern in host:
            # B站专栏页（/read/cvXXX）走文章策略，而非视频策略
            if host_pattern == 'bilibili.com' and '/read/' in path:
                return extract_article(html, base_url)
            try:
                return strategy_fn(html, base_url, final_url)
            except Exception:
                # 站点策略失败，降级为通用 article
                break

    # 2. 通用页面类型判定
    page_type = detect_page_type(html, host)

    if page_type == 'portal':
        return extract_portal(html, base_url, final_url)

    # 3. 默认：文章提取（增强评分算法）
    return extract_article(html, base_url)
