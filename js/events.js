/**
 * Events — 事件绑定与用户交互处理
 *
 * 负责绑定所有 DOM 事件，处理用户操作逻辑，
 * 调用 Renderer 刷新 UI、调用 StorageManager 持久化数据。
 * 抓取逻辑已下沉到服务端，本模块只负责触发与回显。
 *
 * @module Events
 */
'use strict';

const Events = (function () {

  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return document.querySelectorAll(s); };

  // ---------- 保存书签 ----------

  async function handleSave() {
    var url = $('#inpUrl').value.trim();
    var title = $('#inpTitle').value.trim();

    if (!url) { Renderer.showToast('请输入网址'); return; }
    if (!ContentExtractor.isValidUrl(url)) {
      Renderer.showToast('请输入有效的网址（http:// 或 https://）');
      return;
    }

    var editingId = AppState.getEditingId();
    var category = $('#inpCat').value;
    var tags = Renderer.getTags();

    try {
      if (editingId) {
        // 编辑模式：标题必填
        if (!title) { Renderer.showToast('请输入标题'); return; }
        await StorageManager.update(editingId, {
          url: url, title: title, category: category, tags: tags
        });
        Renderer.closeSheet();
        await App.reload();
        Renderer.showToast('已更新');
      } else {
        // 新建模式：后端会自动后台抓取正文，无需前端调用 fetchAndExtract
        // 标题可空，后端会使用 hostname 兜底
        await StorageManager.add({
          url: url,
          title: title || ContentExtractor.getHostname(url),
          category: category,
          tags: tags,
        });
        Renderer.closeSheet();
        await App.reload();
        Renderer.showToast('已收藏，正在后台提取正文...');

        // 后端抓取是异步的，2.5 秒后再刷新一次让结果可见
        setTimeout(function () { App.reload(); }, 2500);
      }
    } catch (e) {
      // 409 = URL 已存在
      if (e && e.status === 409) {
        Renderer.showToast('该网址已存在');
        return;
      }
      Renderer.showToast('保存失败：' + (e.message || '未知错误'));
    }
  }

  // ---------- 重试抓取（阅读视图用） ----------

  async function handleRetry(bookmarkId) {
    Renderer.showToast('正在重新提取...');
    await StorageManager.retry(bookmarkId);
    // 后端抓取异步，2.5 秒后刷新
    setTimeout(async function () {
      await App.reload();
      // 若仍停留在该阅读视图，重新渲染
      if (AppState.getReadingId() == bookmarkId) {
        Renderer.renderReadingView(bookmarkId);
        bindReadingButtons(AppState.getBookmarkById(bookmarkId));
      }
      Renderer.showToast('已重新提取');
    }, 2500);
  }

  // ---------- URL 输入时自动抓取标题（预览） ----------

  var titleFetchTimer = null;
  function handleUrlInput() {
    var url = $('#inpUrl').value.trim();
    clearTimeout(titleFetchTimer);

    if (!ContentExtractor.isValidUrl(url)) return;
    if (AppState.getEditingId()) return; // 编辑模式不预览
    if ($('#inpTitle').value.trim()) return; // 用户已手动输入标题

    titleFetchTimer = setTimeout(async function () {
      Renderer.showExtracting();
      var result = await ContentExtractor.extract(url);
      Renderer.showExtractResult(result);

      if (result.success && result.title) {
        Renderer.showFetchedTitle(result.title);
      }
    }, 800);
  }

  // ---------- 删除 ----------

  async function handleDelete() {
    var id = AppState.getDeleteTargetId();
    if (!id) return;
    await StorageManager.remove(id);
    Renderer.hideConfirm();
    // 如果在阅读视图中，关闭它
    if (String(AppState.getReadingId()) === String(id)) {
      Renderer.closeReadingView();
    }
    await App.reload();
    Renderer.showToast('已删除');
  }

  // ---------- 导出 Markdown ----------

  function exportMarkdown(b) {
    var md = b.markdown || ('# ' + (b.title || '') + '\n\n暂无正文内容');
    var blob = new Blob([md], { type: 'text/markdown' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (b.title || 'bookmark') + '.md';
    a.click();
    URL.revokeObjectURL(url);
    Renderer.showToast('已导出 Markdown');
  }

  // ---------- 阅读视图按钮 ----------

  function bindReadingButtons(b) {
    $('#btnEditRead').onclick = function () { openSheet(b); };
    $('#btnExportRead').onclick = function () { exportMarkdown(b); };
    $('#btnDeleteRead').onclick = function () {
      AppState.setDeleteTargetId(b.id);
      Renderer.showConfirm(b.id, b.title);
    };
    // 重试按钮（若存在）
    var btnRetry = document.getElementById('btnRetryRead');
    if (btnRetry) {
      btnRetry.onclick = function () { handleRetry(b.id); };
    }
  }

  // ---------- 打开 Sheet ----------

  function openSheet(bookmark) {
    AppState.setEditingId(bookmark ? bookmark.id : null);
    Renderer.renderSheet(bookmark);
  }

  // ---------- 自定义分类下拉组件交互 ----------

  function bindCatSelect() {
    var wrap = document.getElementById('catSelect');
    if (!wrap) return;

    // 点击头部切换
    wrap.addEventListener('click', function (e) {
      // 如果点到选项，由选项事件处理
      if (e.target.closest('.catselect-opt')) return;
      var head = e.target.closest('.catselect-head');
      if (!head) return;
      e.stopPropagation();
      var isOpen = wrap.classList.contains('open');
      Renderer.setCatSelectOpen(!isOpen);
    });

    // 选项点击选中
    var menu = document.getElementById('catSelectMenu');
    if (menu) {
      menu.addEventListener('click', function (e) {
        var opt = e.target.closest('.catselect-opt');
        if (!opt) return;
        e.stopPropagation();
        var val = opt.getAttribute('data-val');
        Renderer.syncCatSelect(val);
        Renderer.setCatSelectOpen(false);
      });
    }

    // 键盘操作
    wrap.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        var isOpen = wrap.classList.contains('open');
        if (!isOpen) {
          Renderer.setCatSelectOpen(true);
        } else {
          // 已打开时 Enter 不做什么，选项已经被选中
        }
      } else if (e.key === 'Escape') {
        Renderer.setCatSelectOpen(false);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!wrap.classList.contains('open')) {
          Renderer.setCatSelectOpen(true);
        } else {
          Renderer.selectCatByIndex(1);
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (wrap.classList.contains('open')) {
          Renderer.selectCatByIndex(-1);
        }
      }
    });

    // 聚焦/失焦时高亮头部
    wrap.addEventListener('focus', function () { /* noop, rely on CSS :focus-visible */ }, true);

    // 点击外部关闭下拉
    setTimeout(function () {
      document.addEventListener('click', function (e) {
        if (!wrap.classList.contains('open')) return;
        // 如果点击在下拉组件外，关闭之
        var inCat = e.target.closest('#catSelect');
        if (!inCat) Renderer.setCatSelectOpen(false);
      });
    }, 0);
  }

  // ---------- 搜索（防抖 + 后端 API） ----------

  var searchTimer = null;
  function performSearch(query) {
    if (!query) {
      // 清空搜索：重新加载全部书签
      AppState.setSearch('');
      App.reload();
      return;
    }
    AppState.setSearch(query);
    // 调用后端搜索 API
    StorageManager.search(query, {
      category: AppState.getCurrentCat(),
      tag: AppState.getCurrentTag()
    }).then(function (results) {
      AppState.setBookmarks(results);
      Renderer.renderAll();
    }).catch(function (e) {
      Renderer.showToast('搜索失败');
    });
  }

  // ---------- 绑定所有事件 ----------

  function bindAll() {

    // 自定义分类下拉
    bindCatSelect();

    // 添加按钮
    $('#btnAdd2').addEventListener('click', function () { openSheet(null); });

    // Sheet 操作
    $('#btnSheetClose').addEventListener('click', Renderer.closeSheet);
    $('#btnSheetCancel').addEventListener('click', Renderer.closeSheet);
    $('#btnSheetSave').addEventListener('click', handleSave);

    // URL 输入自动抓取
    $('#inpUrl').addEventListener('input', handleUrlInput);

    // 阅读视图返回
    $('#btnBack').addEventListener('click', function () {
      Renderer.closeReadingView();
    });

    // 原网页打开（仅当 URL 为可跳转的有效链接时才放行）
    $('#btnOpenOrig').addEventListener('click', function () {
      var b = AppState.getBookmarkById(AppState.getReadingId());
      if (b && ContentExtractor.isValidUrl(b.url)) window.open(b.url, '_blank');
    });

    // 阅读视图标签切换
    $('#readView').querySelector('.read-top').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-tab]');
      if (!btn) return;
      var tabs = $('#readView').querySelectorAll('[data-tab]');
      tabs.forEach(function (t) { t.classList.remove('on'); t.setAttribute('aria-selected', 'false'); });
      btn.classList.add('on');
      btn.setAttribute('aria-selected', 'true');
      var key = btn.getAttribute('data-tab');
      $('#panelRender').classList.toggle('show', key === 'render');
      $('#panelSource').classList.toggle('show', key === 'source');
    });

    // 卡片点击 -> 打开阅读视图（事件委托）
    $('#cardGrid').addEventListener('click', function (e) {
      if (e.target.closest('.ltag')) return;
      var card = e.target.closest('.lcard');
      if (!card) return;
      var id = card.getAttribute('data-id');
      var b = AppState.getBookmarkById(id);
      if (!b) return;
      // 非可跳转链接（空、javascript:、非 http/https 等）不打开展示页
      if (!ContentExtractor.isValidUrl(b.url)) {
        Renderer.showToast('该网址不可访问，无法展示正文');
        return;
      }
      AppState.setReadingId(b.id);
      Renderer.renderReadingView(b.id);
      bindReadingButtons(b);
    });

    // 确认对话框
    $('#btnConfirmCancel').addEventListener('click', Renderer.hideConfirm);
    $('#btnConfirmOk').addEventListener('click', handleDelete);

    // 侧边栏分类
    $$('#sidebar .sitem').forEach(function (el) {
      el.addEventListener('click', function () {
        $$('#sidebar .sitem').forEach(function (x) { x.classList.remove('is-on'); });
        el.classList.add('is-on');
        AppState.setCat(el.getAttribute('data-cat'));
        AppState.setTag(null);
        // 若当前有搜索查询，则带新分类重新搜索；否则本地渲染
        if (AppState.getSearchQuery()) {
          performSearch(AppState.getSearchQuery());
        } else {
          Renderer.renderAll();
        }
      });
    });

    // 侧边栏搜索（250ms 防抖，走后端 API）
    $('#sideSearch').addEventListener('input', function (e) {
      clearTimeout(searchTimer);
      var val = e.target.value.trim();
      searchTimer = setTimeout(function () {
        performSearch(val);
      }, 250);
    });

    // 视图切换（网格/列表）
    $$('#dashboard .seg button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        $$('#dashboard .seg button').forEach(function (x) { x.classList.remove('on'); });
        btn.classList.add('on');
        var view = btn.getAttribute('data-view');
        AppState.setView(view);
        $('#cardGrid').style.gridTemplateColumns = view === 'list' ? '1fr' : '';
      });
    });

    // 侧边栏标签点击（事件委托）
    $('#tagList').addEventListener('click', function (e) {
      var el = e.target.closest('.stag');
      if (!el) return;
      var tag = el.getAttribute('data-tag');
      var currentTag = AppState.getCurrentTag();
      AppState.setTag(currentTag === tag ? null : tag);
      // 若当前有搜索查询，则带新标签重新搜索；否则本地渲染
      if (AppState.getSearchQuery()) {
        performSearch(AppState.getSearchQuery());
      } else {
        Renderer.renderAll();
      }
    });

    // Sheet overlay 点击关闭
    $('#sheetOverlay').addEventListener('click', function (e) {
      if (e.target === $('#sheetOverlay')) Renderer.closeSheet();
    });

    // Confirm overlay 点击关闭
    $('#confirmOverlay').addEventListener('click', function (e) {
      if (e.target === $('#confirmOverlay')) Renderer.hideConfirm();
    });

    // 主题切换按钮
    $$('.traffic .t-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var theme = btn.getAttribute('data-theme');
        if (!theme) return;
        document.documentElement.setAttribute('data-theme', theme);
        try { localStorage.setItem('bookmark-hub-theme', theme); } catch (e) {}
      });
    });

    // 键盘快捷键
    document.addEventListener('keydown', function (e) {
      // Esc 依次关闭确认/Sheet/阅读视图
      if (e.key === 'Escape') {
        if ($('#confirmOverlay').classList.contains('show')) {
          Renderer.hideConfirm();
        } else if ($('#sheetOverlay').classList.contains('show')) {
          Renderer.closeSheet();
        } else if ($('#readView').classList.contains('show')) {
          Renderer.closeReadingView();
        }
      }
      // Cmd/Ctrl + N 新建收藏（与参考文件一致）
      if ((e.metaKey || e.ctrlKey) && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault();
        openSheet(null);
      }
      // Cmd/Ctrl + K 聚焦搜索
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        $('#sideSearch').focus();
      }
    });
  }

  return {
    bindAll: bindAll,
    openSheet: openSheet,
    handleSave: handleSave,
    handleDelete: handleDelete,
    handleRetry: handleRetry,
  };
})();
