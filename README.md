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
- [Markdown 导出机制](#markdown-导出机制)
- [数据迁移：导入与导出](#数据迁移导入与导出)
- [打包发布](#打包发布)
- [API 文档](#api-文档)
- [内容提取策略](#内容提取策略)
- [安全设计](#安全设计)
- [主题系统](#主题系统)
- [版本更新记录](#版本更新记录)
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
- **动态页面兜底** — 当正文容器为空（如 SPA 应用官网）时，自动用 meta 描述生成最小正文，避免阅读视图空白

### 本地优先 · 隐私至上

- **SQLite 本地持久化** — 数据库文件就在你的电脑里
- **SSRF 防护** — 抓取请求安全隔离，拒绝内网/私有/环回地址访问
- **仅监听 127.0.0.1** — 不暴露到局域网或公网
- **零依赖云服务** — 完全离线可用，无需注册账号
- **图片代理** — 后端代理外部图片，避免跨域 ORB 拦截与微信 Referer 校验

### 沉浸阅读体验

- **Markdown 渲染** — 自研渲染器，支持标题、代码高亮、引用、表格、图片灯箱
- **源码视图** — 随时查看原始 Markdown，一键切换
- **超长正文折叠** — 6000 字以上自动按段落截断，点击"展开全部"查看
- **图片 Gallery** — 连续多图自动合并为横向图片组，点击放大查看
- **访问原网页** — 一键跳转原始链接

### Markdown 导出 · 多端可选

- **桌面端：原生保存对话框** — 用户自由选择保存位置（tkinter + pywebview 双方案，稳定不失败）
- **失败兜底** — 后端写入桌面 `BookmarkHub-Export/` 目录，Toast 显示完整保存路径 + 打开文件夹按钮
- **网页版：浏览器下载** — 直接触发浏览器下载，不再写入服务器文件系统
- **保存成功提示** — Toast 显示完整绝对路径，18 秒长显 + 路径复制兜底

### 数据迁移

- **JSON 全量导出** — 书签、标签、Markdown 一键导出，用于备份或多电脑迁移
- **JSON 导入** — 导入时按 URL 去重，避免重复收藏
- **Markdown 单条导出** — 每条书签可单独导出 `.md` 文件

### 液态玻璃设计

- **三种主题** — 纯净白、炫彩（液态玻璃）、纯净黑，随心切换
- **Apple 设计语言** — SF Pro 字体、毛玻璃质感、圆角卡片
- **响应式布局** — 窗口缩放自适应
- **标签系统** — 自定义标签分类，支持多维度筛选
- **卡片内容提示** — 正文极薄（<80字）的卡片摘要追加"· 仅摘要"标记，避免点进去才发现空白

---

## 项目展示

项目附带一个产品展示官网页面 [showcase.html](../showcase.html)，包含：

- Hero 区 + 应用 Mockup
- 智能提取 / 隐私保护 / 沉浸阅读 / 液态玻璃 四大功能展示
- 三种主题自动轮播动态演示（通过 CSS + 设计元素实现，非截图）
- 数据统计、使用流程、技术规格、下载入口（内嵌 GitHub 下载链接）

```bash
# 本地预览展示页
python -m http.server 8766 --directory "项目根目录"
# 浏览器访问 http://127.0.0.1:8766/showcase.html
```

**部署上线**：展示页为纯静态 HTML，可直接部署到 GitHub Pages / Vercel / Cloudflare Pages 等平台（将 `showcase.html` 重命名为 `index.html` 即可）。

---

## 技术架构

```
┌───────────────────────────────────────────────────┐
│                桌面窗口 (pywebview)                │
│            WebView2 渲染前端页面                    │
│   JsApi: save_markdown_dialog / open_folder        │
├───────────────────────────────────────────────────┤
│              前端 (Vanilla JS + CSS)               │
│  App → Events → Renderer → State → Storage         │
│  MarkdownRenderer / ContentExtractor              │
├───────────────────────────────────────────────────┤
│          后端 (Python ThreadingHTTPServer)         │
│  静态文件 │ REST API │ 图片代理 │ 后台抓取线程      │
│  /api/export/markdown (写入桌面)                   │
├───────────────────────────────────────────────────┤
│          内容提取器 (extractors 子包)              │
│  站点分发 → 页面类型判定 → 策略执行 → Markdown      │
│  ✨ 空值兜底 (极短markdown用description回填)        │
├───────────────────────────────────────────────────┤
│  tkinter.filedialog (文件保存对话框)                │
│  pywebview (文件对话框兜底)  → 双方案容错           │
├───────────────────────────────────────────────────┤
│            SQLite (bookmarks.db)                   │
│      bookmarks │ tags │ bookmark_tags              │
└───────────────────────────────────────────────────┘
```

**后端技术栈**

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 后端运行时 |
| `http.server.ThreadingHTTPServer` | 内嵌 HTTP 服务器 |
| `sqlite3` | 本地数据库（标准库） |
| `html.parser.HTMLParser` | HTML DOM 解析（标准库，零外部依赖） |
| `tkinter + filedialog` | 文件保存对话框（Python 标准库，打包稳定） |
| `pywebview` | 原生桌面窗口（WebView2） + 文件对话框兜底 |
| `PyInstaller` | 打包为 exe |
| `Inno Setup` | Windows 安装程序 |

**前端技术栈**

| 技术 | 用途 |
|------|------|
| 原生 HTML5 | 无框架依赖 |
| Vanilla JavaScript (ES5+) | 模块化 IIFE 模式 |
| CSS3 + CSS Variables | 设计令牌系统（三套主题） |
| `fetch` API | 与后端 REST API 通信 |
| `localStorage` | 主题偏好持久化 |

---

## 项目结构

```
bookmark-1.2/
├── bookmark-1.0/                 # 应用主目录
│   ├── server.py                 # 桌面应用主入口 + 桌面/开发模式切换
│   ├── index.html                # 前端页面
│   ├── BookmarkHub.spec          # PyInstaller 打包配置（含 tkinter）
│   ├── backend/                  # Python 后端
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLite 数据库操作 + CRUD + 路径决策
│   │   ├── handler.py            # HTTP 请求路由 + Markdown导出API + 图片代理
│   │   ├── extractor.py          # 网络层：URL规范化 + SSRF防护 + 浏览器UA抓取
│   │   └── extractors/           # 内容提取策略子包
│   │       ├── __init__.py       #   策略分发器 + SITE_STRATEGIES注册
│   │       ├── base.py           #   公共工具：文本清理、噪声过滤、charset检测
│   │       ├── parser.py         #   DOM解析与正文容器评分（增强算法）
│   │       ├── markdown.py       #   HTML → Markdown 转换器 + 噪声清洗
│   │       ├── article.py        #   通用文章提取策略（空值兜底）
│   │       ├── weixin.py         #   微信公众号提取策略（空值兜底）
│   │       ├── video.py          #   B站/抖音视频提取策略（兜底扩充）
│   │       └── portal.py         #   门户首页板块化摘要策略（空值兜底）
│   ├── css/                      # 样式文件
│   │   ├── tokens.css            #   CSS变量与设计令牌（含三套主题）
│   │   ├── base.css              #   基础样式与背景动效
│   │   ├── layout.css            #   布局（侧边栏、主区、阅读视图）
│   │   ├── cards.css             #   书签卡片样式
│   │   ├── sheet.css             #   底部弹出面板
│   │   ├── reading.css           #   阅读视图样式
│   │   ├── dialogs.css           #   对话框样式（Toast 固定深色背景，全主题可见）
│   │   └── responsive.css        #   响应式适配
│   ├── js/                       # 前端模块
│   │   ├── app.js                #   应用入口与编排器
│   │   ├── events.js             #   事件绑定 + Markdown三级导出降级
│   │   ├── render.js             #   DOM 渲染层 + 卡片"仅摘要"提示
│   │   ├── state.js              #   应用状态管理
│   │   ├── storage.js            #   REST API 客户端 + JSON导入导出
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

# 不自动打开浏览器（支持 -n / --no-browser 别名）
python server.py --no-open
```

开发模式下，前端通过浏览器访问 `http://127.0.0.1:8765`，控制台输出日志。Markdown 导出走浏览器下载（不调用 pywebview API）。

### 桌面应用模式

```bash
python server.py  # 打包后自动进入桌面模式
```

打包后（`frozen` 模式）启动原生 pywebview 窗口，关闭窗口即退出程序，无控制台黑框。Markdown 导出走 tkinter + pywebview 双方案保存对话框。

### 网页版部署

将 `bookmark-1.0` 目录作为 HTTP 服务根目录运行：
```bash
cd bookmark-1.0 && python server.py --no-open
```
然后在任意浏览器访问 `http://127.0.0.1:8765` 即可使用。网页版 Markdown 导出直接走浏览器下载。

---

## 开发指南

### 数据流

```
用户粘贴 URL
  → Events.handleSave()
  → StorageManager.add()  POST /api/bookmarks
  → 后端 create_bookmark()  写入 SQLite，status=pending
  → 后台线程 fetch_and_update()  异步抓取（不覆盖用户已改标题）
    → extractor.fetch_html()  SSRF校验 + 浏览器UA + HTTP请求
    → extractors.extract_content()  策略分发
        → 空值兜底：markdown<50字 时 description 回填
    → update_bookmark()  写入 markdown，status=saved
  → 前端 2.5s 自动刷新  展示提取结果 + 卡片"仅摘要"标记
```

### Markdown 导出降级链

```
用户点击「导出 Markdown」
  → 桌面端（有 pywebview.api）
      → 1. tkinter.filedialog.asksaveasfilename（Python标准库，主方案）
      → 2. pywebview.create_file_dialog（兜底方案）
      → 3. 后端 /api/export/markdown 写入桌面 BookmarkHub-Export/
  → 网页版（无 pywebview.api）
      → 直接浏览器 Blob 下载
  → Toast: 显示完整路径 + 打开文件夹（失败则复制路径）
```

### 前端模块说明

| 模块 | 职责 |
|------|------|
| `App` | 入口编排，初始化所有模块 |
| `Events` | DOM 事件绑定、Markdown 导出三级降级链、Toast 路径显示 |
| `Renderer` | 纯 DOM 渲染，基于 AppState 状态；正文极薄卡片追加"仅摘要"标记 |
| `AppState` | 集中管理可变状态，提供 getter/setter |
| `StorageManager` | REST API 客户端，JSON 导入导出，Markdown 文件 API |
| `ContentExtractor` | 触发后端提取，前端 URL 预校验 |
| `MarkdownRenderer` | Markdown → HTML 渲染（不依赖外部库） |

### 后端模块说明

| 模块 | 职责 |
|------|------|
| `server.py` | 主入口，桌面/开发模式切换，JsApi（保存对话框+打开文件夹） |
| `handler.py` | HTTP 路由分发，静态文件，REST API，图片代理，Markdown 导出 API |
| `db.py` | SQLite 连接管理，书签/标签 CRUD，开发/打包模式路径决策 |
| `extractor.py` | URL 规范化，SSRF 防护，浏览器 User-Agent HTTP 安全抓取 |
| `extractors/` | 内容提取策略子包（可扩展），统一空值兜底 |

### pywebview JsApi 接口

桌面端通过 `window.pywebview.api.xxx()` 调用：

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `save_markdown_dialog(name, content)` | `suggested_name: str`, `markdown_content: str` | `{ok, path, dir, filename}` 或 `{canceled}` 或 `{error}` | 弹出保存对话框，tkinter 优先，失败自动降级 pywebview |
| `open_folder_in_explorer(path)` | `folder_path: str` | `{ok, opened_path}` 或 `{error}` | 在资源管理器中打开指定文件夹 |

---

## Markdown 导出机制

### 后端导出路径决策

`handler.py: _get_export_dir()` 按优先级选择导出目录：

```
1. 桌面目录（优先）：
   %USERPROFILE%\Desktop  →  $HOME/Desktop
2. 系统下载目录（桌面不存在时）：
   %USERPROFILE%\Downloads  →  $HOME/Downloads
3. 用户目录（全部不存在时兜底）：
   %USERPROFILE%  →  $HOME
```

文件保存格式：`<标题>.md`，同名自动追加 ` (1)`、` (2)`… 后缀避免覆盖。

### 三级降级容错

```
┌─────────────────────────────────────────────────────┐
│ 桌面端 exportMarkdown 三级降级（events.js:194-233）  │
├─────────────────────────────────────────────────────┤
│ 第一级  pywebview.api.save_markdown_dialog           │
│   成功 → Toast 完整路径 + 打开文件夹按钮              │
│   用户取消 → 静默返回，不再降级                       │
│   其他失败 → 设置 pywebviewFailed 标记              │
├─────────────────────────────────────────────────────┤
│ 第二级  仅在 pywebviewFailed 时触发                  │
│   StorageManager.exportMarkdownFile()                │
│   → POST /api/export/markdown                        │
│   → 后端写入桌面 BookmarkHub-Export/xxx.md          │
├─────────────────────────────────────────────────────┤
│ 第三级  以上均失败  →  Blob 浏览器下载               │
│   → Toast 显示"文件已保存到浏览器下载目录"            │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ 网页版 exportMarkdown 直接走浏览器下载               │
│ （因为没有 window.pywebview.api，跳过前两级）        │
└─────────────────────────────────────────────────────┘
```

### Toast 显示优化

- **保存对话框**：成功后 Toast 显示**完整绝对路径**，持续 **18 秒**
- **动作按钮**：「打开所在文件夹」→ 调用 JsApi 启动资源管理器
- **失败兜底**：资源管理器打开失败 → 自动**复制路径到剪贴板**，Toast 再提示
- **白色主题**：Toast 使用固定深色背景 `rgba(28,28,30,0.92)` + 浅色文字，确保所有主题下文字可见

---

## 数据迁移：导入与导出

### JSON 全量导出（前端 storage.js）

```javascript
// 导出当前所有书签 + 标签 + 正文
const data = await StorageManager.exportData();
// 返回格式: { exportedAt, version: 1, bookmarks: [{...}], tags: [{...}]}
```

浏览器触发下载 `bookmark-hub-backup-YYYYMMDD-HHMMSS.json`。

### JSON 导入

```javascript
// 导入 JSON 数据（按 URL 去重）
const result = await StorageManager.importData(jsonData);
// 返回 { imported, skipped, total }
```

导入时通过 `canonical_url` 判断已存在，避免重复创建。已存在的书签自动跳过，不会覆盖用户修改。

---

## 打包发布

### 1. PyInstaller 打包

```bash
cd bookmark-1.0
python -m PyInstaller --clean -y BookmarkHub.spec
```

生成 `dist/BookmarkHub/` 目录，包含 `BookmarkHub.exe` 和 `_internal/` 依赖。这是**绿色免安装版**，双击 `BookmarkHub.exe` 即可运行。

**打包配置要点**（[BookmarkHub.spec](BookmarkHub.spec)）：

- `console=False` — 无控制台黑框
- `tkinter` 模块**完整打包**：`collect_submodules('tkinter')` + `collect_all('tkinter')`，确保保存对话框 DLL（tcl86t.dll / tk86t.dll / tcl/tk 语言包）全部包含
- 收集 `backend`、`webview`、`clr_loader` 全部依赖
- 静态资源（`index.html`、`css/`、`js/`）打包进 exe

### 2. Inno Setup 安装程序

使用 [BookmarkHub-Setup.iss](../BookmarkHub-Setup.iss) 生成安装包：

```bash
# 用 Inno Setup Compiler 编译（需安装 Inno Setup 6）
iscc BookmarkHub-Setup.iss
```

安装程序特性：

- LZMA2 Ultra 压缩
- 可选桌面快捷方式
- 可选开机自启
- 安装后自动启动
- 卸载时清理 `%APPDATA%\BookmarkHub` 数据

### 数据存储路径

| 模式 | 数据库路径 | Markdown 导出目录 |
|------|-----------|-----------------|
| 开发模式 | `bookmark-1.0/data/bookmarks.db` | `桌面/BookmarkHub-Export/` |
| 打包模式（绿色/安装版） | `%APPDATA%\BookmarkHub\bookmarks.db` | `桌面/BookmarkHub-Export/` |

---

## API 文档

所有 API 以 `/api` 为前缀，仅监听 `127.0.0.1`。

### 书签管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/bookmarks` | 获取书签列表（支持 `q` 搜索、`category` 分类、`tag` 标签筛选） |
| `GET` | `/api/bookmarks/:id` | 获取单个书签详情 |
| `POST` | `/api/bookmarks` | 创建书签（自动触发后台抓取，`status` 初始为 `pending`） |
| `PUT` | `/api/bookmarks/:id` | 更新书签（标题/分类/标签/URL/Markdown 正文等） |
| `DELETE` | `/api/bookmarks/:id` | 删除书签（级联删除标签关联） |
| `POST` | `/api/bookmarks/retry` | 重新抓取 `{id}` 书签正文 |

### 标签与统计

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tags` | 获取所有标签（含书签计数） |
| `GET` | `/api/stats` | 获取分类统计 |

### 提取与导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/extract` | 提取 URL 正文（不入库，仅返回 `{title, description, markdown}`） |
| `POST` | `/api/export/markdown` | 将书签 Markdown 写入桌面导出目录，返回 `{ok, path, dir, filename}` |

### 图片代理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/img?url=<encoded>` | 代理外部图片，避免浏览器跨域 ORB 拦截；1 天缓存 |

### 请求示例

```bash
# 创建书签
curl -X POST http://127.0.0.1:8765/api/bookmarks \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mp.weixin.qq.com/s/xxx","category":"tech","tags":["AI"]}'

# 搜索书签（title + url + markdown + description + tags 五字段联合模糊搜索）
curl "http://127.0.0.1:8765/api/bookmarks?q=transformer&category=tech"

# 导出单条 Markdown
curl -X POST http://127.0.0.1:8765/api/export/markdown \
  -H "Content-Type: application/json" \
  -d '{"id":123}'
```

### 书签状态

| 状态 | 说明 |
|------|------|
| `pending` | 刚创建，后台抓取进行中 |
| `saved` | 抓取成功，正文已保存（可能为 description 兜底内容） |
| `failed` | 抓取失败，`error` 字段记录原因（显示卡片红色警告徽章） |

---

## 内容提取策略

### 策略分发流程

```
extract_content(html, base_url, final_url)
  │
  ├─ 1. 站点特例分发（SITE_STRATEGIES）
  │   ├─ mp.weixin.qq.com → extract_weixin（#js_content 锚点优先）
  │   ├─ bilibili.com     → extract_bilibili / 专栏页(/read/cv*) → article
  │   ├─ douyin.com       → extract_douyin（RENDER_DATA + _ROUTER_DATA）
  │   └─ iesdouyin.com    → extract_douyin
  │
  ├─ 2. 页面类型判定（detect_page_type）
  │   ├─ article<=1 + p<10 + link>30 + 长文本块<3 → portal
  │   └─ 默认 → article
  │
  └─ 3. 默认：增强评分算法（extract_article）
      ├─ id/class 白名单优先匹配
      ├─ JSON-LD 结构化数据解析
      ├─ DOM 容器评分
      ├─ 兄弟节点 >30% 回溯父级
      ├─ HTML → Markdown 转换
      └─ ✨ markdown<50字 → description 回填兜底（全局统一）
```

### 评分算法

正文容器评分公式：

```
score = (文本长度 + 段落数×25 + 标题数×35) / (1 + 链接文本密度×8)
```

容器加权：
- `<article>` / `<main>` → ×1.5
- `<section>` → ×1.2
- 动态文本阈值：`max(80, min(200, 全文文本/10))`

### 全局空值兜底（所有策略）

所有策略返回前统一执行（article / portal / weixin / video 各文件返回前）：

```python
if not md.strip() or len(md.strip()) < 50:
    if description:
        md = '# {标题}\n\n{description}'
    else:
        md = '# {标题}\n\n> 此页面为动态渲染内容，正文无法自动提取，请点击「原网页打开」查看完整内容。'
```

**效果**：SPA 应用官网、无法执行 JS 的视频页等"空正文"场景，阅读视图不再显示"暂无正文内容"空白页，至少有标题 + 描述段落。

### 浏览器 User-Agent 优化

抓取请求使用浏览器 UA（而非自定义 bot UA）：

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
```

**效果**：B站/抖音等平台对 bot UA 返回精简 HTML 的概率大幅降低，`__INITIAL_STATE__` / `RENDER_DATA` 等 JSON 数据块更可能完整出现在 HTML 中，视频信息提取成功率显著提升。

### 噪声过滤

双维度过滤（class + id 关键词匹配）：

- 广告/推广：`ads`、`sponsor`、`promotion`
- 交互贴纸：`toast`、`banner`、`popup`、`modal`
- 社交推荐：`comment`、`related`、`share`、`recommend`
- 导航结构：`sidebar`、`menu`、`nav`、`breadcrumb`
- 微信专项：`qr_code`、`reward_area`、`like_area`、`weapp_card`

图片处理：
- 检测懒加载：优先读取 `data-src` / `data-original` / `srcset`
- 过滤 1×1 像素占位图
- 图片 URL 全部转为 `/api/img?url=...` 后端代理（避免跨域 + 微信 Referer 校验）
- 加载失败显示占位符，保持卡片/阅读视图布局稳定

### 扩展新站点

在 [extractors/\_\_init\_\_.py](backend/extractors/__init__.py) 的 `SITE_STRATEGIES` 列表注册：

```python
SITE_STRATEGIES = [
    ('mp.weixin.qq.com', extract_weixin),
    ('bilibili.com', extract_bilibili),
    # 新增：
    ('zhihu.com', extract_zhihu),
]
```

新增策略模块只需实现接口：
```python
def extract_xxx(html: str, base_url: str, final_url: str) -> tuple[str, str, str]:
    """返回 (title, description, markdown) 三元组"""
```
并在返回前加上统一的空值兜底逻辑即可。

---

## 安全设计

### SSRF 防护

所有 HTTP 抓取请求经过三层校验：

1. **URL 规范化** — 补协议、去 fragment、小写 host
2. **主机解析** — `socket.getaddrinfo` 解析所有 IP（一个私网 IP 即拒绝）
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
| Toast 保存成功显示 | 18 秒 |

### 路径安全

静态文件服务防止路径穿越：

```python
if '..' in rel.split('/'):
    return self.send_error(403)
target = os.path.normpath(os.path.join(STATIC_DIR, rel))
if not target.startswith(STATIC_DIR):
    return self.send_error(403)
```

### 用户数据隔离

- 打包后数据库写入 `%APPDATA%\BookmarkHub\`（用户目录，管理员权限）
- 卸载/重装不删除用户数据（除非 Inno Setup 勾选清理选项）
- 所有抓取请求仅发出给用户显式输入的 URL（不对任意第三方上报）

---

## 主题系统

三套主题通过 `data-theme` 属性切换，CSS 变量驱动：

| 主题 | data-theme | 风格 |
|------|------------|------|
| 纯净白 | `white` | 经典 iOS 浅色，纯白背景 |
| 炫彩 | `blue` | 液态玻璃，毛玻璃质感（默认） |
| 纯净黑 | `black` | 深色模式，OLED 友好 |

切换方式：点击标题栏左侧三个圆点按钮。偏好保存在 `localStorage`，下次打开自动恢复。

**Toast 样式独立**：使用固定深色背景 + 浅色文字，**不受主题变量影响**，确保白色主题下文字也清晰可见。

```javascript
// 主题切换核心逻辑
document.documentElement.setAttribute('data-theme', theme);
localStorage.setItem('bookmark-hub-theme', theme);
```

---

## 版本更新记录

### v1.2.0（当前）

**提取优化**
- 新增：所有提取策略（article/portal/weixin/video）Markdown 空值兜底（<50 字自动用 description 回填），解决 SPA 官网阅读视图空白
- 优化：HTTP 抓取 UA 改为浏览器 Chrome UA，提高 B站/抖音 JSON 数据获取成功率
- 前端：正文极薄（<80 字）的卡片摘要追加"· 仅摘要"提示，用户在列表页就知道正文不完整

**导出修复**
- 关键修复：`BookmarkHub.spec` 完整打包 `tkinter` 模块（含 tcl/tk 资源），解决绿色免安装版无法保存 Markdown 的问题
- 桌面端：`save_markdown_dialog` 改为 **tkinter 优先 + pywebview 兜底** 双方案，任意一个可用即成功
- 前端：`exportMarkdown` 三级降级链正确实现（pywebview 失败→后端API→浏览器下载，原逻辑会在失败后直接 return 不降级）
- Toast：显示完整**绝对路径** + 18 秒长显 + 打开文件夹按钮（失败自动复制路径到剪贴板）
- 网页版：检测无 `window.pywebview.api` 时**直接走浏览器下载**，不再调用后端写文件 API

**可见性修复**
- Toast 样式改为固定 `rgba(28,28,30,0.92)` 深色背景 + `#F2F2F7` 浅色文字，白色主题下文字不再不可见

---

## 许可证

开源项目，仅供学习交流使用。

---

**书签集 · Bookmark Hub v1.2.0** — 本地优先 · 隐私至上 · 开源精神
