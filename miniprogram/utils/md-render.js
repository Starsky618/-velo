/**
 * Markdown 小译员——把路线手册里的少量 Markdown 翻译成 rich-text 节点。
 *
 * 这个文件只认路线百科当前会用到的写法：标题、段落、粗体、无序/有序列表、键值对、图片。
 * 不认识的语法不会丢弃，而是当普通段落展示，像读手写笔记时先保住原话。
 *
 * 排版分层设计（2026-06-12 / "正文太密无分层"反馈后的升级）：
 * 同样的 Markdown 行，按"长相"翻译成三种立体结构，让正文有层次可扫读——
 *   - "- **距离**：10.05 km"  → 键值行（iOS 设置页式：左灰标签 + 右深色数字）
 *   - "1. **汾河绿道** ..."   → 步骤行（橙色序号 + 正文，"怎么骑"导航感）
 *   - "- 普通列表项"          → 自绘圆点行（橙点 + 正文，间距可控）
 * 粗体用 span.md-b 而不是原生 strong：strong 触发 font-weight 700，
 * 中文苹方真字重上限 600，700 会合成加粗笔画糊（MASTER §3 铁律）。
 */

function textNode(text) {
  return { type: 'text', text: text || '' }
}

function inlineNodes(text) {
  var nodes = []
  var source = text || ''
  var pattern = /\*\*([^*]+)\*\*/g
  var last = 0
  var match
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > last) {
      nodes.push(textNode(source.slice(last, match.index)))
    }
    nodes.push({ name: 'span', attrs: { class: 'md-b' }, children: [textNode(match[1])] })
    last = pattern.lastIndex
  }
  if (last < source.length) {
    nodes.push(textNode(source.slice(last)))
  }
  return nodes.length ? nodes : [textNode(source)]
}

function paragraphNode(text) {
  return {
    name: 'p',
    attrs: { class: 'md-p' },
    children: inlineNodes(text),
  }
}

function headingNode(level, text) {
  return {
    name: level === 1 ? 'h1' : 'h2',
    attrs: { class: level === 1 ? 'md-h1' : 'md-h2' },
    children: inlineNodes(text),
  }
}

function imageNode(alt, src) {
  return {
    name: 'img',
    attrs: {
      class: 'md-img',
      alt: alt || '',
      src: src || '',
      style: 'max-width:100%;border-radius:12px;',
    },
  }
}

// 键值行："**距离**：10.05 km" → 左灰标签右深色值（设置页式数据表）
function keyValueNode(key, value) {
  return {
    name: 'div',
    attrs: { class: 'md-kv' },
    children: [
      { name: 'span', attrs: { class: 'md-kv-k' }, children: [textNode(key)] },
      { name: 'span', attrs: { class: 'md-kv-v' }, children: [textNode(value)] },
    ],
  }
}

// 步骤行："1. **汾河绿道** 沿汾河…" → 橙色序号 + 正文
function stepNode(number, text) {
  return {
    name: 'div',
    attrs: { class: 'md-step' },
    children: [
      { name: 'span', attrs: { class: 'md-step-n' }, children: [textNode(number)] },
      { name: 'span', attrs: { class: 'md-step-body' }, children: inlineNodes(text) },
    ],
  }
}

// 自绘圆点行：替代原生 ul/li——li 的默认 bullet 和间距在 rich-text 里不可控
function bulletNode(text) {
  return {
    name: 'div',
    attrs: { class: 'md-li' },
    children: [
      { name: 'span', attrs: { class: 'md-dot' } },
      { name: 'span', attrs: { class: 'md-li-body' }, children: inlineNodes(text) },
    ],
  }
}

// 字段块："**到起点**：迎宾桥两岸…（长文）" → 橙色小标签独立一行 + 值另起一行。
// 与键值行的分工：短值（"10.05 km"）走左右对齐表格行；长文塞进表格右列会排版崩坏。
function fieldNode(key, value) {
  return {
    name: 'div',
    attrs: { class: 'md-field' },
    children: [
      { name: 'div', attrs: { class: 'md-field-k' }, children: [textNode(key)] },
      { name: 'div', attrs: { class: 'md-field-v' }, children: inlineNodes(value) },
    ],
  }
}

// 语录块："“语录”——解释" → 语录气泡 + 解释另起一行小字（骑友怎么说节）
function quoteNode(quote, note) {
  var children = [
    { name: 'div', attrs: { class: 'md-quote-text' }, children: [textNode('“' + quote + '”')] },
  ]
  if (note) {
    children.push({ name: 'div', attrs: { class: 'md-quote-note' }, children: [textNode(note)] })
  }
  return { name: 'div', attrs: { class: 'md-quote' }, children: children }
}

// 中文里一个汉字顶两个拉丁字符宽——超过这个视觉长度的值不再适合表格右列
var KV_VALUE_MAX = 18

function listItemNode(item) {
  // "- “语录”——解释" → 语录气泡（第一个 —— 分割，解释里再有 —— 归解释）
  var quote = item.match(/^[“"](.+?)[”"]\s*——\s*(.+)$/)
  if (quote) return quoteNode(quote[1].trim(), quote[2].trim())
  // "- **键**：值" → 短值进键值表格行，长值进字段块
  var kv = item.match(/^\*\*([^*]+)\*\*\s*[：:]\s*(.+)$/)
  if (kv) {
    var key = kv[1].trim()
    var value = kv[2].trim()
    return value.length > KV_VALUE_MAX ? fieldNode(key, value) : keyValueNode(key, value)
  }
  return bulletNode(item)
}

function renderMarkdown(markdown) {
  var nodes = []
  var lines = String(markdown || '').split(/\r?\n/)

  lines.forEach(function (rawLine) {
    var line = rawLine.trim()
    if (!line) return
    var image = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
    if (image) {
      nodes.push(imageNode(image[1], image[2]))
      return
    }
    if (line.indexOf('## ') === 0) {
      nodes.push(headingNode(2, line.slice(3).trim()))
      return
    }
    if (line.indexOf('# ') === 0) {
      nodes.push(headingNode(1, line.slice(2).trim()))
      return
    }
    if (line.indexOf('- ') === 0 || line.indexOf('* ') === 0) {
      nodes.push(listItemNode(line.slice(2).trim()))
      return
    }
    var step = line.match(/^(\d+)[.、]\s+(.+)$/)
    if (step) {
      nodes.push(stepNode(step[1], step[2]))
      return
    }
    nodes.push(paragraphNode(line))
  })

  return nodes
}

function splitSections(markdown) {
  var sections = []
  var current = null
  var lines = String(markdown || '').split(/\r?\n/)

  lines.forEach(function (line) {
    if (line.indexOf('## ') === 0) {
      if (current) sections.push(current)
      current = { title: line.slice(3).trim(), body: [] }
      return
    }
    if (current) current.body.push(line)
  })

  if (current) sections.push(current)
  return sections.map(function (section) {
    return {
      title: section.title,
      body: section.body.join('\n'),
    }
  })
}

module.exports = {
  renderMarkdown: renderMarkdown,
  splitSections: splitSections,
}
