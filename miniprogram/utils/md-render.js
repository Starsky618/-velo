/**
 * Markdown 小译员——把路线手册里的少量 Markdown 翻译成 rich-text 节点。
 *
 * 这个文件只认路线百科当前会用到的写法：标题、段落、粗体、无序列表、图片。
 * 不认识的语法不会丢弃，而是当普通段落展示，像读手写笔记时先保住原话。
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
    nodes.push({ name: 'strong', children: [textNode(match[1])] })
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
      style: 'max-width:100%;border-radius:8px;',
    },
  }
}

function flushList(nodes, items) {
  if (!items.length) return
  nodes.push({
    name: 'ul',
    attrs: { class: 'md-ul' },
    children: items.map(function (item) {
      return { name: 'li', attrs: { class: 'md-li' }, children: inlineNodes(item) }
    }),
  })
  items.length = 0
}

function renderMarkdown(markdown) {
  var nodes = []
  var listItems = []
  var lines = String(markdown || '').split(/\r?\n/)

  lines.forEach(function (rawLine) {
    var line = rawLine.trim()
    var image = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
    if (!line) {
      flushList(nodes, listItems)
      return
    }
    if (image) {
      flushList(nodes, listItems)
      nodes.push(imageNode(image[1], image[2]))
      return
    }
    if (line.indexOf('## ') === 0) {
      flushList(nodes, listItems)
      nodes.push(headingNode(2, line.slice(3).trim()))
      return
    }
    if (line.indexOf('# ') === 0) {
      flushList(nodes, listItems)
      nodes.push(headingNode(1, line.slice(2).trim()))
      return
    }
    if (line.indexOf('- ') === 0 || line.indexOf('* ') === 0) {
      listItems.push(line.slice(2).trim())
      return
    }
    flushList(nodes, listItems)
    nodes.push(paragraphNode(line))
  })

  flushList(nodes, listItems)
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
