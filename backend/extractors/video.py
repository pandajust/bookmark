# -*- coding: utf-8 -*-
"""视频平台内容提取策略（B站 / 抖音）。

视频页核心内容不在可见 DOM 文本中，而在初始 HTML 内嵌的 JSON 数据里。
- B站：解析 window.__INITIAL_STATE__
- 抖音：解析 <script id="RENDER_DATA">（URL 编码的 JSON）
- 兜底：降级为 og:title / og:description 等 meta 标签
"""

import re
import json
import urllib.parse
import time


def extract_bilibili(html, base_url='', final_url=''):
    """B站视频页提取。返回 (title, description, markdown)。

    核心数据源：window.__INITIAL_STATE__（原始 JSON，非编码）。
    """
    video_data = _parse_bilibili_initial_state(html)

    if video_data:
        return _format_bilibili(video_data, base_url)

    # 兜底：meta 标签
    return _extract_meta_fallback(html, base_url, 'B站视频')


def _parse_bilibili_initial_state(html):
    """从 HTML 中提取并解析 __INITIAL_STATE__。"""
    # 正则提取：注意结尾是 ;(function 或 ;( 为自删除脚本
    m = re.search(
        r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;\s*\(',
        html,
        re.DOTALL,
    )
    if not m:
        # 备用正则：更宽松的匹配
        m = re.search(
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;',
            html,
            re.DOTALL,
        )
    if not m:
        return None

    try:
        state = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None

    # videoData 路径
    video_data = state.get('videoData') or state.get('video', {}).get('data') or {}
    if not video_data:
        return None

    # 统计数据
    stat = video_data.get('stat', {})
    owner = video_data.get('owner', {})

    return {
        'title': video_data.get('title', ''),
        'desc': video_data.get('desc', ''),
        'bvid': video_data.get('bvid', ''),
        'aid': video_data.get('aid', ''),
        'author': owner.get('name', ''),
        'author_id': owner.get('mid', ''),
        'pubdate': video_data.get('pubdate', 0),
        'cover': video_data.get('pic', ''),
        'duration': video_data.get('duration', 0),
        'tname': video_data.get('tname', ''),
        'view': stat.get('view', 0),
        'danmaku': stat.get('danmaku', 0),
        'reply': stat.get('reply', 0),
        'favorite': stat.get('favorite', 0),
        'coin': stat.get('coin', 0),
        'like': stat.get('like', 0),
    }


def _format_bilibili(data, base_url):
    """将B站视频数据格式化为 Markdown。"""
    title = data.get('title', 'B站视频')
    desc = data.get('desc', '')
    author = data.get('author', '')
    pubdate = data.get('pubdate', 0)
    cover = data.get('cover', '')
    tname = data.get('tname', '')

    # 格式化发布时间
    date_str = ''
    if pubdate:
        try:
            date_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(pubdate))
        except Exception:
            date_str = ''

    # 构建元信息行
    meta_parts = []
    if author:
        meta_parts.append('**UP主**: {}'.format(author))
    if date_str:
        meta_parts.append('**发布时间**: {}'.format(date_str))
    if tname:
        meta_parts.append('**分区**: {}'.format(tname))

    # 统计信息
    stat_parts = []
    if data.get('view'):
        stat_parts.append('播放 {}'.format(data['view']))
    if data.get('like'):
        stat_parts.append('点赞 {}'.format(data['like']))
    if data.get('coin'):
        stat_parts.append('投币 {}'.format(data['coin']))
    if data.get('favorite'):
        stat_parts.append('收藏 {}'.format(data['favorite']))
    if data.get('danmaku'):
        stat_parts.append('弹幕 {}'.format(data['danmaku']))

    lines = ['# ' + title]

    if meta_parts:
        lines.append('')
        lines.extend(meta_parts)

    if stat_parts:
        lines.append('')
        lines.append('> ' + ' | '.join(stat_parts))

    # 封面图（代理化）
    if cover:
        cover_url = _proxy_single_url(cover, base_url)
        lines.append('')
        lines.append('![封面]({})'.format(cover_url))

    # 简介
    if desc:
        lines.append('')
        lines.append(desc)

    # 视频链接
    bvid = data.get('bvid', '')
    if bvid:
        lines.append('')
        lines.append('**视频链接**: https://www.bilibili.com/video/{}'.format(bvid))

    md = '\n'.join(lines) + '\n'
    description = (desc or '')[:200]

    return title, description, md


def extract_douyin(html, base_url='', final_url=''):
    """抖音视频页提取。返回 (title, description, markdown)。

    核心数据源：<script id="RENDER_DATA">（URL 编码的 JSON）。
    """
    video_data = _parse_douyin_render_data(html)

    if video_data:
        return _format_douyin(video_data, base_url)

    # 备用：_ROUTER_DATA
    video_data = _parse_douyin_router_data(html)
    if video_data:
        return _format_douyin(video_data, base_url)

    # 兜底：meta 标签
    return _extract_meta_fallback(html, base_url, '抖音视频')


def _parse_douyin_render_data(html):
    """从 HTML 中提取并解码 RENDER_DATA。"""
    m = re.search(
        r'<script\s+id="RENDER_DATA"\s*[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    raw = m.group(1).strip()
    if not raw:
        return None

    # RENDER_DATA 是 URL 编码的 JSON
    try:
        decoded = urllib.parse.unquote(raw)
        data = json.loads(decoded)
    except (json.JSONDecodeError, ValueError):
        return None

    # 在嵌套结构中查找视频数据（路径随版本变化，多路径尝试）
    return _locate_douyin_video(data)


def _parse_douyin_router_data(html):
    """从 HTML 中提取 _ROUTER_DATA。"""
    m = re.search(
        r'window\._ROUTER_DATA\s*=\s*(\{.+?\})\s*;',
        html,
        re.DOTALL,
    )
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None

    return _locate_douyin_video(data)


def _locate_douyin_video(data):
    """在抖音 JSON 数据中定位视频节点（多路径尝试）。"""
    if not isinstance(data, dict):
        return None

    # 路径1：loaderData -> video_{id}
    loader_data = data.get('loaderData') or {}
    for key, val in loader_data.items():
        if key.startswith('video_') and isinstance(val, dict):
            return _extract_douyin_fields(val)

    # 路径2：递归搜索含 desc + authorInfo 的节点
    found = _deep_search_video(data)
    if found:
        return found

    return None


def _deep_search_video(data, depth=0):
    """递归搜索包含视频特征的节点。"""
    if depth > 5 or not isinstance(data, dict):
        return None

    # 视频节点特征：含 desc 或 awemeId 字段
    has_desc = 'desc' in data or 'descRaw' in data
    has_author = 'authorInfo' in data or 'author' in data
    has_id = 'awemeId' in data or 'aweme_id' in data or 'id' in data

    if (has_desc or has_id) and (has_author or has_id):
        return _extract_douyin_fields(data)

    for val in data.values():
        if isinstance(val, dict):
            result = _deep_search_video(val, depth + 1)
            if result:
                return result
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    result = _deep_search_video(item, depth + 1)
                    if result:
                        return result

    return None


def _extract_douyin_fields(node):
    """从抖音视频节点提取标准化字段。"""
    author_info = node.get('authorInfo') or node.get('author') or {}
    stats = node.get('stats') or node.get('statsData') or {}
    video = node.get('video') or {}

    # 解析话题标签
    tags = []
    text_extra = node.get('textExtra') or []
    for t in text_extra:
        if isinstance(t, dict):
            hashtag = t.get('hashtagName') or t.get('hashtag_name') or ''
            if hashtag:
                tags.append(hashtag)

    return {
        'desc': node.get('desc') or node.get('descRaw') or '',
        'author': author_info.get('nickname') or author_info.get('name') or '',
        'author_id': author_info.get('uid') or author_info.get('secUid') or '',
        'create_time': node.get('createTime') or node.get('create_time') or 0,
        'cover': video.get('cover') or video.get('originCover') or node.get('cover') or '',
        'duration': video.get('duration') or node.get('duration') or 0,
        'digg_count': stats.get('diggCount') or stats.get('digg_count') or 0,
        'comment_count': stats.get('commentCount') or stats.get('comment_count') or 0,
        'share_count': stats.get('shareCount') or stats.get('share_count') or 0,
        'play_count': stats.get('playCount') or stats.get('play_count') or 0,
        'aweme_id': node.get('awemeId') or node.get('aweme_id') or node.get('id') or '',
        'tags': tags,
    }


def _format_douyin(data, base_url):
    """将抖音视频数据格式化为 Markdown。"""
    desc = data.get('desc', '抖音视频')
    # 标题取描述的第一行或前 50 字
    title = desc.split('\n')[0][:50] if desc else '抖音视频'
    author = data.get('author', '')
    create_time = data.get('create_time', 0)
    cover = data.get('cover', '')
    tags = data.get('tags', [])

    date_str = ''
    if create_time:
        try:
            date_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(int(create_time)))
        except Exception:
            date_str = ''

    meta_parts = []
    if author:
        meta_parts.append('**作者**: {}'.format(author))
    if date_str:
        meta_parts.append('**发布时间**: {}'.format(date_str))

    stat_parts = []
    if data.get('digg_count'):
        stat_parts.append('点赞 {}'.format(data['digg_count']))
    if data.get('comment_count'):
        stat_parts.append('评论 {}'.format(data['comment_count']))
    if data.get('share_count'):
        stat_parts.append('分享 {}'.format(data['share_count']))

    lines = ['# ' + title]

    if meta_parts:
        lines.append('')
        lines.extend(meta_parts)

    if stat_parts:
        lines.append('')
        lines.append('> ' + ' | '.join(stat_parts))

    # 封面图
    if cover:
        cover_url = _proxy_single_url(cover, base_url)
        lines.append('')
        lines.append('![封面]({})'.format(cover_url))

    # 描述
    if desc:
        lines.append('')
        lines.append(desc)

    # 话题标签
    if tags:
        lines.append('')
        lines.append('**话题**: ' + ' '.join('#' + t for t in tags))

    md = '\n'.join(lines) + '\n'
    description = (desc or '')[:200]

    return title, description, md


def _proxy_single_url(url, base_url):
    """将单个图片 URL 转为代理 URL。"""
    if not url or url.startswith('data:'):
        return url
    try:
        abs_url = urllib.parse.urljoin(base_url or '', url)
    except Exception:
        return url
    encoded = urllib.parse.quote(abs_url, safe='')
    return '/api/img?url=' + encoded


def _extract_meta_fallback(html, base_url, default_title):
    """meta 标签兜底提取（当 JSON 解析失败时）。"""
    title = ''
    description = ''
    image = ''

    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html, re.I)
    if m:
        title = m.group(1)
    m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html, re.I)
    if m:
        description = m.group(1)
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html, re.I)
    if m:
        image = m.group(1)

    if not title:
        m = re.search(r'<title>(.*?)</title>', html, re.I | re.DOTALL)
        if m:
            title = m.group(1).strip()

    title = title or default_title

    lines = ['# ' + title]
    if description:
        lines.append('')
        lines.append(description)
    if image:
        img_url = _proxy_single_url(image, base_url)
        lines.append('')
        lines.append('![封面]({})'.format(img_url))
    lines.append('')
    lines.append('> 视频内容无法提取，仅保存元信息。')

    md = '\n'.join(lines) + '\n'
    return title, description, md
