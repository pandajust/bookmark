/**
 * App — 应用入口与编排器
 *
 * 负责初始化所有模块，加载持久化数据，
 * 绑定事件，提供全局重载接口。
 *
 * @module App
 */
'use strict';

const App = (function () {

  // ---------- 初始化 ----------

  async function init() {
    try {
      // 应用已保存的主题
      var savedTheme = 'blue';
      try { savedTheme = localStorage.getItem('bookmark-hub-theme') || 'blue'; } catch (e) {}
      document.documentElement.setAttribute('data-theme', savedTheme);

      // 初始化存储层
      await StorageManager.init();

      // 加载数据到状态
      await reload();

      // 绑定所有事件
      Events.bindAll();

      // 首次渲染
      Renderer.renderAll();

      console.log('[App] 初始化完成，共 ' + AppState.getBookmarks().length + ' 条收藏');
    } catch (e) {
      console.error('[App] 初始化失败:', e);
    }
  }

  // ---------- 重新从存储加载 ----------

  async function reload() {
    var bookmarks = await StorageManager.getAll();
    AppState.setBookmarks(bookmarks || []);
    Renderer.renderAll();
  }

  // ---------- 启动 ----------

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return {
    init: init,
    reload: reload,
  };
})();
