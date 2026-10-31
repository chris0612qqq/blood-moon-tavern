// 進入點：畫面外框、單一時鐘、健康檢查。畫面內容由 router 依狀態決定（CODING_RULES V1）。
import { h, render } from './dom.js';
import { api, connect, retryNow, serverNow } from './net.js';
import { ROLE_TABLE, STEP } from './protocol.js';
import { resolveScreen } from './router.js';
import { clearAdminToken, clearPlayerToken, loadTokens } from './session.js';
import { changed, store, subscribe } from './store.js';
import { stepName, t } from './strings.js';
import { button, deadTag } from './ui/common.js';
import { refreshAdminRoom, s0, s1, s2, s25, s3, s4 } from './screens/entry.js';
import { s5 } from './screens/s5_lobby.js';
import { s10, s19, s6, s7, s8, s9 } from './screens/night.js';
import { s11, s12, s13, s14, s15, s16, s17, s22, s27 } from './screens/day.js';
import { lobbyMenu, s20 } from './screens/host.js';
import { chatTab, playersTab, roleTab, s18, s21, s26 } from './screens/tabs.js';

const HEALTH_MS = 5000;
const TOAST_MS = 3000;
const ERROR_LOG_LIMIT = 50;
const NIGHT_STEPS = new Set([STEP.NIGHT_START, STEP.WOLF, STEP.WOLF_END, STEP.SEER, STEP.SEER_END, STEP.WITCH, STEP.WITCH_END]);
const SCREENS = {
  S0: s0, S1: s1, S2: s2, S3: s3, S4: s4, S5: s5, S6: s6, S7: s7, S8: s8, S9: s9, S10: s10,
  S11: s11, S12: s12, S13: s13, S14: s14, S15: s15, S17: s17, S18: s18, S20: s20, S21: s21,
  S22: s22, S25: s25, S26: s26, S27: s27,
};
const OVERLAY_SCREENS = new Set(['S1', 'S2', 'S3', 'S21', 'S26', 'S27']);

store.wolfCount = (n) => ROLE_TABLE[n]?.[0] ?? 1;
store.errorLog = [];

function statusTitle(server) {
  if (!server) return t('app.name');
  if (server.phase !== 'game') return `${server.room?.name ?? t('app.name')} · ${t('phase.lobby')}`;
  if (!server.round_no) return stepName(server.step);
  return t('phase.round', { n: server.round_no, step: stepName(server.step) });
}

function statusBar() {
  const server = store.server;
  const conn = store.conn;
  return h('div', { class: 'status' },
    h('span', { class: 'status__title', testid: 'status-title' }, statusTitle(server)),
    server ? h('span', { class: `conn conn--${conn}`, testid: 'conn-light' }, t(`conn.${conn}`)) : null,
    iconButton('?', 'S26', 'btn-rules'),
    iconButton('⚙', 'S21', 'btn-settings'),
    iconButton('🔑', 'admin', 'btn-admin-key'));
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
  if (server.me?.wolf_pack || server.host || (server.step === STEP.END && server.phase === 'game')) {
    list.push(['wolf', t('tab.wolf')]);
  }
  if (server.me?.role) list.push(['role', t('tab.role')]);
  list.push(['players', t('tab.players')]);
  return h('div', { class: 'tabs' }, list.map(([id, label]) => h('button', {
    class: `tab ${store.ui.tab === id ? 'tab--on' : ''}`,
    key: id,
    testid: `tab-${id}`,
    onclick: () => { store.ui.tab = id; changed(); },
  }, label)));
}

function tabContent(server) {
  switch (store.ui.tab) {
    case 'chat': return chatTab(server, 'public');
    case 'wolf': return chatTab(server, 'wolf');
    case 'role': return roleTab(server);
    case 'players': return playersTab(server);
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
  clearTimeout(store.toastTimer);
  store.toastTimer = setTimeout(() => { store.ui.toast = null; changed(); }, TOAST_MS);
  return h('div', { class: 'toast', testid: 'toast' }, t(toast.key, toast.params));
}

function mainContent(screen) {
  const server = store.server;
  if (OVERLAY_SCREENS.has(screen) || !server) return SCREENS[screen](server);
  const tabView = tabContent(server);
  if (tabView) return tabView;
  // 遊戲分頁暫停時蓋上卷軸（UI_RULES F7）；主持人的控制台要能按繼續，所以不蓋
  if (server.paused && !server.host && server.phase === 'game' && server.step !== STEP.END) return s16(server);
  return [deadTag(server), s19(server), SCREENS[screen](server)];
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
    toastLayer(),
    h('div', { class: 'rotate' }, t('rotate')));
}

// 單一時鐘（UI_RULES Q5、U6）：每影格以 deadline − 校正後的伺服器時間重算，不用計數器
let lastHostRedraw = 0;

function clockFrame() {
  const now = serverNow();
  // 上帝控制台的「下一句可以按了」會隨時間變，每秒重畫一次
  if (store.server?.host && performance.now() - lastHostRedraw > 1000) {
    lastHostRedraw = performance.now();
    changed();
  }
  for (const el of document.querySelectorAll('[data-deadline]')) {
    const opens = Number(el.dataset.opens);
    let text;
    if (el.dataset.opens && now < opens) text = t('prep');
    else {
      const left = Math.max(0, Math.ceil(Number(el.dataset.deadline) - now));
      text = el.dataset.clock === 'mmss'
        ? `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`
        : String(left);
    }
    if (el.textContent !== text) el.textContent = text;
  }
  requestAnimationFrame(clockFrame);
}

async function pollHealth() {
  const res = await api('/api/health');
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

subscribe(draw);
window.__bmt = store; // Playwright 比對畫面與 store 用（UI_RULES UT1），不含任何別人的秘密
draw();
requestAnimationFrame(clockFrame);
pollHealth();
setInterval(pollHealth, HEALTH_MS);
