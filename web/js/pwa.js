// 加到主畫面（SPEC S23、S24、CODING_RULES N16、V16）。
// 主畫面 App 和瀏覽器的資料不共用，所以教學一定要在加入房間之前出現。
import { send } from './net.js';
import { load, save } from './storage.js';
import { changed, store, subscribe } from './store.js';

const ua = navigator.userAgent;
/** 'ios'、'android'，電腦是 null（不出教學）。iPad 會假裝是 Mac，要看觸控點。 */
export const PLATFORM = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
  ? 'ios'
  : /Android/.test(ua) ? 'android' : null;
export const STANDALONE = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

// 正式環境是 HTTPS；區網 http 不能用 service worker，測試用 sw_test 打開
if ('serviceWorker' in navigator && (location.protocol === 'https:' || load('sw_test'))) {
  navigator.serviceWorker.register('sw.js').catch(() => {}); // 失敗只是少了離線開啟，不影響遊戲（E11）
}

// Android Chrome 可以直接跳出安裝視窗；iPhone 沒有，只能照步驟按
store.installPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  store.installPrompt = e;
  changed();
});

export async function promptInstall() {
  const prompt = store.installPrompt;
  if (!prompt) return;
  store.installPrompt = null;
  await prompt.prompt();
  changed();
}

/** 用手機瀏覽器開、還沒加入也還沒略過時，先出 S23。 */
export function wantsInstallGuide(tokens) {
  return Boolean(PLATFORM) && !STANDALONE && !tokens.player && !tokens.admin && !load('install_skipped');
}

export function skipInstallGuide() {
  save('install_skipped', true);
  changed();
}

/** 螢幕會不會自己關：瀏覽器能鎖住，或玩家說已經把自動鎖定改成永不。 */
export function screenStaysOn() {
  return (store.wake.supported && !store.wake.failed) || Boolean(load('wake_manual'));
}

export function confirmScreenManual() {
  save('wake_manual', true);
  changed();
}

// 準備檢查的結果回報給伺服器，管理員開始前才知道誰的螢幕可能會關
let reported = null;
subscribe(() => {
  const server = store.server;
  const mine = server?.me && (server.roster ?? []).find((p) => p.id === server.me.id);
  if (!mine || server.phase !== 'lobby' || store.conn !== 'online') return;
  const prep = { wakelock: screenStaysOn(), pwa: STANDALONE };
  const key = JSON.stringify(prep);
  if (mine.prep?.wakelock === prep.wakelock && mine.prep?.pwa === prep.pwa) {
    reported = key;
    return;
  }
  if (reported === key) return;
  reported = key;
  send('prep.report', prep).then((result) => {
    if (!result.ok) reported = null;
  });
});
