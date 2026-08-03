# -*- coding: utf-8 -*-
"""提取器公共工具：文本清理、噪声过滤、charset 检测。

所有提取策略模块共享的基础设施。
"""

import re


# ===== 文本清理（解决非文本符号问题）=====

# 零宽字符、BOM、软连字等不可见字符
INVISIBLE_CHARS = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]')
# ASCII 控制字符（保留 \t \n \r）
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# 连续空格/制表符（含 nbsp）
MULTI_SPACE = re.compile(r'[ \t\u00a0]{2,}')

# i18n 函数调用清理：gettext(`key`) / t('key') / i18n("key") → key
I18N_FUNC_RE = re.compile(r'(?:gettext|i18n|t)\(\s*[`\'"]([^`\'"]+)[`\'"]\s*\)')


def clean_text(text):
    """清理文本中的不可见字符和控制字符。

    - 移除零宽字符、BOM、软连字
    - 移除 ASCII 控制字符（保留 \\t \\n \\r）
    - nbsp 转普通空格
    - 折叠连续空格
    - 还原未解析的 i18n 函数调用（gettext(`date.months.3`) → date.months.3）
    """
    if not text:
        return text
    text = INVISIBLE_CHARS.sub('', text)
    text = CONTROL_CHARS.sub('', text)
    text = text.replace('\u00a0', ' ')
    text = MULTI_SPACE.sub(' ', text)
    text = I18N_FUNC_RE.sub(r'\1', text)
    return text


# ===== 噪声过滤（class + id 双维度）=====

# 噪声关键词：广告、交互贴纸、社交推荐、导航结构等
NOISE_KEYWORDS = [
    # 广告 / 推广
    r'ads?', r'advert', r'sponsor', r'promotion', r'promo',
    # 交互贴纸 / 浮层
    r'toast', r'badge', r'chip', r'bubble', r'float', r'sticky',
    r'tooltip', r'notice', r'alert', r'banner', r'widget', r'popup', r'modal',
    # 社交 / 推荐
    r'comment', r'related', r'share', r'social', r'recommend', r'reward',
    r'like_area', r'subscribe', r'newsletter', r'follow',
    # 导航 / 结构
    r'sidebar', r'menu', r'nav', r'breadcrumb', r'pagination', r'footer', r'header',
    # 其他
    r'cookie', r'consent', r'signup', r'login',
    # 微信专项
    r'qr_code', r'reward_area', r'weapp', r'vote_area',
    r'tool_area', r'related_articles', r'comment_wrp',
    r'pay_for_reading', r'profile_container', r'rich_media_tool',
]

# 编译为正则：匹配 class 或 id 中的噪声词（词边界为 _、-、空格、开头/结尾）
NOISE_PATTERN = re.compile(
    r'(?:^|[\s_\-])(' + '|'.join(NOISE_KEYWORDS) + r')(?:[\s_\-]|$)',
    re.I,
)


def is_noise_attrs(attrs):
    """判断元素属性是否属于噪声（检查 class 和 id）。"""
    cls = (attrs.get('class', '') or '').lower()
    elem_id = (attrs.get('id', '') or '').lower()
    combined = cls + ' ' + elem_id
    if not combined.strip():
        return False
    return bool(NOISE_PATTERN.search(combined))


# ===== 隐藏元素检测 =====

_HIDDEN_STYLE_RE = re.compile(
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0\b)',
    re.I,
)


def is_hidden_element(attrs):
    """检查元素是否通过 inline style 隐藏（display:none / visibility:hidden / opacity:0）。

    这些元素通常是 SPA 框架的配置数据容器或模板节点，内容不是正文。
    """
    style = (attrs.get('style', '') or '').strip()
    if not style:
        return False
    return bool(_HIDDEN_STYLE_RE.search(style))


# ===== Markdown 行级过滤 =====

# JSON 配置数据行（以 { 开头，含 "key": 模式）
_JSON_LINE_RE = re.compile(r'^\s*\{["\w]+\s*:')
# 纯装饰符号行（同一字符连续重复 10 次以上）
_DECORATIVE_LINE_RE = re.compile(r'^\s*([*_~\-=#>|])\1{9,}\s*$')
# 纯符号行（整行仅由装饰符号和空白组成，如 "**"、"* * *"、"[]()"）
_PURE_SYMBOL_LINE_RE = re.compile(r'^[\s*_~\-=#>|<\[\](){}\.+]+$')
# 合法水平分隔线（--- / *** / ___，3+ 同字符，允许空格）—— 纯符号行过滤时保留
_HR_LINE_RE = re.compile(r'^\s*([-*_])\s*\1\s*\1[\s\1]*$')
# 空文本链接 [](url) —— 文本为空，无论 URL 是什么都删除
_EMPTY_TEXT_LINK_RE = re.compile(r'\[\s*\]\([^)]*\)')
# 不可跳转链接 [text](javascript:...) / [text](#) / [text](void(...)) → 只保留 text
_NON_JUMPABLE_LINK_RE = re.compile(
    r'\[([^\]]+)\]\((?:javascript:[^)]*|#[^)]*|void\([^)]*\)|)\s*\)'
)
# 装饰符号碎片：方括号内以 * _ ~ 为主、夹杂短文本，如 [*** English*] [** 标题 **]
_DECORATIVE_BRACKET_RE = re.compile(r'\[[\s*_~\-]+[^\[\]]{0,20}[\s*_~\-]+\](?!\()')


def _clean_inline_noise(text):
    """清理行内非正文噪声：空链接、不可跳转链接、装饰碎片。"""
    if not text:
        return text
    # 1. 空文本链接 [](url) → 删除
    text = _EMPTY_TEXT_LINK_RE.sub('', text)
    # 2. 不可跳转链接 [text](javascript:;) / [text](#) / [text]() → 只保留 text
    text = _NON_JUMPABLE_LINK_RE.sub(r'\1', text)
    # 3. 装饰符号碎片 [*** 文本*] → 删除（不影响 [文本](url) 真正链接）
    text = _DECORATIVE_BRACKET_RE.sub('', text)
    # 4. 装饰符号碎片 [*] [**]（方括号内纯符号，且后接非 ( 的内容）
    text = re.sub(r'\[\*+\](?!\()', '', text)
    return text


def filter_markdown_lines(md):
    """过滤 Markdown 文本中的非正文行。

    - 移除 JSON 配置数据行
    - 移除纯装饰符号行（如 **********************）
    - 移除纯符号行（如 "**"、"* * *"）
    - 清理行内空链接、不可跳转链接、装饰符号碎片
    """
    if not md:
        return md
    # 先做行内清理（链接/碎片可能出现在任意行）
    md = _clean_inline_noise(md)
    lines = md.split('\n')
    filtered = []
    for line in lines:
        if _JSON_LINE_RE.match(line):
            continue
        if _DECORATIVE_LINE_RE.match(line):
            continue
        # 纯符号行（清完行内噪声后整行只剩符号/空白）→ 丢弃，避免空段落留白
        # 但保留合法水平分隔线 --- / *** / ___
        if _PURE_SYMBOL_LINE_RE.match(line) and not _HR_LINE_RE.match(line):
            continue
        filtered.append(line)
    return '\n'.join(filtered)


# ===== charset 检测 =====

def detect_charset(html_bytes, http_content_type):
    """检测 HTML 字符编码。

    优先级：HTTP Content-Type 头 > <meta charset> > <meta http-equiv> > utf-8
    """
    # 1. HTTP 头
    if http_content_type:
        m = re.search(r'charset=([\w\-]+)', http_content_type, re.I)
        if m:
            return m.group(1)

    # 2. <meta charset="...">
    # 只读前 4KB，避免全量解码
    head = html_bytes[:4096].decode('ascii', errors='ignore')
    m = re.search(r'<meta[^>]+charset=["\']?([\w\-]+)', head, re.I)
    if m:
        return m.group(1)

    # 3. 默认 utf-8
    return 'utf-8'


# ===== HTML 标签分类常量 =====

NOISE_TAGS = frozenset({
    'script', 'style', 'noscript', 'iframe', 'form', 'button',
    'svg', 'nav', 'header', 'footer', 'aside',
})

BLOCK_TAGS = frozenset({
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'li', 'blockquote', 'pre', 'td', 'th',
})

HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})

CONTAINER_TAGS = frozenset({'article', 'main', 'section', 'div', 'body'})

# 正文容器 id/class 白名单（优先命中，跳过评分）
ARTICLE_CONTAINER_SELECTORS = [
    ('id', 'js_content'),          # 微信公众号
    ('id', 'article-content'),     # CSDN
    ('id', 'post-content'),        # WordPress
    ('id', 'entry-content'),       # WordPress
    ('class', 'rich_media_content'),  # 微信公众号
    ('class', 'post-content'),
    ('class', 'article-body'),
    ('class', 'entry-content'),
    ('class', 'article-content'),
]
