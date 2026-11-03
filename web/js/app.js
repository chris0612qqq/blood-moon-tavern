// 進入點：畫面外框、單一時鐘、健康檢查。畫面內容由 router 依狀態決定（CODING_RULES V1）。
import { h, render } from './dom.js';
import { api, connect, findServer, retryNow, serverNow } from './net.js';
import { STEP } from './protocol.js';
import { resolveScreen } from './router.js';
import './wake.js';
import './pwa.js';
import { lightboxLayer } from './ui/media.js';
import { tickClocks, watchFrames } from './ui/clock.js';
import { clearAdminToken, clearPlayerToken, loadTokens } from './session.js';
import { changed, store, subscribe } from './store.js';
import { stepName, t } from './strings.js';
import { button, deadTag, nameOf } from './ui/common.js';
import { refreshAdminRoom, s0, s1, s2, s25, s3, s4 } from './screens/entry.js';
import { s5 } from './screens/s5_lobby.js';
import { s23 } from './screens/install.js';
import { s10, s19, s6, s7, s8, s9 } from './screens/night.js';
import { s11, s12, s13, s14, s15, s16, s17, s22 } from './screens/day.js';
import { lobbyMenu, s20 } from './screens/host.js';
import { broadcastTab } from './screens/broadcast.js';
import { chatTab, NIGHT_STEPS, pauseButton, playersTab, roleTab, s18, s21, s26 } from './screens/tabs.js';

const HEALTH_MS = 5000;
const TOAST_MS = 3000;
const ERROR_LOG_LIMIT = 50;
const CHAT_STICK_PX = 40;
const UNREAD_MAX = 99;
const CHANNEL_OF_TAB = Object.freeze({ chat: 'public' });
const SCREENS = {
  S0: s0, S1: s1, S2: s2, S3: s3, S4: s4, S5: s5, S6: s6, S7: s7, S8: s8, S9: s9, S10: s10,
  S11: s11, S12: s12, S13: s13, S14: s14, S15: s15, S17: s17, S18: s18, S20: s20, S21: s21,
  S22: s22, S23: s23, S25: s25, S26: s26,
};
const OVERLAY_SCREENS = new Set(['S1', 'S2', 'S3', 'S21', 'S23', 'S26']);

store.errorLog = [];

/** 狀態列標題，一行一件事，窄手機也不會斷在字中間。 */
function statusTitle(server) {
  if (!server) return [t('app.name')];
  if (server.phase !== 'game') return [server.room?.name ?? t('app.name'), t('phase.lobby')];
  if (!server.round_no) return [stepName(server.step)];
  return [t('phase.round', { n: server.round_no }), stepName(server.step)];
}

function statusBar() {
  const server = store.server;
  const conn = store.conn;
  const myName = server?.me ? nameOf(server, server.me.id) : null;
  return h('div', { class: 'status' },
    h('span', { class: 'status__title', testid: 'status-title' },
      statusTitle(server).map((line) => h('span', { class: 'status__line' }, line))),
    h('div', { class: 'status__side' },
      h('div', { class: 'status__icons' },
        iconButton('?', 'S26', 'btn-rules'),
        iconButton('⚙', 'S21', 'btn-settings'),
        iconButton('🔑', 'admin', 'btn-admin-key')),
      server
        ? h('div', { class: 'status__who' },
          myName ? h('span', { class: 'status__name', testid: 'status-name' }, myName) : null,
          h('span', { class: `conn conn--${conn}`, testid: 'conn-light' }, t(`conn.${conn}`)))
        : null));
}

function iconButton(label, target, testid) {
  return h('button', {
    class: 'status__icon',
    testid,
    onclick: async () => {
      if (target !== 'admin') {
        store.ui.overlay = target;
      } else if (loadTokens().admin) {
        store.ui.overlay = 'S2';
        await refreshAdminRoom();
      } else {
        store.ui.overlay = 'S1';
      }
      changed();
    },
  }, label);
}

function connBanner() {
  if (!store.server || store.conn === 'online' || store.conn === 'connecting') return null;
  const offline = store.conn === 'offline';
  return h('div', { class: `banner ${offline ? 'banner--error' : ''}`, testid: 'conn-banner' },
    offline ? t('banner.offline') : t('banner.reconnecting', { n: store.attempts }),
    button(t('banner.retry'), retryNow, { small: true }));
}

function tabs(server) {
  const list = [['game', t('tab.game')], ['chat', t('tab.chat')]];
  if (server.me?.role) list.push(['role', t('tab.role')]);
  list.push(['players', t('tab.players')]);
  if (server.is_admin) list.push(['broadcast', t('tab.broadcast')]);
  return h('div', { class: 'tabs' }, list.map(([id, label]) => {
    const channel = CHANNEL_OF_TAB[id];
    const unread = channel ? store.ui.unread[channel] ?? 0 : 0;
    return h('button', {
      class: `tab ${store.ui.tab === id ? 'tab--on' : ''}`,
      key: id,
      testid: `tab-${id}`,
      onclick: () => {
        store.ui.tab = id;
        if (channel) {
          store.ui.chatChannel = channel; // 每次打開都先看公共，旁人瞄到也看不出是狼
          store.ui.unread = { ...store.ui.unread, [channel]: 0 };
        }
        changed();
      },
    }, label, unread ? h('span', { class: 'tab__unread', testid: `unread-${id}` }, unread > UNREAD_MAX ? `${UNREAD_MAX}+` : String(unread)) : null);
  }));
}

function tabContent(server) {
  switch (store.ui.tab) {
    case 'chat': return chatTab(server);
    case 'role': return roleTab(server);
    case 'players': return playersTab(server);
    case 'broadcast': return broadcastTab(server);
    default: return null;
  }
}

function dialogLayer(server) {
  const dialog = store.ui.dialog;
  if (!dialog) return null;
  const close = () => { store.ui.dialog = null; changed(); };
  let content;
  if (dialog.kind === 'lobby-player') content = lobbyMenu(server, dialog.playerId);
  else if (dialog.kind === 'version') {
    content = [h('p', {}, t('dialog.update')), button(t('dialog.reload'), () => location.reload())];
  } else if (dialog.kind === 'text') {
    content = [h('textarea', { style: 'height:200px', value: dialog.text }), button(t('common.close'), close)];
  } else {
    content = [
      h('p', { testid: 'dialog-text', style: 'white-space:pre-line' }, dialog.text),
      h('div', { class: 'row', style: 'gap:16px' },
        h('div', { class: 'grow' }, button(t('common.cancel'), close, { testid: 'dialog-cancel' })),
        h('div', { class: 'grow' }, button(dialog.confirmLabel ?? t('common.confirm'), () => {
          close();
          dialog.onConfirm();
        }, { kind: 'suggest', testid: 'dialog-confirm' }))),
    ];
  }
  return h('div', { class: 'overlay', testid: 'dialog' }, h('div', { class: 'dialog' }, content));
}

function toastLayer() {
  const toast = store.ui.toast;
  if (!toast) return null;
  // 只有換了新的提示才重新計時：控制台每秒重畫，每次都重算就永遠消不掉
  if (store.toastShown !== toast) {
    store.toastShown = toast;
    clearTimeout(store.toastTimer);
    store.toastTimer = setTimeout(() => { store.ui.toast = null; changed(); }, toast.ms ?? TOAST_MS);
  }
  return h('div', { class: 'toast', testid: 'toast' }, t(toast.key, toast.params));
}

function mainContent(screen) {
  const server = store.server;
  if (OVERLAY_SCREENS.has(screen) || !server) return SCREENS[screen](server);
  const tabView = tabContent(server);
  if (tabView) return tabView;
  // 遊戲分頁暫停時蓋上卷軸（UI_RULES F7）；主持人的控制台要能按繼續，所以不蓋
  if (server.paused && !server.host && server.phase === 'game' && server.step !== STEP.END) return [pauseButton(server), s16(server)];
  return [deadTag(server), pauseButton(server), s19(server), SCREENS[screen](server)];
}

// 看最新訊息時跟著捲到底；往上翻舊訊息時不打擾。是否在看最新只由使用者的捲動決定：
// 鍵盤或轉向讓清單變矮時距離底部會變大，但人並沒有往上翻，不能在重繪時用幾何量
let chatPinned = true;

document.addEventListener('scroll', (e) => {
  if (!e.target.matches?.('.chat__list')) return;
  const list = e.target;
  chatPinned = list.scrollHeight - list.scrollTop - list.clientHeight < CHAT_STICK_PX;
}, { capture: true, passive: true });

function settleChatScroll() {
  const list = document.querySelector('.chat__list');
  if (!list) chatPinned = true; // 下次打開聊天從最新開始看
  else if (store.ui.chatRestore !== null) list.scrollTop += list.scrollHeight - store.ui.chatRestore;
  else if ((chatPinned || store.ui.chatStick) && list.scrollTop + list.clientHeight < list.scrollHeight) {
    // 已經在底就不要再設：控制台每秒重畫，一直設會打斷 iPhone 的慣性捲動
    list.scrollTop = list.scrollHeight;
  }
  store.ui.chatRestore = null;
  store.ui.chatStick = false;
}

function draw() {
  const screen = resolveScreen(store);
  const server = store.server;
  // V6：日夜主題只有這一個開關
  document.documentElement.dataset.phase = NIGHT_STEPS.has(server?.step) ? 'night' : 'day';
  document.documentElement.dataset.screen = screen;
  const showTabs = server && !OVERLAY_SCREENS.has(screen) && screen !== 'S25';
  render(document.getElementById('app'),
    statusBar(),
    store.subtitle && server ? h('div', { class: 'subtitle', testid: 'subtitle' }, store.subtitle) : null,
    connBanner(),
    h('div', { class: 'main', testid: `screen-${screen}` }, mainContent(screen)),
    showTabs ? tabs(server) : null,
    dialogLayer(server),
    lightboxLayer(),
    toastLayer(),
    h('div', { class: 'rotate' }, t('rotate')));
  settleChatScroll();
}

// 單一時鐘（UI_RULES Q5、U6）：每影格以 deadline − 校正後的伺服器時間重算，不用計數器
let lastHostRedraw = 0;

function clockFrame(ms) {
  watchFrames(ms);
  const now = serverNow();
  // 上帝控制台的「下一句可以按了」會隨時間變，每秒重畫一次
  if (store.server?.host && performance.now() - lastHostRedraw > 1000) {
    lastHostRedraw = performance.now();
    changed();
  }
  tickClocks(now);
  requestAnimationFrame(clockFrame);
}

async function pollHealth() {
  let res = await api('/api/health');
  if (!res.ok) {
    // 酒館可能換了網址（重開通道），重讀 server.json 再試一次
    await findServer();
    res = await api('/api/health');
  }
  const before = store.health?.room?.state;
  store.healthFailed = !res.ok;
  store.health = res.ok ? res.data : store.health;
  if (res.ok && !store.server && !store.ended) connectFromStorage();
  if (before !== store.health?.room?.state) changed();
  else if (!store.server) changed();
}

function connectFromStorage() {
  const tokens = loadTokens();
  const room = store.health?.room;
  if (!room) return;
  const token = tokens.player ?? (room.mode === 'god' ? tokens.admin : null);
  if (token && store.activeToken !== token) {
    store.activeToken = token;
    connect(token);
  }
}

// CODING_RULES E14：全域錯誤攔截，最近 50 筆可在設定匯出
function recordError(message) {
  store.errorLog.push({ at: Date.now(), message: String(message) });
  store.errorLog.splice(0, Math.max(0, store.errorLog.length - ERROR_LOG_LIMIT));
  store.ui.toast = { key: 'toast.error' };
  changed();
}

window.addEventListener('error', (e) => recordError(e.message));
window.addEventListener('unhandledrejection', (e) => recordError(e.reason));

store.onUnauthorized = () => {
  // token 失效（重啟後主持人、關房後玩家）：清掉，回到登入或加入
  const tokens = loadTokens();
  if (store.activeToken === tokens.player) clearPlayerToken();
  if (store.activeToken === tokens.admin) clearAdminToken();
  store.activeToken = null;
  store.server = null;
  changed();
};
store.refreshHealth = pollHealth;
store.restart = () => {
  store.activeToken = null;
  connect(null);
  pollHealth();
};

// UI_RULES K12：鍵盤跳出來時畫面跟著縮，輸入框移到看得到的地方（等鍵盤動畫結束）
const KEYBOARD_MS = 300;
window.visualViewport?.addEventListener('resize', () => {
  document.documentElement.style.setProperty('--app-h', `${window.visualViewport.height}px`);
  settleChatScroll();
});
document.addEventListener('focusin', (e) => {
  if (e.target.matches('input, textarea')) {
    setTimeout(() => e.target.scrollIntoView({ block: 'center' }), KEYBOARD_MS);
  }
});

// UI_RULES K14：遊戲中按返回不會直接離開。第一次點擊才加歷史，否則瀏覽器會把它跳過
const stayHere = () => history.pushState({ bmt: true }, '');
window.addEventListener('pointerdown', stayHere, { once: true });
window.addEventListener('popstate', () => {
  const playing = store.server?.phase === 'game' && store.server.step !== STEP.END;
  if (!store.ui.overlay && !playing) {
    history.back();
    return;
  }
  stayHere();
  if (store.ui.overlay) store.ui.overlay = null;
  else store.ui.dialog = { text: t('dialog.leave'), confirmLabel: t('dialog.leaveOk'), onConfirm: () => history.go(-2) };
  changed();
});

subscribe(draw);
window.__bmt = store; // Playwright 比對畫面與 store 用（UI_RULES UT1），不含任何別人的秘密
draw();
requestAnimationFrame(clockFrame);
findServer().then(() => {
  pollHealth();
  setInterval(pollHealth, HEALTH_MS);
});
