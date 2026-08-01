/**
 * Render — DOM 渲染层
 *
 * 纯渲染函数，不处理事件逻辑。
 * 所有渲染都基于 AppState 的当前状态。
 *
 * @module Renderer
 */
'use strict';

const Renderer = (function () {

  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return document.querySelectorAll(s); };

  // ---------- 工具 ----------

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function firstChar(s) {
    return (s || '?')[0].toUpperCase();
  }

  function fmtTime(ts) {
    var diff = Date.now() - ts;
    var m = Math.floor(diff / 60000);
    var h = Math.floor(diff / 3600000);
    var d = Math.floor(diff / 86400000);
    if (m < 1) return '刚刚';
    if (m < 60) return m + ' 分钟前';
    if (h < 24) return h + ' 小时前';
    if (d < 7) return d + ' 天前';
    if (d < 30) return Math.floor(d / 7) + ' 周前';
    return new Date(ts).toLocaleDateString('zh-CN');
  }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  // ---------- 渲染：卡片网格 ----------

  function renderCards() {
    var grid = $('#cardGrid');
    var list = AppState.getFiltered();

    if (list.length === 0) {
      grid.innerHTML = '<div class="empty"><span class="ic">📑</span><h4>暂无收藏</h4><p>点击右上角「收藏网址」开始吧</p></div>';
      return;
    }

    var CAT_COLORS = AppState.getCatColors();
    var FAV_COLORS = AppState.getFavColors();

    grid.innerHTML = list.map(function (b, i) {
      var colorClass = CAT_COLORS[b.category] || FAV_COLORS[i % 4];
      var tags = (b.tags || []).map(function (t) {
        return '<span class="ltag">' + escapeHtml(t) + '</span>';
      }).join('');

      var excerpt = b.description || (b.markdown || '').replace(/^#\s+.+\n*/, '').substring(0, 120);

      var failed = (b.status === 'failed');
      var statusClass = failed ? ' status-failed' : '';
      // 抓取失败徽章 + hover tooltip（根据是否有具体错误区分文案）
      var warnBadge = '';
      if (failed) {
        var errMsg = (b.error && String(b.error).trim()) ? ('原因：' + escapeHtml(String(b.error).substring(0, 40))) : '';
        warnBadge = '<span class="lcard-warn" title="网址内容读取失败，请自行添加正文"></span>' +
          '<div class="lcard-warn-tooltip">网址内容读取失败，请自行添加正文' +
          (errMsg ? '<br><span style="opacity:.75">' + errMsg + '</span>' : '') +
          '<br><span style="opacity:.75">点击卡片 → 「编辑」可手动补充</span>' +
          '</div>';
      }

      return '<article class="lcard' + statusClass + '" data-id="' + b.id + '" data-cat="' + b.category + '">' +
        warnBadge +
        '<div class="lcard-h"><span class="lfav ' + colorClass + '">' + escapeHtml(firstChar(b.title)) + '</span><h5>' + escapeHtml(b.title || '未命名') + '</h5></div>' +
        '<span class="u">' + escapeHtml(b.url) + '</span>' +
        '<p class="ex">' + escapeHtml(excerpt) + '</p>' +
        '<div class="lcard-f">' + tags + '<span class="ltm">' + fmtTime(b.createdAt) + '</span></div>' +
        '</article>';
    }).join('');
  }

  // ---------- 渲染：侧边栏 ----------

  function renderSidebar() {
    var bookmarks = AppState.getBookmarks();
    var CATEGORIES = AppState.getCategories();
    var counts = {};

    Object.keys(CATEGORIES).forEach(function (cat) {
      counts[cat] = cat === 'all' ? bookmarks.length : bookmarks.filter(function (b) { return b.category === cat; }).length;
    });

    $('#countAll').textContent = counts.all;
    $('#countTech').textContent = counts.tech;
    $('#countDesign').textContent = counts.design;
    $('#countRead').textContent = counts.read;
    $('#countTool').textContent = counts.tool;

    // 高亮当前分类
    $$('#sidebar .sitem').forEach(function (el) {
      el.classList.toggle('is-on', el.getAttribute('data-cat') === AppState.getCurrentCat());
    });

    // 标签列表
    var tagMap = {};
    bookmarks.forEach(function (b) {
      (b.tags || []).forEach(function (t) {
        tagMap[t] = (tagMap[t] || 0) + 1;
      });
    });

    var TAG_COLORS = AppState.getTagColors();
    var currentTag = AppState.getCurrentTag();
    var entries = Object.keys(tagMap).sort(function (a, b) { return tagMap[b] - tagMap[a]; });

    var tagList = $('#tagList');
    tagList.innerHTML = entries.map(function (t, i) {
      var color = TAG_COLORS[i % TAG_COLORS.length];
      return '<div class="stag" data-tag="' + escapeHtml(t) + '" style="' + (currentTag === t ? 'background:var(--glass-strong);box-shadow:var(--glass-inset);border-radius:var(--radius-sm)' : '') + '">' +
        '<span class="dot" style="background:' + color + ';color:' + color + '"></span>' + escapeHtml(t) +
        ' <span style="font:var(--w-medium) var(--text-xs) var(--font-mono);color:var(--text-muted);margin-left:auto">' + tagMap[t] + '</span></div>';
    }).join('');
  }

  // ---------- 渲染：主标题 ----------

  function renderMainHeader() {
    var CATEGORIES = AppState.getCategories();
    var currentTag = AppState.getCurrentTag();
    var currentCat = AppState.getCurrentCat();
    var list = AppState.getFiltered();

    $('#mainTitle').textContent = currentTag ? '标签: ' + currentTag : (CATEGORIES[currentCat] || '全部');
    $('#mainMeta').textContent = list.length + ' 条';
  }

  // ---------- 渲染：状态栏 ----------

  function renderStatus() {
    var list = AppState.getFiltered();
    $('#statusText').textContent = '数据已本地保存 · ' + list.length + ' 条收藏';
  }

  // ---------- 渲染：阅读视图 ----------

  function renderReadingView(id) {
    var b = AppState.getBookmarkById(id);
    if (!b) return;

    var CATEGORIES = AppState.getCategories();
    var CAT_COLORS = AppState.getCatColors();
    var colorClass = CAT_COLORS[b.category] || 'b1';

    var tags = (b.tags || []).map(function (t) {
      return '<span class="read-tag">' + escapeHtml(t) + '</span>';
    }).join('');

    $('#readSide').innerHTML =
      '<span class="fav">' + escapeHtml(firstChar(b.title)) + '</span>' +
      '<h4>' + escapeHtml(b.title) + '</h4>' +
      '<span class="url">' + escapeHtml(b.url) + '</span>' +
      '<div class="read-kv"><span class="k">收藏时间</span><span class="v">' + new Date(b.createdAt).toLocaleDateString('zh-CN') + '</span></div>' +
      '<div class="read-kv"><span class="k">分类</span><span class="v">' + (CATEGORIES[b.category] || b.category) + '</span></div>' +
      '<div class="read-tags">' + tags + '</div>' +
      '<div class="read-acts">' +
        '<button class="read-btn primary" id="btnEditRead"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/></svg>编辑</button>' +
        '<button class="read-btn ghost" id="btnExportRead"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>导出 Markdown</button>' +
        '<button class="read-btn ghost" style="color:var(--danger)" id="btnDeleteRead"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>删除</button>' +
      '</div>';

    // Markdown 渲染
    var md = b.markdown || '';
    $('#panelRender').innerHTML = MarkdownRenderer.render(md || ('# ' + (b.title || '') + '\n\n暂无正文内容'));
    $('#panelSource').innerHTML = '<div class="read-src">' + escapeHtml(md) + '</div>';

    // 图片后处理：多图合并为横向 gallery + 所有图点击放大
    processImages();

    // 重置标签
    var readTop = $('#readView').querySelector('.read-top');
    readTop.querySelectorAll('[data-tab]').forEach(function (t, i) {
      t.classList.toggle('on', i === 0);
      t.setAttribute('aria-selected', i === 0 ? 'true' : 'false');
    });
    $('#readView').querySelectorAll('.read-panel-body').forEach(function (p, i) {
      p.classList.toggle('show', i === 0);
    });

    $('#readCrumb').innerHTML = (CATEGORIES[b.category] || b.category) + ' / <b>' + escapeHtml(b.title) + '</b>';

    // 切换视图
    $('#dashboard').style.display = 'none';
    $('#readView').classList.add('show');
    $('#tbTitle').textContent = b.title;
  }

  function closeReadingView() {
    $('#readView').classList.remove('show');
    $('#dashboard').style.display = '';
    $('#tbTitle').textContent = '书签集';
  }

  // ---------- 自定义分类下拉组件 ----------

  var CAT_LABEL_MAP = { tech: '技术', design: '设计', read: '阅读', tool: '工具' };

  function syncCatSelect(val) {
    var cat = val || 'tech';
    var label = CAT_LABEL_MAP[cat] || '技术';
    // 同步隐藏的原生 select（原有逻辑仍读取 $('#inpCat').value）
    var inp = $('#inpCat');
    if (inp) inp.value = cat;
    // 同步自定义组件显示
    var wrap = $('#catSelect');
    var lbl = $('#catSelectLabel');
    if (wrap) wrap.setAttribute('aria-expanded', 'false');
    if (wrap) wrap.classList.remove('open');
    if (lbl) lbl.textContent = label;
    // 选项高亮
    var opts = document.querySelectorAll('#catSelectMenu .catselect-opt');
    opts.forEach(function (o) {
      var active = (o.getAttribute('data-val') === cat);
      o.classList.toggle('is-active', active);
      o.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  function setCatSelectOpen(open) {
    var wrap = $('#catSelect');
    if (!wrap) return;
    wrap.classList.toggle('open', !!open);
    wrap.setAttribute('aria-expanded', !!open ? 'true' : 'false');
  }

  function selectCatByIndex(delta) {
    var opts = Array.prototype.slice.call(document.querySelectorAll('#catSelectMenu .catselect-opt'));
    if (!opts.length) return;
    var currentIdx = 0;
    opts.forEach(function (o, i) { if (o.classList.contains('is-active')) currentIdx = i; });
    var next = (currentIdx + delta + opts.length) % opts.length;
    var val = opts[next].getAttribute('data-val');
    syncCatSelect(val);
  }

  // ---------- 渲染：Sheet（添加/编辑面板） ----------

  var currentTags = [];

  function renderSheet(bookmark) {
    if (bookmark) {
      $('#sheetTitle').textContent = '编辑收藏';
      $('#inpUrl').value = bookmark.url || '';
      $('#inpTitle').value = bookmark.title || '';
      var cat = bookmark.category || 'tech';
      $('#inpCat').value = cat;
      syncCatSelect(cat);
      currentTags = [].concat(bookmark.tags || []);

      // 显示已有正文
      if (bookmark.markdown) {
        $('#extractBox').style.display = 'block';
        $('#extractPreview').innerHTML = escapeHtml(bookmark.markdown.slice(0, 500));
        $('#extractLabel').textContent = '正文已提取 · Markdown';
        $('#extractStatus').innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>' + (bookmark.markdown.length) + ' 字';
      } else {
        $('#extractBox').style.display = 'none';
      }
    } else {
      $('#sheetTitle').textContent = '收藏新网址';
      $('#inpUrl').value = '';
      $('#inpTitle').value = '';
      $('#inpCat').value = 'tech';
      syncCatSelect('tech');
      currentTags = [];
      $('#extractBox').style.display = 'none';
    }

    $('#titleBox').style.display = 'none';
    renderTagBox();
    setCatSelectOpen(false);
    $('#sheetOverlay').classList.add('show');

    if (!bookmark) {
      setTimeout(function () { $('#inpUrl').focus(); }, 300);
    }
  }

  function closeSheet() {
    $('#sheetOverlay').classList.remove('show');
    setCatSelectOpen(false);
    currentTags = [];
  }

  function renderTagBox() {
    var box = $('#tagBox');
    var existing = currentTags.map(function (t) {
      return '<span class="chip">' + escapeHtml(t) + ' <span class="x" data-remove="' + escapeHtml(t) + '">×</span></span>';
    }).join('');
    box.innerHTML = existing + '<span class="chip add">+ 添加</span>';

    var addBtn = box.querySelector('.chip.add');
    if (addBtn) {
      addBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        showTagInput(box);
      });
    }
    box.querySelectorAll('.x').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        currentTags = currentTags.filter(function (t) { return t !== el.getAttribute('data-remove'); });
        renderTagBox();
      });
    });
  }

  function showTagInput(box) {
    var addBtn = box.querySelector('.chip.add');
    if (addBtn) addBtn.remove();
    var input = document.createElement('input');
    input.className = 'tag-input';
    input.placeholder = '输入标签后回车';
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var val = input.value.trim();
        if (val && currentTags.indexOf(val) === -1) {
          currentTags.push(val);
          renderTagBox();
        }
        e.preventDefault();
      }
      if (e.key === 'Escape') { renderTagBox(); }
    });
    input.addEventListener('blur', function () { renderTagBox(); });
    box.appendChild(input);
    setTimeout(function () { input.focus(); }, 50);
  }

  function getTags() { return currentTags; }
  function setTags(t) { currentTags = t || []; }

  // ---------- 渲染：提取预览 ----------

  function showExtracting() {
    $('#extractBox').style.display = 'block';
    $('#extractLabel').textContent = '正文提取中...';
    $('#extractStatus').innerHTML = '';
    $('#extractPreview').innerHTML = '<span style="color:var(--text-muted)">正在通过代理抓取网页内容...</span>';
  }

  function showExtractResult(result) {
    if (result.success) {
      $('#extractLabel').textContent = '正文已提取 · Markdown';
      $('#extractStatus').innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>' + (result.markdown || '').length + ' 字';
      $('#extractPreview').innerHTML = escapeHtml((result.markdown || '').slice(0, 500));
    } else {
      $('#extractLabel').textContent = '正文提取失败';
      $('#extractStatus').innerHTML = '<span style="color:var(--danger)">失败</span>';
      $('#extractPreview').innerHTML = '<span style="color:var(--text-muted)">' + escapeHtml(result.error || '未知错误') + '</span>';
    }
  }

  function showFetchedTitle(title) {
    $('#titleBox').style.display = 'flex';
    $('#fetchedTitle').textContent = title;
    if (!$('#inpTitle').value.trim()) {
      $('#inpTitle').value = title;
    }
  }

  // ---------- 渲染：全部刷新 ----------

  function renderAll() {
    renderCards();
    renderSidebar();
    renderStatus();
    renderMainHeader();
  }

  // ---------- 确认对话框 ----------

  function showConfirm(id, title) {
    $('#confirmMsg').textContent = '「' + title + '」及其 Markdown 正文将被永久移除，此操作不可撤销。';
    $('#confirmOverlay').classList.add('show');
  }

  function hideConfirm() {
    $('#confirmOverlay').classList.remove('show');
  }

  // ---------- 图片：Gallery + Lightbox ----------
  // 当前 lightbox 中展示的图片列表
  var lbImages = [];
  var lbIndex = 0;

  // 判断一个段落是否"图片占主导"（应该进 gallery）
  // 规则：(1) 图片数 ≥ 2，或 (2) 恰好 1 张图片且文本字符数 < 30（很可能是独立图片加个标题说明）
  function isImgDominant(p) {
    var c = p.cloneNode(true);
    var imgEls = c.querySelectorAll('img');
    var n = imgEls.length;
    if (n === 0) return { ok: false, count: 0 };
    imgEls.forEach(function (n) { if (n.remove) n.remove(); });
    c.querySelectorAll('br').forEach(function (n) { if (n.remove) n.remove(); });
    var txt = (c.textContent || '').trim();
    var ok = (n >= 2) || (n === 1 && txt.length < 30);
    return { ok: ok, count: n, textLen: txt.length };
  }

  function processImages() {
    var panel = $('#panelRender');
    if (!panel) return;

    var imgs = Array.prototype.slice.call(panel.querySelectorAll('img:not(.lb-processed)'));
    if (imgs.length === 0) return;

    // ---- Step 1: 扫描直接子节点，合并连续的"图片主导段落"为 gallery ----
    var children = Array.prototype.slice.call(panel.children);
    var i = 0;
    while (i < children.length) {
      var child = children[i];
      // 跳过非 P、或 P 不含图片
      if (child.tagName !== 'P') { i++; continue; }
      var info = isImgDominant(child);
      if (!info.ok) { i++; continue; }

      // 找到了起点，收集连续的图片主导段落（中间最多允许一个非图片段间隔？这里严格要求相邻）
      var groupPs = [child];
      var groupImgCount = info.count;
      var j = i + 1;
      while (j < children.length) {
        var p2 = children[j];
        if (p2.tagName !== 'P') break;
        var info2 = isImgDominant(p2);
        if (!info2.ok) break;
        groupPs.push(p2);
        groupImgCount += info2.count;
        j++;
      }

      if (groupImgCount >= 1) {
        // 用 IIFE 隔离作用域，防止后续 gallery 覆盖 groupImgs 引用
        (function (groupPs, groupImgCount) {
          // 收集这些段中的全部 img（保持文档顺序）
          var groupImgs = [];
          groupPs.forEach(function (gp) {
            Array.prototype.slice.call(gp.querySelectorAll('img')).forEach(function (img) {
              groupImgs.push(img);
            });
          });

          // 对每个 img 包裹 .img-gallery-item 并绑定事件
          groupImgs.forEach(function (img, idx) {
            var wrap = document.createElement('div');
            wrap.className = 'img-gallery-item';
            img.parentNode.insertBefore(wrap, img);
            wrap.appendChild(img);
            // 图片加载失败时显示占位符，不隐藏整个 item
            img.addEventListener('error', function () {
              img.style.display = 'none';
              wrap.classList.add('img-failed');
            });
            // 处理已经加载完成但失败的图片（error 事件已触发，不会再触发）
            if (img.complete && img.naturalWidth === 0) {
              img.style.display = 'none';
              wrap.classList.add('img-failed');
            }
            // 角标（第一个显示 N 图）
            if (groupImgs.length >= 2) {
              if (idx === 0) {
                var badge = document.createElement('span');
                badge.className = 'img-gallery-badge';
                badge.textContent = groupImgs.length + ' 图';
                wrap.appendChild(badge);
              }
              var zoom = document.createElement('span');
              zoom.className = 'img-gallery-badge zoom';
              zoom.innerHTML = '&#128269; 放大';
              wrap.appendChild(zoom);
            }
            // 闭包捕获当前 groupImgs 和 idx
            (function (imgs, index) {
              wrap.addEventListener('click', function () {
                openLightbox(imgs, index);
              });
            })(groupImgs.slice(), idx);
          });

          // 创建 gallery 容器并插入
          var gallery = document.createElement('div');
          gallery.className = 'img-gallery';
          groupImgs.forEach(function (img) {
            gallery.appendChild(img.parentNode); // .img-gallery-item
          });
          // 替换第一个段为 gallery，并移除其余段落（它们的 img 已被取走）
          var firstP = groupPs[0];
          firstP.parentNode.insertBefore(gallery, firstP);
          groupPs.forEach(function (gp) { if (gp.parentNode) gp.parentNode.removeChild(gp); });
        })(groupPs.slice(), groupImgCount);
      }

      i = j;
    }

    // ---- Step 2: 剩余的独立单图（不在 gallery 内）→ .img-single + 点击放大 ----
    var remaining = Array.prototype.slice.call(panel.querySelectorAll('img'));
    remaining.forEach(function (img) {
      if (img.closest('.img-gallery-item')) return;
      if (img.closest('.img-single')) return; // 已包裹
      // 图片加载失败时隐藏
      img.addEventListener('error', function () {
        img.style.display = 'none';
      });
      // 处理已经加载完成但失败的图片（error 事件已触发，不会再触发）
      if (img.complete && img.naturalWidth === 0) {
        img.style.display = 'none';
      }
      var wrap = document.createElement('span');
      wrap.className = 'img-single';
      img.parentNode.insertBefore(wrap, img);
      wrap.appendChild(img);
      wrap.addEventListener('click', function () {
        openLightbox([img], 0);
      });
    });
  }

  function openLightbox(images, startIndex) {
    lbImages = images.slice();
    lbIndex = startIndex || 0;
    var lb = $('#imgLightbox');
    var lbImg = $('#imgLbImg');
    var lbCap = $('#imgLbCaption');
    var lbCnt = $('#imgLbCounter');
    var btnPrev = $('#imgLbPrev');
    var btnNext = $('#imgLbNext');

    function render() {
      var img = lbImages[lbIndex];
      if (!img) return;
      lbImg.src = img.src;
      lbImg.alt = img.alt || '';
      lbCap.textContent = img.alt || '';
      lbCnt.textContent = (lbIndex + 1) + ' / ' + lbImages.length;
      btnPrev.disabled = (lbIndex <= 0);
      btnNext.disabled = (lbIndex >= lbImages.length - 1);
    }

    render();
    lb.classList.add('show');
    document.body.style.overflow = 'hidden';

    // 关闭逻辑
    function closeLb() {
      lb.classList.remove('show');
      document.body.style.overflow = '';
      lbImg.src = '';
    }

    // 按钮
    btnPrev.onclick = function () { if (lbIndex > 0) { lbIndex--; render(); } };
    btnNext.onclick = function () { if (lbIndex < lbImages.length - 1) { lbIndex++; render(); } };
    $('#imgLbClose').onclick = closeLb;
    // 点击背景关闭
    lb.onclick = function (e) {
      if (e.target === lb || e.target.classList.contains('img-lb-wrap')) closeLb();
    };
    // Esc 关闭
    document.removeEventListener('keydown', lbKeyHandler);
    document.addEventListener('keydown', lbKeyHandler);
    function lbKeyHandler(e) {
      if (e.key === 'Escape') { closeLb(); document.removeEventListener('keydown', lbKeyHandler); }
      if (e.key === 'ArrowLeft')  { if (lbIndex > 0) { lbIndex--; render(); } }
      if (e.key === 'ArrowRight') { if (lbIndex < lbImages.length - 1) { lbIndex++; render(); } }
    }
  }

  // ---------- Toast ----------

  var toastTimer;
  function showToast(msg) {
    var toast = $('#toast');
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove('show'); }, 2000);
  }

  return {
    renderAll: renderAll,
    renderCards: renderCards,
    renderSidebar: renderSidebar,
    renderReadingView: renderReadingView,
    closeReadingView: closeReadingView,
    renderSheet: renderSheet,
    closeSheet: closeSheet,
    renderTagBox: renderTagBox,
    getTags: getTags,
    setTags: setTags,
    showExtracting: showExtracting,
    showExtractResult: showExtractResult,
    showFetchedTitle: showFetchedTitle,
    showConfirm: showConfirm,
    hideConfirm: hideConfirm,
    showToast: showToast,
    escapeHtml: escapeHtml,
    fmtTime: fmtTime,
    uid: uid,
    syncCatSelect: syncCatSelect,
    setCatSelectOpen: setCatSelectOpen,
    selectCatByIndex: selectCatByIndex,
  };
})();
