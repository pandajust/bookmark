/**
 * storage.js
 * StorageManager — 书签数据 REST API 客户端
 * 职责：通过 HTTP 调用后端 server.py 提供的 REST API 完成数据持久化。
 *       后端使用 SQLite 存储，本模块只负责网络请求与错误归一化。
 * 暴露：全局变量 StorageManager
 */
'use strict';

const StorageManager = (function () {
  const API = '/api';

  // ---------- 通用请求封装 ----------

  async function request(method, path, body) {
    const opts = {
      method: method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined && body !== null) {
      opts.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(API + path, opts);
    } catch (e) {
      const err = new Error('网络错误：' + (e.message || '无法连接服务器'));
      err.status = 0;
      throw err;
    }
    if (resp.status === 204) return null;
    let payload = null;
    try {
      payload = await resp.json();
    } catch (e) {
      // 非 JSON 响应
    }
    if (!resp.ok) {
      const msg = (payload && payload.error) || ('HTTP ' + resp.status);
      const err = new Error(msg);
      err.status = resp.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  // ---------- 初始化（探测后端连通性） ----------

  async function init() {
    try {
      await request('GET', '/stats');
      return { ok: true, useIndexedDB: false };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  // ---------- CRUD ----------

  async function getAll() {
    const r = await request('GET', '/bookmarks');
    return (r && r.bookmarks) || [];
  }

  async function getById(id) {
    try {
      const r = await request('GET', '/bookmarks/' + id);
      return (r && r.bookmark) || null;
    } catch (e) {
      if (e.status === 404) return null;
      throw e;
    }
  }

  async function add(bookmark) {
    // 后端会忽略前端提供的 id，使用 SQLite 自增主键
    const payload = {
      url: bookmark.url,
      title: bookmark.title,
      category: bookmark.category || 'tech',
      tags: bookmark.tags || [],
    };
    const r = await request('POST', '/bookmarks', payload);
    return (r && r.bookmark) || null;
  }

  async function update(id, patch) {
    try {
      const r = await request('PUT', '/bookmarks/' + id, patch);
      return (r && r.bookmark) || null;
    } catch (e) {
      if (e.status === 404) return null;
      throw e;
    }
  }

  async function remove(id) {
    try {
      await request('DELETE', '/bookmarks/' + id);
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---------- 搜索与筛选 ----------

  async function search(query, filters) {
    const f = filters || {};
    const params = [];
    if (query && query.trim()) params.push('q=' + encodeURIComponent(query.trim()));
    if (f.category && f.category !== 'all') params.push('category=' + encodeURIComponent(f.category));
    if (f.tag) params.push('tag=' + encodeURIComponent(f.tag));
    const qs = params.length ? '?' + params.join('&') : '';
    const r = await request('GET', '/bookmarks' + qs);
    return (r && r.bookmarks) || [];
  }

  async function getByCategory(category) {
    const r = await request('GET', '/bookmarks?category=' + encodeURIComponent(category));
    return (r && r.bookmarks) || [];
  }

  async function getByTag(tag) {
    const r = await request('GET', '/bookmarks?tag=' + encodeURIComponent(tag));
    return (r && r.bookmarks) || [];
  }

  async function getAllTags() {
    const r = await request('GET', '/tags');
    return (r && r.tags) || [];
  }

  async function getCategoryCounts() {
    const r = await request('GET', '/stats');
    return (r && r.counts) || { all: 0, tech: 0, design: 0, read: 0, tool: 0 };
  }

  // ---------- 重试抓取 ----------

  async function retry(id) {
    try {
      await request('POST', '/bookmarks/retry', { id: id });
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---------- 导入导出 ----------

  async function exportData() {
    const all = await getAll();
    return {
      version: 1,
      exportedAt: Date.now(),
      bookmarks: all,
    };
  }

  async function importData(json) {
    let data = json;
    if (typeof json === 'string') {
      data = JSON.parse(json);
    }
    let bookmarks = [];
    if (data && Array.isArray(data.bookmarks)) {
      bookmarks = data.bookmarks;
    } else if (Array.isArray(data)) {
      bookmarks = data;
    }
    let count = 0;
    for (let i = 0; i < bookmarks.length; i++) {
      const b = bookmarks[i];
      if (b && b.url) {
        try {
          await add({
            url: b.url,
            title: b.title,
            category: b.category,
            tags: b.tags || [],
          });
          count++;
        } catch (e) {
          // 重复 URL 跳过
        }
      }
    }
    return count;
  }

  async function exportMarkdownFile(bookmark) {
    try {
      var res = await fetch('/api/export/markdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: bookmark && bookmark.id ? bookmark.id : undefined,
          title: bookmark ? bookmark.title : '',
          markdown: bookmark ? bookmark.markdown : '',
        }),
      });
      if (!res.ok) {
        var j = await res.json().catch(function () { return {}; });
        throw new Error((j && j.error) || '导出失败');
      }
      return await res.json();
    } catch (e) {
      throw e;
    }
  }

  return {
    init: init,
    getAll: getAll,
    getById: getById,
    add: add,
    update: update,
    remove: remove,
    search: search,
    getByCategory: getByCategory,
    getByTag: getByTag,
    getAllTags: getAllTags,
    getCategoryCounts: getCategoryCounts,
    retry: retry,
    exportData: exportData,
    importData: importData,
    exportMarkdownFile: exportMarkdownFile,
  };
})();
