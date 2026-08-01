/**
 * State — 应用状态管理
 *
 * 集中管理应用所有可变状态，提供 getter/setter，
 * 状态变更时通知订阅者刷新 UI。
 *
 * @module AppState
 */
'use strict';

const AppState = (function () {

  // ---------- 内部状态 ----------
  let bookmarks = [];
  let currentCat = 'all';
  let currentTag = null;
  let searchQuery = '';
  let editingId = null;
  let deleteTargetId = null;
  let currentView = 'grid';      // grid | list
  let currentTab = 'render';     // render | source（阅读视图标签）
  let readingId = null;          // 当前正在阅读的书签 ID

  const CATEGORIES = { all: '全部', tech: '技术', design: '设计', read: '阅读', tool: '工具' };
  const FAV_COLORS = ['b1', 'b2', 'b3', 'b4'];
  const CAT_COLORS = { tech: 'b1', design: 'b2', read: 'b3', tool: 'b4' };
  const TAG_COLORS = ['#007AFF', '#5856D6', '#34C759', '#FF9500', '#FF3B30', '#AF52DE', '#FF2D55', '#00C7BE'];

  // ---------- 筛选与排序 ----------

  function getFiltered() {
    let list = bookmarks;

    if (currentCat !== 'all') {
      list = list.filter(function (b) { return b.category === currentCat; });
    }
    if (currentTag) {
      list = list.filter(function (b) { return (b.tags || []).indexOf(currentTag) !== -1; });
    }
    // 搜索文本过滤已迁移至后端 API，此处只保留分类/标签本地筛选
    return list.sort(function (a, b) { return b.createdAt - a.createdAt; });
  }

  // ---------- Getters ----------

  function getBookmarks() { return bookmarks; }
  function getCurrentCat() { return currentCat; }
  function getCurrentTag() { return currentTag; }
  function getSearchQuery() { return searchQuery; }
  function getEditingId() { return editingId; }
  function getDeleteTargetId() { return deleteTargetId; }
  function getCurrentView() { return currentView; }
  function getCurrentTab() { return currentTab; }
  function getReadingId() { return readingId; }
  function getCategories() { return CATEGORIES; }
  function getFavColors() { return FAV_COLORS; }
  function getCatColors() { return CAT_COLORS; }
  function getTagColors() { return TAG_COLORS; }

  function getBookmarkById(id) {
    // 容许字符串/数字 id 混用：DOM data-id 是字符串，后端返回的是数字
    var sid = String(id);
    return bookmarks.find(function (b) { return String(b.id) === sid; });
  }

  // ---------- Setters ----------

  function setBookmarks(list) {
    bookmarks = (list || []).map(function (b) {
      // 后端 tags 格式为 [{id, name}]，前端只需要字符串数组
      var rawTags = b.tags || [];
      var strTags = rawTags.map(function (t) {
        return (t != null && typeof t === 'object') ? (t.name || '') : String(t);
      }).filter(function (s) { return s; });
      return Object.assign({}, b, { tags: strTags });
    });
  }
  function setCat(cat) { currentCat = cat; }
  function setTag(tag) { currentTag = tag; }
  function setSearch(q) { searchQuery = q; }
  function setEditingId(id) { editingId = id; }
  function setDeleteTargetId(id) { deleteTargetId = id; }
  function setView(view) { currentView = view; }
  function setTab(tab) { currentTab = tab; }
  function setReadingId(id) { readingId = id; }

  return {
    getFiltered: getFiltered,
    getBookmarks: getBookmarks,
    getCurrentCat: getCurrentCat,
    getCurrentTag: getCurrentTag,
    getSearchQuery: getSearchQuery,
    getEditingId: getEditingId,
    getDeleteTargetId: getDeleteTargetId,
    getCurrentView: getCurrentView,
    getCurrentTab: getCurrentTab,
    getReadingId: getReadingId,
    getCategories: getCategories,
    getFavColors: getFavColors,
    getCatColors: getCatColors,
    getTagColors: getTagColors,
    getBookmarkById: getBookmarkById,
    setBookmarks: setBookmarks,
    setCat: setCat,
    setTag: setTag,
    setSearch: setSearch,
    setEditingId: setEditingId,
    setDeleteTargetId: setDeleteTargetId,
    setView: setView,
    setTab: setTab,
    setReadingId: setReadingId,
  };
})();
