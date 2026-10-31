// 最小的畫面工具（UI_RULES U2、U5）：每次用 h() 組出新樹，再和舊樹比對，只更新有變的節點。
// 有 data-id 的子節點依 id 比對，所以選取、捲動、輸入中的文字都不會被重置。

const EVENT_PREFIX = 'on';

/** 建立元素。屬性 testid → data-testid（CODING_RULES V9），id → data-id（U5）。 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith(EVENT_PREFIX)) el[key] = value;
    else if (key === 'class') el.className = value;
    else if (key === 'testid') el.dataset.testid = value;
    else if (key === 'key') el.dataset.id = value;
    else if (key === 'value') el.__value = String(value);
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  if (el.__value !== undefined) el.value = el.__value;
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

const EVENT_NAMES = ['onclick', 'oninput', 'onchange', 'onpointerdown', 'onpointerup',
  'onpointercancel', 'onpointerleave', 'oncontextmenu', 'onkeydown', 'oncompositionstart',
  'oncompositionend'];

function syncNode(oldNode, newNode) {
  if (oldNode.nodeType !== newNode.nodeType || oldNode.nodeName !== newNode.nodeName) {
    oldNode.replaceWith(newNode);
    return;
  }
  if (oldNode.nodeType === Node.TEXT_NODE) {
    if (oldNode.data !== newNode.data) oldNode.data = newNode.data;
    return;
  }
  for (const attr of [...oldNode.attributes]) {
    if (!newNode.hasAttribute(attr.name)) oldNode.removeAttribute(attr.name);
  }
  for (const attr of newNode.attributes) {
    if (oldNode.getAttribute(attr.name) !== attr.value) oldNode.setAttribute(attr.name, attr.value);
  }
  for (const name of EVENT_NAMES) oldNode[name] = newNode[name];
  // 輸入中的欄位不覆寫（避免打斷注音組字），其他情況才同步
  if (newNode.__value !== undefined && oldNode !== document.activeElement) {
    oldNode.value = newNode.__value;
  }
  if ('disabled' in newNode) oldNode.disabled = newNode.disabled;
  syncChildren(oldNode, newNode);
}

function syncChildren(parent, source) {
  const incoming = [...source.childNodes];
  const keyed = new Map();
  for (const child of parent.childNodes) {
    if (child.dataset?.id) keyed.set(child.dataset.id, child);
  }
  let cursor = parent.firstChild;
  for (const next of incoming) {
    const key = next.dataset?.id;
    let match = key ? keyed.get(key) : cursor;
    if (key && !match) match = null;
    if (!key && match?.dataset?.id) match = null;
    if (match) {
      if (match !== cursor) parent.insertBefore(match, cursor);
      syncNode(match, next);
      const current = next.isConnected ? next : match;
      cursor = (current.parentNode === parent ? current : match).nextSibling;
    } else {
      parent.insertBefore(next, cursor);
    }
  }
  while (cursor) {
    const after = cursor.nextSibling;
    cursor.remove();
    cursor = after;
  }
}

/** 把容器內容更新成 children。 */
export function render(container, ...children) {
  const next = document.createElement(container.nodeName);
  append(next, children);
  syncChildren(container, next);
}
