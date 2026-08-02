# 书签集 · Bookmark Hub

> 为阅读者而生的本地优先桌面书签管理器。

粘贴链接，自动提取网页正文为 Markdown；所有数据存储在本地 SQLite，不经过任何云端服务器。无账号、无追踪、无联网依赖。

---

## 目录

- [功能特性](#功能特性)
- [项目展示](#项目展示)
- [技术架构](#技术架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [开发指南](#开发指南)
- [打包发布](#打包发布)
- [API 文档](#api-文档)
- [内容提取策略](#内容提取策略)
- [安全设计](#安全设计)
- [主题系统](#主题系统)
- [许可证](#许可证)

---

## 功能特性

### 智能正文提取

不只是存一个网址。书签集会抓取网页正文，智能去除广告、导航、评论等噪声，转换为干净的 Markdown 格式保存。

- **微信公众号文章** — 精准提取 `#js_content` 正文，过滤赞赏/二维码/推荐阅读
- **B站视频 / 专栏** — 解析 `__INITIAL_STATE__` JSON 数据，提取视频信息与统计
- **抖音视频** — 解析 `RENDER_DATA` 提取视频描述与作者
- **通用文章/博客/新闻** — 增强评分算法自动识别正文容器
- **门户首页** — 板块化摘要，分类提取通知公告、新闻动态等

### 本地优先 · 隐私至上

- **SQLite 本地持久化** — 数据库文件就在你的电脑里
- **SSRF 防护** — 抓取请求安全隔离，拒绝内网/私有/环回地址访问
- **仅监听 127.0.0.1** — 不暴露到局域网或公网
- **零依赖云服务** — 完全离线可用，无需注册账号

### 沉浸阅读体验

- **Markdown 渲染** — 自研渲染器，支持标题、代码高亮、引用、表格、图片灯箱
- **源码视图** — 随时查看原始 Markdown，一键切换
- **图片代理** — 后端代理外部图片，避免跨域拦截
- **访问原网页** — 一键跳转原始链接

### 液态玻璃设计

- **三种主题** — 纯净白、炫彩（液态玻璃）、纯净黑，随心切换
- **Apple 设计语言** — SF Pro 字体、毛玻璃质感、圆角卡片
- **响应式布局** — 窗口缩放自适应，网格/列表双视图
- **标签系统** — 自定义标签分类，支持多维度筛选

---

## 项目展示

项目附带一个 iPhone 风格的产品展示页面 [showcase.html](../showcase.html)，包含：

- Hero 区 + 应用 Mockup
- 智能提取 / 隐私保护 / 沉浸阅读 / 液态玻璃 四大功能展示
- 三种主题自动轮播动态演示（通过 CSS + 设计元素实现，非截图）
- 数据统计、使用流程、技术规格、下载入口

```bash
# 本地预览展示页
python -m http.server 8766 --directory "项目根目录"
# 浏览器访问 http://127.0.0.1:8766/showcase.html
```

---

## 技术架构

```
┌─────────────────────────────────────────────┐
│              桌面窗口 (pywebview)             │
│          WebView2 渲染前端页面                │
├─────────────────────────────────────────────┤
│            前端 (Vanilla JS + CSS)            │
│  App → Events → Renderer → State → Storage   │
├─────────────────────────────────────────────┤
│          后端 (Python ThreadingHTTPServer)    │
│    静态文件 │ REST API │ 图片代理 │ 抓取       │
├─────────────────────────────────────────────┤
│          内容提取器 (extractors 子包)          │
│  站点分发 → 页面类型判定 → 策略执行 → Markdown │
├─────────────────────────────────────────────┤
│            SQLite (bookmarks.db)             │
│      bookmarks │ tags │ bookmark_tags        │
└─────────────────────────────────────────────┘
```

**后端技术栈**

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 后端运行时 |
| `http.server.ThreadingHTTPServer` | 内嵌 HTTP 服务器 |
| `sqlite3` | 本地数据库（标准库） |
| `pywebview` | 原生桌面窗口（WebView2） |
| `PyInstaller` | 打包为 exe |
| `Inno Setup` | Windows 安装程序 |

**前端技术栈**

| 技术 | 用途 |
|------|------|
| 原生 HTML5 | 无框架依赖 |
| Vanilla JavaScript (ES5+) | 模块化 IIFE 模式 |
| CSS3 + CSS Variables | 设计令牌系统 |
| `fetch` API | 与后端 REST API 通信 |
| `localStorage` | 主题偏好持久化 |

---

## 项目结构

```
bookmark-1.2/
├── bookmark-1.0/                 # 应用主目录
│   ├── server.py                 # 桌面应用主入口
│   ├── index.html                # 前端页面
│   ├── BookmarkHub.spec          # PyInstaller 打包配置
│   ├── backend/                  # Python 后端
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLite 数据库操作 + CRUD
│   │   ├── handler.py            # HTTP 请求路由与处理
│   │   ├── extractor.py          # 网络层：URL规范化 + SSRF防护 + HTTP抓取
│   │   └── extractors/           # 内容提取策略子包
│   │       ├── __init__.py       #   策略分发器
│   │       ├── base.py           #   公共工具：文本清理、噪声过滤、charset检测
│   │       ├── parser.py         #   DOM解析与正文容器评分
│   │       ├── markdown.py       #   HTML → Markdown 转换器
│   │       ├── article.py        #   通用文章提取策略
│   │       ├── weixin.py         #   微信公众号提取策略
│   │       ├── video.py          #   B站/抖音视频提取策略
│   │       └── portal.py         #   门户首页板块化摘要策略
│   ├── css/                      # 样式文件
│   │   ├── tokens.css            #   CSS变量与设计令牌（含三套主题）
│   │   ├── base.css              #   基础样式与背景动效
│   │   ├── layout.css            #   布局（侧边栏、主区、阅读视图）
│   │   ├── cards.css             #   书签卡片样式
│   │   ├── sheet.css             #   底部弹出面板
│   │   ├── reading.css           #   阅读视图样式
│   │   ├── dialogs.css           #   对话框样式
│   │   └── responsive.css        #   响应式适配
│   ├── js/                       # 前端模块
│   │   ├── app.js                #   应用入口与编排器
│   │   ├── events.js             #   事件绑定与用户交互
│   │   ├── render.js             #   DOM 渲染层
│   │   ├── state.js              #   应用状态管理
│   │   ├── storage.js            #   REST API 客户端
│   │   ├── extractor.js          #   提取请求代理
│   │   └── markdown.js           #   Markdown → HTML 渲染器
│   └── .gitignore
├── showcase.html                 # 产品展示官网页面
├── BookmarkHub-Setup.iss         # Inno Setup 安装脚本
└── README.md                     # 本文件
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Windows 10/11（需 WebView2 运行时，Win11 已内置）

### 安装依赖

```bash
pip install pywebview pyinstaller
```

### 开发模式运行

```bash
cd bookmark-1.0

# 默认 127.0.0.1:8765，自动打开浏览器
python server.py

# 自定义端口
python server.py 9000

# 不自动打开浏览器
python server.py --no-open
```

开发模式下，前端通过浏览器访问 `http://127.0.0.1:8765`，控制台输出日志。

### 桌面应用模式

```bash
python server.py  # 打包后自动进入桌面模式
```

打包后（`frozen` 模式）启动原生 pywebview 窗口，关闭窗口即退出程序，无控制台黑框。

---

## 开发指南

### 数据流

```
用户粘贴 URL
  → Events.handleSave()
  → StorageManager.create()  POST /api/bookmarks
  → 后端 create_bookmark()  写入 SQLite，status=pending
  → 后台线程 fetch_and_update()  异步抓取
    → extractor.fetch_html()  SSRF校验 + HTTP请求
    → extractors.extract_content()  策略分发
    → update_bookmark()  写入 markdown，status=saved
  → 前端轮询/刷新  展示提取结果
```

### 前端模块说明

| 模块 | 职责 |
|------|------|
| `App` | 入口编排，初始化所有模块 |
| `Events` | DOM 事件绑定与用户交互处理 |
| `Renderer` | 纯 DOM 渲染，基于 AppState 状态 |
| `AppState` | 集中管理可变状态，提供 getter/setter |
| `StorageManager` | REST API 客户端，网络请求与错误归一化 |
| `ContentExtractor` | 触发后端提取，前端 URL 预校验 |
| `MarkdownRenderer` | Markdown → HTML 渲染（不依赖外部库） |

### 后端模块说明

| 模块 | 职责 |
|------|------|
| `server.py` | 主入口，桌面/开发模式切换，端口管理 |
| `handler.py` | HTTP 路由分发，静态文件，REST API，图片代理 |
| `db.py` | SQLite 连接管理，书签/标签 CRUD |
| `extractor.py` | URL 规范化，SSRF 防护，HTTP 安全抓取 |
| `extractors/` | 内容提取策略子包（可扩展） |

---

## 打包发布

### 1. PyInstaller 打包

```bash
cd bookmark-1.0
pyinstaller BookmarkHub.spec
```

生成 `dist/BookmarkHub/` 目录，包含 `BookmarkHub.exe` 和 `_internal/` 依赖。

打包配置要点（[BookmarkHub.spec](BookmarkHub.spec)）：

- `console=False` — 无控制台黑框
- 收集 `backend`、`webview`、`clr_loader` 全部依赖
- 静态资源（`index.html`、`css/`、`js/`）打包进 exe

### 2. Inno Setup 安装程序

使用 [BookmarkHub-Setup.iss](../BookmarkHub-Setup.iss) 生成安装包：

```bash
# 用 Inno Setup Compiler 编译
iscc BookmarkHub-Setup.iss
```

安装程序特性：

- LZMA2 Ultra 压缩
- 可选桌面快捷方式
- 可选开机自启
- 安装后自动启动
- 卸载时清理 `%APPDATA%\BookmarkHub` 数据

### 数据存储路径

| 模式 | 路径 |
|------|------|
| 开发模式 | `bookmark-1.0/data/bookmarks.db` |
| 打包模式 | `%APPDATA%\BookmarkHub\bookmarks.db` |

---

## API 文档

所有 API 以 `/api` 为前缀，仅监听 `127.0.0.1`。

### 书签管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/bookmarks` | 获取书签列表（支持搜索/分类/标签筛选） |
| `GET` | `/api/bookmarks/:id` | 获取单个书签详情 |
| `POST` | `/api/bookmarks` | 创建书签（自动触发后台抓取） |
| `PUT` | `/api/bookmarks/:id` | 更新书签（标题/分类/标签/URL等） |
| `DELETE` | `/api/bookmarks/:id` | 删除书签 |
| `POST` | `/api/bookmarks/retry` | 重新抓取失败的书签 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tags` | 获取所有标签（含书签计数） |
| `GET` | `/api/stats` | 获取分类统计 |
| `POST` | `/api/extract` | 提取 URL 正文（不入库，仅返回结果） |
| `GET` | `/api/img?url=...` | 图片代理（避免跨域 ORB 拦截） |

### 请求示例

```bash
# 创建书签
curl -X POST http://127.0.0.1:8765/api/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mp.weixin.qq.com/s/xxx","category":"tech","tags":["AI"]}'

# 搜索书签
curl "http://127.0.0.1:8765/api/bookmarks?q=transformer&category=tech"
```

### 书签状态

| 状态 | 说明 |
|------|------|
| `pending` | 刚创建，后台抓取进行中 |
| `saved` | 抓取成功，正文已保存 |
| `failed` | 抓取失败，`error` 字段记录原因 |

---

## 内容提取策略

### 策略分发流程

```
extract_content(html, base_url, final_url)
  │
  ├─ 1. 站点特例分发（SITE_STRATEGIES）
  │   ├─ mp.weixin.qq.com → extract_weixin
  │   ├─ bilibili.com     → extract_bilibili（专栏页走 article）
  │   ├─ douyin.com       → extract_douyin
  │   └─ iesdouyin.com    → extract_douyin
  │
  ├─ 2. 页面类型判定（detect_page_type）
  │   ├─ article 少 + 链接多 + 段落少 → portal
  │   └─ 默认 → article
  │
  └─ 3. 默认：增强评分算法（extract_article）
      ├─ id/class 白名单优先匹配
      ├─ JSON-LD 结构化数据解析
      ├─ DOM 容器评分（文本密度 + 段落数 + 标题数 / 链接密度）
      └─ HTML → Markdown 转换
```

### 评分算法

正文容器评分公式：

```
score = (文本长度 + 段落数×25 + 标题数×35) / (1 + 链接文本密度×8)
```

信号权重：

| 信号 | 权重 | 说明 |
|------|------|------|
| 文本长度 | 1 | 容器内纯文本字符数 |
| 段落数 | ×25 | `<p>` 标签数量 |
| 标题数 | ×35 | `<h1>`-`<h6>` 数量 |
| 链接密度 | ×8 | 链接文本占比（越高越可能是导航） |

### 噪声过滤

双维度过滤（class + id）：

- 广告/推广：`ads`、`sponsor`、`promotion`
- 交互贴纸：`toast`、`banner`、`popup`、`modal`
- 社交推荐：`comment`、`related`、`share`、`recommend`
- 导航结构：`sidebar`、`menu`、`nav`、`breadcrumb`
- 微信专项：`qr_code`、`reward_area`、`like_area`、`weapp_card`

### 扩展新站点

在 [extractors/\_\_init\_\_.py](bookmark-1.0/backend/extractors/__init__.py) 的 `SITE_STRATEGIES` 列表注册：

```python
SITE_STRATEGIES = [
    ('mp.weixin.qq.com', extract_weixin),
    ('bilibili.com', extract_bilibili),
    # 新增：
    ('zhihu.com', extract_zhihu),
]
```

新增策略模块只需实现 `extract_xxx(html, base_url, final_url) → (title, description, markdown)` 接口。

---

## 安全设计

### SSRF 防护

所有 HTTP 抓取请求经过三层校验：

1. **URL 规范化** — 补协议、去 fragment、小写 host
2. **主机解析** — `socket.getaddrinfo` 解析所有 IP
3. **IP 验证** — 拒绝以下地址：
   - 私有网络（`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`）
   - 环回地址（`127.0.0.0/8`）
   - 链路本地（`169.254.0.0/16`）
   - 保留/组播/未指定地址
   - IPv4 映射的 IPv6 地址

4. **重定向校验** — `SafeRedirectHandler` 对每次重定向目标重新执行 IP 验证

### 请求限制

| 限制项 | 值 |
|--------|-----|
| 请求超时 | 15 秒 |
| 最大响应体 | 5 MB |
| 最大重定向次数 | 5 次 |
| Markdown 截断 | 80,000 字符 |
| 图片代理上限 | 5 MB |
| 标签长度 | 20 单位（中文算 2，ASCII 算 1） |

### 路径安全

静态文件服务防止路径穿越：

```python
if '..' in rel.split('/'):
    return self.send_error(403)
target = os.path.normpath(os.path.join(STATIC_DIR, rel))
if not target.startswith(STATIC_DIR):
    return self.send_error(403)
```

---

## 主题系统

三套主题通过 `data-theme` 属性切换，CSS 变量驱动：

| 主题 | data-theme | 风格 |
|------|------------|------|
| 纯净白 | `white` | 经典 iOS 浅色，纯白背景 |
| 炫彩 | `blue` | 液态玻璃，毛玻璃质感（默认） |
| 纯净黑 | `black` | 深色模式，OLED 友好 |

切换方式：点击标题栏左侧三个圆点按钮。偏好保存在 `localStorage`，下次打开自动恢复。

```javascript
// 主题切换核心逻辑
document.documentElement.setAttribute('data-theme', theme);
localStorage.setItem('bookmark-hub-theme', theme);
```

---

## 许可证

开源项目，仅供学习交流使用。

---

**书签集 · Bookmark Hub v1.2.0** — 本地优先 · 隐私至上 · 开源精神
