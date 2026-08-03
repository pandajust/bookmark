/**
 * extractor.js
 * ContentExtractor — 网页正文提取前端代理
 * 职责：通过后端 /api/extract 接口触发服务端抓取与正文提取。
 *       服务端实现 SSRF 防护、HTML 评分、HTML→Markdown 转换。
 *       本模块只负责发起请求与错误归一化，不直接处理 HTML。
 * 暴露：全局变量 ContentExtractor
 */
'use strict';

const ContentExtractor = (function () {

  // 校验 http/https URL（前端预校验，后端会再校验一次）
  function isValidUrl(str) {
    if (typeof str !== 'string') return false;
    const s = str.trim();
    if (!s) return false;
    if (!/^https?:\/\//i.test(s)) return false;
    try {
      const u = new URL(s);
      return u.protocol === 'http:' || u.protocol === 'https:';
    } catch (e) {
      return false;
    }
  }

  // 从 URL 提取主机名（去掉 www.）用于标题兜底
  function getHostname(url) {
    try {
      const u = new URL(url);
      let host = u.hostname || '';
      if (host.indexOf('www.') === 0) host = host.slice(4);
      return host;
    } catch (e) {
      return '';
    }
  }

  // 调用后端 /api/extract 进行抓取与转换
  // 返回统一结果对象 { success, title, description, markdown, error }
  async function extract(url) {
    if (!isValidUrl(url)) {
      return { success: false, error: '无效的 URL（仅支持 http/https）' };
    }
    try {
      const resp = await fetch('/api/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url }),
      });
      const data = await resp.json();
      // 后端已保证返回结构 { success, title?, description?, markdown?, error? }
      if (data && data.success) {
        return {
          success: true,
          title: data.title || '',
          description: data.description || '',
          markdown: data.markdown || '',
        };
      }
      return {
        success: false,
        error: (data && data.error) || '抓取失败',
      };
    } catch (e) {
      return {
        success: false,
        error: '网络错误：' + (e.message || '无法连接服务器'),
      };
    }
  }

  return {
    extract: extract,
    isValidUrl: isValidUrl,
    getHostname: getHostname,
  };
})();
