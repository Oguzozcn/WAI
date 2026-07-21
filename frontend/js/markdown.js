/*
 * WisdomMarkdown — shared, dependency-free markdown renderer.
 * ------------------------------------------------------------
 * Used by the Documentation page; lesson.html / edit-learning-path.html still
 * carry older regex mini-renderers and can migrate here over time.
 *
 * All input is HTML-escaped BEFORE any transformation, so rendered content
 * cannot inject markup. Supported syntax: h1-h4, **bold**, *italic*,
 * `inline code`, fenced code blocks, [links](url), ordered/unordered lists,
 * blockquotes, pipe tables, horizontal rules, paragraphs.
 *
 * Exposes: window.WisdomMarkdown = { render, escapeHtml }
 */
(function () {
  'use strict';

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Inline transforms applied to already-escaped text.
  function inline(text) {
    return text
      // `code` first, so markers inside code spans stay literal-ish
      .replace(/`([^`]+)`/g, '<code class="md-code-inline">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      // links — escaped text means no quotes can break out of href
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, label, href) {
        var external = /^https?:\/\//i.test(href);
        var attrs = external ? ' target="_blank" rel="noopener"' : '';
        return '<a class="md-link" href="' + href + '"' + attrs + '>' + label + '</a>';
      });
  }

  function render(md) {
    var lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
    var html = [];
    var i = 0;

    function isTableRow(line) {
      return /^\s*\|.*\|\s*$/.test(line);
    }
    function isDividerRow(line) {
      return /^\s*\|[\s:|-]+\|\s*$/.test(line);
    }
    function splitRow(line) {
      var trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
      return trimmed.split('|').map(function (c) { return c.trim(); });
    }

    while (i < lines.length) {
      var line = lines[i];

      // Fenced code block
      var fence = line.match(/^\s*```(\w*)\s*$/);
      if (fence) {
        var code = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
          code.push(escapeHtml(lines[i]));
          i++;
        }
        i++; // closing fence
        html.push('<pre class="md-pre"><code>' + code.join('\n') + '</code></pre>');
        continue;
      }

      // Blank line
      if (!line.trim()) { i++; continue; }

      // Headings
      var h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        var level = h[1].length;
        html.push('<h' + level + ' class="md-h' + level + '">' + inline(escapeHtml(h[2])) + '</h' + level + '>');
        i++;
        continue;
      }

      // Horizontal rule
      if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
        html.push('<hr class="md-hr">');
        i++;
        continue;
      }

      // Table
      if (isTableRow(line) && i + 1 < lines.length && isDividerRow(lines[i + 1])) {
        var headCells = splitRow(line).map(function (c) {
          return '<th>' + inline(escapeHtml(c)) + '</th>';
        }).join('');
        i += 2;
        var bodyRows = [];
        while (i < lines.length && isTableRow(lines[i])) {
          bodyRows.push('<tr>' + splitRow(lines[i]).map(function (c) {
            return '<td>' + inline(escapeHtml(c)) + '</td>';
          }).join('') + '</tr>');
          i++;
        }
        html.push(
          '<div class="md-table-wrap"><table class="md-table"><thead><tr>' + headCells +
          '</tr></thead><tbody>' + bodyRows.join('') + '</tbody></table></div>'
        );
        continue;
      }

      // Blockquote (consume consecutive > lines)
      if (/^\s*>\s?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quote.push(inline(escapeHtml(lines[i].replace(/^\s*>\s?/, ''))));
          i++;
        }
        html.push('<blockquote class="md-quote">' + quote.join('<br>') + '</blockquote>');
        continue;
      }

      // Unordered list (supports one nesting level via indentation)
      if (/^\s*[-*]\s+/.test(line)) {
        var items = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          var m = lines[i].match(/^(\s*)[-*]\s+(.*)$/);
          items.push({ depth: m[1].length >= 2 ? 1 : 0, text: inline(escapeHtml(m[2])) });
          i++;
        }
        var ul = '<ul class="md-ul">';
        var open = false;
        items.forEach(function (item) {
          if (item.depth === 1 && !open) { ul += '<ul class="md-ul md-ul-nested">'; open = true; }
          if (item.depth === 0 && open) { ul += '</ul>'; open = false; }
          ul += '<li>' + item.text + '</li>';
        });
        if (open) ul += '</ul>';
        ul += '</ul>';
        html.push(ul);
        continue;
      }

      // Ordered list
      if (/^\s*\d+\.\s+/.test(line)) {
        var oitems = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          oitems.push('<li>' + inline(escapeHtml(lines[i].replace(/^\s*\d+\.\s+/, ''))) + '</li>');
          i++;
        }
        html.push('<ol class="md-ol">' + oitems.join('') + '</ol>');
        continue;
      }

      // Paragraph (consume until a blank line or a block-start)
      var para = [];
      while (
        i < lines.length && lines[i].trim() &&
        !/^(#{1,4})\s/.test(lines[i]) && !/^\s*```/.test(lines[i]) &&
        !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i]) &&
        !/^\s*>\s?/.test(lines[i]) && !isTableRow(lines[i]) &&
        !/^\s*(---+|\*\*\*+|___+)\s*$/.test(lines[i])
      ) {
        para.push(inline(escapeHtml(lines[i].trim())));
        i++;
      }
      if (para.length) html.push('<p class="md-p">' + para.join(' ') + '</p>');
    }

    return html.join('\n');
  }

  window.WisdomMarkdown = { render: render, escapeHtml: escapeHtml };
})();
