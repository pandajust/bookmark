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

  // ---- 文本清理：过滤乱码、非文本内容 ----
  // 零宽字符、BOM、软连字
  var RE_INVISIBLE = /[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]/g;
  // 控制字符（保留 \t \n \r）
  var RE_CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;
  // JSON 数据行（以 { 开头，含 "key": 模式）
  var RE_JSON_LINE = /^\s*\{["\w]+\s*:/;
  // 纯装饰符号行（同一字符连续重复 10 次以上，如 ******）
  var RE_DECORATIVE = /^\s*([*_~\-=#>|])\1{9,}\s*$/;
  // 纯符号行（整行仅由装饰符号和空白组成，如 "**"、"* * *"）—— 但保留合法 hr
  var RE_PURE_SYMBOL = /^[\s*_~\-=#>|<\[\](){}\.+]+$/;
  var RE_HR_LINE = /^\s*([-*_])\s*\1\s*\1[\s\1]*$/;
  // 空文本链接 [](url) → 删除（无论 URL 是什么）
  var RE_EMPTY_TEXT_LINK = /\[\s*\]\([^)]*\)/g;
  // 不可跳转链接 [text](javascript:;) / [text](#) / [text](void(0)) / [text]() → 只保留 text
  var RE_NON_JUMP_LINK = /\[([^\]]+)\]\((?:javascript:[^)]*|#[^)]*|void\([^)]*\)|)\s*\)/g;
  // 装饰符号碎片：方括号内以 * _ ~ 为主夹杂短文本，如 [*** English*]
  var RE_DECO_BRACKET = /\[[\s*_~\-]+[^\[\]]{0,20}[\s*_~\-]+\](?!\()/g;
  // 纯 [*] [**] 碎片（方括号内纯星号，且后非 ( ）
  var RE_DECO_STARS = /\[\*+\](?!\()/g;
  // 图片被链接包裹 [![alt](img)](url) → 只保留 ![alt](img)
  var RE_LINKED_IMG = /\[!\[([^\]]*)\]\(([^)]+)\)\]\([^)]*\)/g;
  // 脚注链接：[*](url) / [†](url) / [1](url) / [12](url) 等标记性引用 → 删除
  // 分两组覆盖：符号型脚注 + 数字型脚注（多数字）
  var RE_FOOTNOTE_LINK = /\[[*†‡§¶]\]\([^)]*\)/g;
  var RE_FOOTNOTE_LINK_NUM = /\[\d+\]\([^)]*\)/g;
  // 断裂链接 ](url)（缺少开头 [）→ 删除
  var RE_BROKEN_LINK = /\]\([^)]*\)/g;
  // 孤立脚注标记 [*] / [†] / [1] / [12] 等（后非 ( ）
  var RE_FOOTNOTE_MARK = /\[[*†‡§¶]\](?!\()/g;
  var RE_FOOTNOTE_MARK_NUM = /\[\d+\](?!\()/g;
  // 列表行内的标题标记（如 "- ### 标题"）→ 移除 ### 标记
  var RE_LIST_HEADING = /^(\s*[-*+]\s+)#{1,6}\s+/gm;
  // 正文内孤立的 #...# 行内标题标记（如段落中 "### 子标题" 残留）→ 移除
  var RE_INLINE_HEADING = /#{1,6}\s+/g;

  function cleanMarkdown(md) {
    if (!md) return md;
    // 辅助：从 s[start]='(' 起返回匹配 ')' 的位置（含），找不到返回 -1
    function findBalancedParen(s, start) {
      var depth = 0;
      for (var j = start; j < s.length; j++) {
        if (s.charCodeAt(j) === 40) depth++;        // '('
        else if (s.charCodeAt(j) === 41) {         // ')'
          depth--;
          if (depth === 0) return j;
        }
      }
      return -1;
    }

    // 1. 先移除不可见字符和控制字符（在占位符之前，避免破坏占位符分隔符）
    md = md.replace(RE_INVISIBLE, '');
    md = md.replace(RE_CONTROL, '');
    // 2. nbsp 转普通空格
    md = md.replace(/\u00a0/g, ' ');

    // 3. 用占位符保护图片 ![alt](url)，防止后续正则（如断裂链接）误删 URL
    var imgHolders = [];
    md = (function (s) {
      var out = [];
      var i = 0;
      var n = s.length;
      while (i < n) {
        // 识别 ![alt](url)
        if (s.charCodeAt(i) === 33) { // !
          if (i + 1 < n && s.charCodeAt(i + 1) === 91) { // ![
            var altEnd = s.indexOf(']', i + 2);
            if (altEnd > 0 && altEnd + 1 < n && s.charCodeAt(altEnd + 1) === 40) { // (
              var parenEnd = findBalancedParen(s, altEnd + 1);
              if (parenEnd > 0) {
                var alt = s.substring(i + 2, altEnd);
                var url = s.substring(altEnd + 2, parenEnd);
                var ph = '\x80img' + imgHolders.length + '\x80';
                imgHolders.push({ alt: alt, url: url });
                out.push(ph);
                i = parenEnd + 1;
                continue;
              }
            }
            // ! 紧跟 [ 但图片语法不完整（如 ![alt] 无 URL）→ 移除整个图片标记
            // 跳过 !，让后续的 [alt] 部分也被清理
            out.push('');
            i++;
            continue;
          }
          // ! 非图片起始：保留（交由 renderInline 处理精确判断）
          out.push(s[i]);
          i++;
          continue;
        }
        out.push(s[i]);
        i++;
      }
      return out.join('');
    })(md);

    // 3.5 用占位符保护完整链接 [text](url)，防止 RE_BROKEN_LINK 误匹配
    var linkHolders = [];
    md = (function (s) {
      var out = [];
      var i = 0;
      var n = s.length;
      while (i < n) {
        if (s.charCodeAt(i) === 91) { // [
          var bracketEnd = s.indexOf(']', i + 1);
          if (bracketEnd > 0 && bracketEnd + 1 < n && s.charCodeAt(bracketEnd + 1) === 40) { // (
            var parenEnd = findBalancedParen(s, bracketEnd + 1);
            if (parenEnd > 0) {
              var text = s.substring(i + 1, bracketEnd);
              var url = s.substring(bracketEnd + 2, parenEnd);
              var u = (url || '').trim();
              var isFootnote = /^[*†‡§¶\d]+$/.test(text.trim());
              var isNonJump = !u || u === '#' || /^javascript:/i.test(u) || u.indexOf('void(') === 0;
              if (isFootnote) {
                // 脚注链接 → 直接删除（不进入占位符）
                out.push('');
                i = parenEnd + 1;
                continue;
              } else if (isNonJump) {
                // 不可跳转链接 → 只保留 text
                out.push(text);
                i = parenEnd + 1;
                continue;
              } else {
                // 正常链接 → 用占位符保护
                var ph = '\x80link' + linkHolders.length + '\x80';
                linkHolders.push({ text: text, url: url });
                out.push(ph);
                i = parenEnd + 1;
                continue;
              }
            }
          }
        }
        out.push(s[i]);
        i++;
      }
      return out.join('');
    })(md);

    // 4. 图片被链接包裹 → 只保留图片（占位符形式匹配）
    md = md.replace(/\[\x80img(\d+)\x80\]\([^)]*\)/g, function (m, idx) {
      return '![' + imgHolders[+idx].alt + '](' + imgHolders[+idx].url + ')';
    });
    // 5. 空文本链接 [](url) → 删除（空链接不含有效文本，不会被占位符保护）
    md = md.replace(RE_EMPTY_TEXT_LINK, '');
    // 6. 装饰符号碎片 [*** 文本*] / [*] → 删除
    md = md.replace(RE_DECO_BRACKET, '');
    md = md.replace(RE_DECO_STARS, '');
    // 7. 断裂链接 ](url) → 删除（完整链接已被占位符保护，图片已被保护）
    md = md.replace(RE_BROKEN_LINK, '');
    // 8. 孤立脚注标记 [*] / [†] / [1] / [12]（后非 ( ） → 删除
    md = md.replace(RE_FOOTNOTE_MARK, '');
    md = md.replace(RE_FOOTNOTE_MARK_NUM, '');
    // 9. 列表行内的标题标记 ### → 移除（仅移除列表项开头的）
    md = md.replace(RE_LIST_HEADING, '$1');
    // 10. 移除正文中残留的行内标题标记（不在列表项开头的 ### 标记）
    md = md.replace(/^(?!\s*[-*+]\s)(?!#{1,6}\s)(.*?)#{1,6}\s+/gm, '$1');
    // 10.5 清理损坏的图片标记行（在逐行过滤之前）
    //     列表项中仅有 ! 的行（如 "- !"）→ 移除整行
    md = md.replace(/^[ \t]*(?:[-*+]\s+)*!\s*$/gm, '');
    //     损坏的图片语法行（如 "![]()" 或 "![alt]()" 无 URL）→ 移除整行
    md = md.replace(/^[ \t]*(?:[-*+]\s+)*!\[[^\]]*\]\(\s*\)\s*$/gm, '');
    // 11. 逐行过滤 JSON 数据行、装饰符号行、纯符号行
    var lines = md.split('\n');
    var filtered = [];
    for (var li = 0; li < lines.length; li++) {
      var line = lines[li];
      if (RE_JSON_LINE.test(line)) continue;
      if (RE_DECORATIVE.test(line)) continue;
      if (RE_PURE_SYMBOL.test(line) && !RE_HR_LINE.test(line)) continue;
      filtered.push(line);
    }
    md = filtered.join('\n');
    // 12. 恢复被保护的图片占位符
    md = md.replace(/\x80img(\d+)\x80/g, function (m, idx) {
      var im = imgHolders[+idx];
      return '![' + im.alt + '](' + im.url + ')';
    });
    // 13. 恢复被保护的链接占位符
    md = md.replace(/\x80link(\d+)\x80/g, function (m, idx) {
      var lk = linkHolders[+idx];
      return '[' + lk.text + '](' + lk.url + ')';
    });
    // 14. 合并连续空行（最多保留两个换行）
    md = md.replace(/\n{3,}/g, '\n\n');
    return md;
  }

  // ---- 内联解析 ----
  function renderInline(md) {
    if (!md) return '';

    // 辅助：从 s[start]='(' 起返回匹配 ')' 的位置（含），找不到返回 -1
    function findBalancedParen(s, start) {
      var depth = 0;
      for (var j = start; j < s.length; j++) {
        if (s.charCodeAt(j) === 40) depth++;        // '('
        else if (s.charCodeAt(j) === 41) {         // ')'
          depth--;
          if (depth === 0) return j;
        }
      }
      return -1;
    }

    // 代码（最高优先级，防止代码内的 * _ ` 被误解析）
    var result = md.replace(/`([^`]+)`/g, function (m, code) {
      return '<code>' + escapeHtml(code) + '</code>';
    });

    // 图片 ![alt](url) — 先用平衡括号匹配保护（URL 可能含圆括号）
    // 使用 \x80 作为占位符分隔符（高位 ASCII，安全不被清理）
    var imgPlaceholders = [];
    result = (function (s) {
      var out = [];
      var i = 0;
      var n = s.length;
      while (i < n) {
        // 识别 ![alt](url)
        if (s.charCodeAt(i) === 33) { // !
          if (i + 1 < n && s.charCodeAt(i + 1) === 91) { // ![
            var altEnd = s.indexOf(']', i + 2);
            if (altEnd > 0 && altEnd + 1 < n && s.charCodeAt(altEnd + 1) === 40) { // (
              var parenEnd = findBalancedParen(s, altEnd + 1);
              if (parenEnd > 0) {
                var alt = s.substring(i + 2, altEnd);
                var url = s.substring(altEnd + 2, parenEnd);
                var ph = '\x80img' + imgPlaceholders.length + '\x80';
                imgPlaceholders.push({ alt: alt, url: url });
                out.push(ph);
                i = parenEnd + 1;
                continue;
              }
            }
            // ! 紧跟 [ 但图片语法不完整 → 丢弃 !（损坏的图片标记）
            out.push('');
            i++;
            continue;
          }
          // ! 非图片起始：判断是否为孤立的损坏标记
          var prev = i > 0 ? s.charCodeAt(i - 1) : 0;
          var next = i + 1 < n ? s.charCodeAt(i + 1) : 0;
          var isWordChar = function(c) {
            return (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) ||
                   (c >= 0x4e00 && c <= 0x9fff) || c === 95;
          };
          if (isWordChar(prev) || isWordChar(next)) {
            // 合法文本中的 ! → 保留
            out.push(s[i]);
            i++;
          } else {
            // 孤立的 !（周围是空白/标点/边界）→ 丢弃
            out.push('');
            i++;
          }
          continue;
        }
        out.push(s[i]);
        i++;
      }
      return out.join('');
    })(result);

    // 链接 [text](url) — 图片已被占位符保护，平衡匹配 URL 内的圆括号
    result = (function (s) {
      var out = [];
      var i = 0;
      var n = s.length;
      while (i < n) {
        if (s.charCodeAt(i) === 91) { // [
          var bracketEnd = s.indexOf(']', i + 1);
          if (bracketEnd > 0 && bracketEnd + 1 < n && s.charCodeAt(bracketEnd + 1) === 40) { // (
            var parenEnd = findBalancedParen(s, bracketEnd + 1);
            if (parenEnd > 0) {
              var text = s.substring(i + 1, bracketEnd);
              var url = s.substring(bracketEnd + 2, parenEnd);
              var u = (url || '').trim();
              // 不可跳转链接 → 只保留 text
              if (!u || u === '#' || /^javascript:/i.test(u) || u.indexOf('void(') === 0) {
                out.push(text);
              } else {
                out.push('<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + text + '</a>');
              }
              i = parenEnd + 1;
              continue;
            }
          }
        }
        out.push(s[i]);
        i++;
      }
      return out.join('');
    })(result);

    // 恢复图片占位符为 <img> 标签
    result = result.replace(/\x80img(\d+)\x80/g, function (m, idx) {
      var item = imgPlaceholders[parseInt(idx, 10)];
      if (!item) return '';
      return '<img src="' + escapeHtml(item.url) + '" alt="' + escapeHtml(item.alt) + '">';
    });

    // 清理未能转换的残留 Markdown 语法
    // 断裂链接 ](url)（平衡匹配，可能含嵌套圆括号）
    result = (function (s) {
      var out = [];
      var i = 0;
      var n = s.length;
      while (i < n) {
        if (s.charCodeAt(i) === 93 && i + 1 < n && s.charCodeAt(i + 1) === 40) { // ](
          var parenEnd = findBalancedParen(s, i + 1);
          if (parenEnd > 0) {
            out.push('');
            i = parenEnd + 1;
            continue;
          }
        }
        out.push(s[i]);
        i++;
      }
      return out.join('');
    })(result);

    // 孤立脚注标记（符号型 + 数字型）
    result = result.replace(/\[[*†‡§¶]\]/g, '');
    result = result.replace(/\[\d+\]/g, '');
    // 行内孤立的 # 标题标记
    result = result.replace(/#{1,6}\s+/g, '');

    // 清理残留的占位符文本（防止泄漏到输出中）
    result = result.replace(/\x80img\d+\x80/g, '');
    result = result.replace(/\x80link\d+\x80/g, '');

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
    // 前端渲染前清理：过滤乱码、JSON数据、装饰符号、空链接等非文本内容
    md = cleanMarkdown(md);
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
    var pendingImages = [];

    function flushImages() {
      if (pendingImages.length === 0) return;
      if (listType) { listType = closeList(listType); }
      if (inBlockquote) { html += '</blockquote>'; inBlockquote = false; }
      if (inTable) flushTable();
      // 每张图片独占一个 <p>，让 render.js 的 processImages 统一合并为 gallery
      for (var ii = 0; ii < pendingImages.length; ii++) {
        var img = pendingImages[ii];
        html += '<p><img src="' + escapeHtml(img.url) + '" alt="' + escapeHtml(img.alt) + '"></p>';
      }
      pendingImages = [];
    }

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
        if (pendingImages.length) flushImages();
        i++;
        continue;
      }

      // 图片行检测（独占一行的 ![alt](url)，可能带列表标记）
      // 使用平衡括号匹配支持 URL 含圆括号
      var trimmedLine = line.trim();
      var listPrefix = '';
      var checkLine = trimmedLine;
      // 检查是否有列表前缀
      var lpMatch = trimmedLine.match(/^([-*+]\s+)/);
      if (lpMatch) {
        listPrefix = lpMatch[1];
        checkLine = trimmedLine.substring(listPrefix.length);
      }
      // 检查是否为图片（从 ! 开始）
      var isImgLine = false;
      var imgAlt = '';
      var imgUrl = '';
      if (checkLine.charCodeAt(0) === 33 && checkLine.charCodeAt(1) === 91) { // ![
        var imgAltEnd = checkLine.indexOf(']', 2);
        if (imgAltEnd > 0 && imgAltEnd + 1 < checkLine.length && checkLine.charCodeAt(imgAltEnd + 1) === 40) { // (
          // 平衡括号匹配 URL 中的圆括号
          var imgDepth = 0;
          var imgParenEnd = -1;
          for (var ij = imgAltEnd + 1; ij < checkLine.length; ij++) {
            if (checkLine.charCodeAt(ij) === 40) imgDepth++;
            else if (checkLine.charCodeAt(ij) === 41) {
              imgDepth--;
              if (imgDepth === 0) { imgParenEnd = ij; break; }
            }
          }
          if (imgParenEnd > 0 && imgParenEnd + 1 === checkLine.length) {
            imgAlt = checkLine.substring(2, imgAltEnd);
            imgUrl = checkLine.substring(imgAltEnd + 2, imgParenEnd);
            isImgLine = true;
          }
        }
      }
      if (isImgLine) {
        pendingImages.push({ alt: imgAlt, url: imgUrl });
        i++;
        continue;
      }
      // 非图片行：如果之前积累了图片，先 flush
      if (pendingImages.length) {
        flushImages();
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
        var ulContent = renderInline(ulMatch[2]);
        if (ulContent && ulContent.trim()) {
          html += '<li>' + ulContent + '</li>';
        }
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
        var olContent = renderInline(olMatch[3]);
        if (olContent && olContent.trim()) {
          html += '<li>' + olContent + '</li>';
        }
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
             !/^\|.*\|$/.test(lines[i].trim()) &&
             !/^(?:[-*+]\s+)?!\[([^\]]*)\]\(([^)]+)\)$/.test(lines[i].trim())) {
        paraLines.push(lines[i]);
        i++;
      }
      html += '<p>' + renderInline(paraLines.join(' ')) + '</p>';
    }

    // 结束未关闭的结构
    if (listType) closeList(listType);
    if (inBlockquote) html += '</blockquote>';
    if (inTable) flushTable();
    if (pendingImages.length) flushImages();
    if (inCodeBlock) {
      html += '<pre><code' + (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : '') + '>' + escapeHtml(codeBuffer.join('\n')) + '</code></pre>';
    }

    // 最终清理：移除孤立的 ! 符号（来自损坏的图片语法），保留合法 !（如 Hello!）
    html = html.replace(/>([^<]*)</g, function(m, text) {
      if (text.indexOf('!') < 0) return m;
      // 只清理不在单词字符旁边的 !（孤立的损坏标记）
      var refined = text.replace(/!/g, function(ch, pos) {
        var prev = pos > 0 ? text.charCodeAt(pos - 1) : 0;
        var next = pos + 1 < text.length ? text.charCodeAt(pos + 1) : 0;
        var isWordChar = function(c) {
          return (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) ||
                 (c >= 0x4e00 && c <= 0x9fff) || c === 95;
        };
        return (isWordChar(prev) || isWordChar(next)) ? ch : '';
      });
      return '>' + refined + '<';
    });

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
    cleanMarkdown: cleanMarkdown,
    escapeHtml: escapeHtml,
    extractText: extractText,
  };
})();
