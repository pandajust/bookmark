/**
 * markdown.js
 * MarkdownRenderer — 完整 Markdown 渲染器（不依赖外部库）
 * 职责：将 Markdown 字符串渲染为安全的 HTML 字符串。
 *       支持：标题、段落、粗体/斜体、行内代码、链接、图片、
 *             有序/无序列表、引用、代码块、分割线、表格、删除线。
 * 暴露：全局变量 MarkdownRenderer
 */
'use strict';

const MarkdownRenderer = (function () {

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---- 内联解析 ----
  function renderInline(md) {
    if (!md) return '';
    var result = md;

    // 代码（最高优先级，防止代码内的 * _ ` 被误解析）
    result = result.replace(/`([^`]+)`/g, function (m, code) {
      return '<code>' + escapeHtml(code) + '</code>';
    });

    // 图片 ![alt](url)
    // 不使用 loading="lazy"，避免阅读视图内图片被延迟加载导致用户认为"不显示"
    result = result.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (m, alt, url) {
      return '<img src="' + escapeHtml(url) + '" alt="' + escapeHtml(alt) + '">';
    });

    // 链接 [text](url)
    result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (m, text, url) {
      return '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + text + '</a>';
    });

    // 粗斜体 ***text*** 或 ___text___（必须在粗体/斜体之前处理）
    result = result.replace(/\*\*\*([^*\n]+?)\*\*\*/g, function (m, content) {
      if (!content.trim()) return m;
      return '<strong><em>' + content + '</em></strong>';
    });
    result = result.replace(/___([^_\n]+?)___/g, function (m, content) {
      if (!content.trim()) return m;
      return '<strong><em>' + content + '</em></strong>';
    });

    // 粗体 **text** 或 __text__（跳过纯空白内容）
    result = result.replace(/\*\*([^*\n]+?)\*\*/g, function (m, content) {
      if (!content.trim()) return m;
      return '<strong>' + content + '</strong>';
    });
    result = result.replace(/__([^_\n]+?)__/g, function (m, content) {
      if (!content.trim()) return m;
      return '<strong>' + content + '</strong>';
    });

    // 斜体 *text* 或 _text_（跳过纯空白内容）
    result = result.replace(/\*([^*\n]+?)\*/g, function (m, content) {
      if (!content.trim()) return m;
      return '<em>' + content + '</em>';
    });
    result = result.replace(/_([^_\n]+?)_/g, function (m, content) {
      if (!content.trim()) return m;
      return '<em>' + content + '</em>';
    });

    // 删除线 ~~text~~
    result = result.replace(/~~([^~\n]+?)~~/g, function (m, content) {
      if (!content.trim()) return m;
      return '<del>' + content + '</del>';
    });

    // 清理残留的连续 * 或 _ （原 HTML 装饰字符，非 Markdown 语法）
    // 移除所有未被匹配为格式的 ** 及以上序列；保留单个 * （可能为合法文本如 3*4=12）
    result = result.replace(/\*{2,}/g, '');
    result = result.replace(/_{2,}/g, '');

    return result;
  }

  // ---- 块级解析 ----
  function render(md, title) {
    if (!md) {
      return '<h1>' + escapeHtml(title) + '</h1><div class="sub">暂无正文内容</div>';
    }
    var lines = md.split('\n');
    var html = '';
    var i = 0;

    function closeList(listType) {
      if (listType === 'ul') html += '</ul>';
      else if (listType === 'ol') html += '</ol>';
      return null;
    }

    var listType = null;
    var listCounter = 0;
    var listIndent = 0;
    var inBlockquote = false;
    var inCodeBlock = false;
    var codeLang = '';
    var codeBuffer = [];
    var tableRows = [];
    var inTable = false;

    function flushTable() {
      if (tableRows.length === 0) return;
      html += '<table>';
      for (var r = 0; r < tableRows.length; r++) {
        var cells = tableRows[r];
        html += r === 0 ? '<thead><tr>' : (r === 1 ? '</thead><tbody><tr>' : '<tr>');
        for (var c = 0; c < cells.length; c++) {
          html += (r === 0 ? '<th>' : '<td>') + renderInline(cells[c]) + (r === 0 ? '</th>' : '</td>');
        }
        html += '</tr>';
      }
      html += '</tbody></table>';
      tableRows = [];
      inTable = false;
    }

    while (i < lines.length) {
      var line = lines[i];

      // 代码块
      if (line.trim().startsWith('```')) {
        if (inCodeBlock) {
          if (listType) { listType = closeList(listType); }
          if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
          html += '<pre><code' + (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : '') + '>' + escapeHtml(codeBuffer.join('\n')) + '</code></pre>';
          codeBuffer = [];
          codeLang = '';
          inCodeBlock = false;
        } else {
          if (listType) { listType = closeList(listType); }
          if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
          if (inTable) flushTable();
          inCodeBlock = true;
          codeLang = line.trim().slice(3).trim();
          codeBuffer = [];
        }
        i++;
        continue;
      }

      if (inCodeBlock) {
        codeBuffer.push(line);
        i++;
        continue;
      }

      // 空行
      if (line.trim() === '') {
        if (listType) { listType = closeList(listType); }
        if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
        if (inTable) flushTable();
        i++;
        continue;
      }

      // 表格行（以 | 开头和结尾）
      if (line.indexOf('|') > -1 && line.replace(/\s+/g, '') !== '' && /^\|.*\|$/.test(line.trim())) {
        if (!inTable) {
          if (listType) { listType = closeList(listType); }
          if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
          inTable = true;
          tableRows = [];
        }
        var cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) { return c.trim(); });
        // 跳过分隔行（|---|---|）
        if (cells.length > 0 && /^-+$/.test(cells[0].replace(/\s+/g, ''))) {
          i++;
          continue;
        }
        tableRows.push(cells);
        i++;
        continue;
      } else if (inTable) {
        flushTable();
      }

      // 分割线 ---, ***, ___
      if (/^\s*([-*_])\s*\1\s*\1[\s\S]*$/.test(line) && /^\s*[-*_\s]+$/.test(line)) {
        if (listType) { listType = closeList(listType); }
        if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
        html += '<hr>';
        i++;
        continue;
      }

      // 标题
      var hMatch = line.match(/^(#{1,6})\s+(.+)/);
      if (hMatch) {
        if (listType) { listType = closeList(listType); }
        if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
        if (inTable) flushTable();
        var level = hMatch[1].length;
        html += '<h' + level + '>' + renderInline(hMatch[2]) + '</h' + level + '>';
        i++;
        continue;
      }

      // 引用
      if (line.startsWith('> ')) {
        if (listType) { listType = closeList(listType); }
        if (inTable) flushTable();
        if (!inBlockquote) {
          html += '<blockquote>';
          inBlockquote = true;
        }
        html += '<p>' + renderInline(line.slice(2)) + '</p>';
        i++;
        continue;
      }

      // 无序列表
      var ulMatch = line.match(/^(\s*)[-*+]\s+(.+)/);
      if (ulMatch) {
        var indent = ulMatch[1].replace(/\t/g, '  ').length;
        if (listType !== 'ul' || indent !== listIndent) {
          if (listType) { listType = closeList(listType); }
          html += '<ul>';
          listType = 'ul';
          listIndent = indent;
        }
        html += '<li>' + renderInline(ulMatch[2]) + '</li>';
        i++;
        continue;
      }

      // 有序列表
      var olMatch = line.match(/^(\s*)(\d+)\.\s+(.+)/);
      if (olMatch) {
        var oIndent = olMatch[1].replace(/\t/g, '  ').length;
        if (listType !== 'ol' || oIndent !== listIndent) {
          if (listType) { listType = closeList(listType); }
          html += '<ol>';
          listType = 'ol';
          listIndent = oIndent;
        }
        html += '<li>' + renderInline(olMatch[3]) + '</li>';
        i++;
        continue;
      }

      // 普通段落
      if (listType) { listType = closeList(listType); }
      if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
      if (inTable) flushTable();

      // 合并连续非空行为一段
      var paraLines = [line];
      i++;
      while (i < lines.length && lines[i].trim() !== '' &&
             !/^(#{1,6})\s/.test(lines[i]) &&
             !/^\s*[-*+]\s/.test(lines[i]) &&
             !/^\s*\d+\.\s/.test(lines[i]) &&
             !lines[i].trim().startsWith('```') &&
             !lines[i].startsWith('> ') &&
             !/^\s*[-*_\s]+$/.test(lines[i]) &&
             !/^\|.*\|$/.test(lines[i].trim())) {
        paraLines.push(lines[i]);
        i++;
      }
      html += '<p>' + renderInline(paraLines.join(' ')) + '</p>';
    }

    // 结束未关闭的结构
    if (listType) closeList(listType);
    if (inBlockquote) html += '</blockquote>';
    if (inTable) flushTable();
    if (inCodeBlock) {
      html += '<pre><code' + (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : '') + '>' + escapeHtml(codeBuffer.join('\n')) + '</code></pre>';
    }

    return html;
  }

  // 从 DOM 元素提取正文文本为 Markdown
  function extractText(el) {
    var lines = [];
    var walk = function (node) {
      if (node.nodeType === 3) {
        var t = node.textContent.trim();
        if (t) lines.push(t);
        return;
      }
      if (node.nodeType !== 1) return;
      var tag = node.tagName.toLowerCase();
      if (['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'iframe'].indexOf(tag) > -1) return;
      if (['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'pre', 'td', 'th'].indexOf(tag) > -1) {
        var t2 = node.textContent.trim();
        if (t2) {
          if (tag.charAt(0) === 'h') lines.push('\n## ' + t2);
          else if (tag === 'li') lines.push('- ' + t2);
          else if (tag === 'blockquote') lines.push('> ' + t2);
          else lines.push(t2);
        }
        return;
      }
      for (var ci = 0; ci < node.childNodes.length; ci++) walk(node.childNodes[ci]);
    };
    walk(el);
    return lines.slice(0, 80).join('\n\n');
  }

  return {
    render: render,
    escapeHtml: escapeHtml,
    extractText: extractText,
  };
})();
