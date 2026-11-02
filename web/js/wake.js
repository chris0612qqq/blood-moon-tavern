// 保持螢幕亮著（SPEC S24）。瀏覽器只在 HTTPS 提供這個功能，也可能拒絕（例如省電模式），
// 這時大廳提示玩家手動設定。切到背景時鎖會被放掉，回來要重新要（CODING_RULES E11：失敗不影響遊戲）。
import { changed, store } from './store.js';

let lock = null;
let requesting = false;

store.wake = { supported: Boolean(navigator.wakeLock), failed: false };

function setFailed(failed) {
  if (store.wake.failed === failed) return;
  store.wake.failed = failed;
  changed();
}

async function sync() {
  if (!store.wake.supported || requesting) return;
  if (!store.server) {
    lock?.release();
    return;
  }
  if (lock || document.hidden) return;
  requesting = true;
  try {
    lock = await navigator.wakeLock.request('screen');
    lock.addEventListener('release', () => { lock = null; });
    setFailed(false);
  } catch {
    setFailed(true);
  } finally {
    requesting = false;
  }
}

// 有些瀏覽器要手指點過才肯開，所以每次點擊都檢查一次
for (const name of ['touchend', 'click']) {
  document.addEventListener(name, sync, { capture: true, passive: true });
}
document.addEventListener('visibilitychange', sync);
