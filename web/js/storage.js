// 手機本機資料（CODING_RULES E12）：讀不到一律當新使用者，不拋錯。
// DEV_MODE 的 ?dev_device=x 讓一台電腦能開多個分頁當多位玩家（CODING_RULES D9）。

const params = new URLSearchParams(location.search);
export const DEV_DEVICE = params.get('dev_device');
const PREFIX = DEV_DEVICE ? `bmt.${DEV_DEVICE}.` : 'bmt.';
const memory = new Map();

export function load(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return memory.has(key) ? memory.get(key) : fallback;
  }
}

export function save(key, value) {
  memory.set(key, value);
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // 私密瀏覽可能不能寫入；這次連線仍可用記憶體中的值
  }
}

export function remove(key) {
  memory.delete(key);
  try {
    localStorage.removeItem(PREFIX + key);
  } catch {
    // 同上
  }
}

/** 隨機 id。非 HTTPS 的區網網址沒有 crypto.randomUUID，所以用 getRandomValues。 */
export function randomId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** 裝置 ID（SPEC A5.7）。 */
export function deviceId() {
  let id = load('device_id');
  if (!id) {
    id = randomId();
    save('device_id', id);
  }
  return id;
}
