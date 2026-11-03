// 美術垂直切片的預覽頁（DEV_PLAN P8）：用假資料畫真正的 S8，不用開一局就能在手機上看每種狀態。
// 不連伺服器；點格子只改這頁的假資料。
import { h, render } from './dom.js';
import { serverNow } from './net.js';
import { speak } from './narrator.js';
import { s8 } from './screens/night.js';
import { wolfHowl } from './sfx.js';
import { changed, store, subscribe } from './store.js';
import { tickClocks, watchFrames } from './ui/clock.js';

const NAMES = ['阿狼', '小明', '大華', '美玲', '老王', '志強', '雅婷', '阿傑'];
const ME = 'p1';
const ALLY = 'p5';
const WOLF_OPEN = '狼人請睜眼，請選擇今晚要殺的人';
const players = NAMES.map((name, i) => ({ id: `p${i + 1}`, seat: i + 1, name, alive: true }));
let state = 'picking';
let confirmTimer = null;

function pack(picks, extra = {}) {
  return { pack: [ME, ALLY], picks, decided: false, confirming_until: null, decided_target: null, ...extra };
}

const STATES = {
  picking: ['選擇中', () => ({ deadline: serverNow() + 45, wolf: pack({}) })],
  ally: ['同伴已選', () => ({ deadline: serverNow() + 38, wolf: pack({ [ALLY]: 'p3' }) })],
  agree: ['全員一致', () => ({ deadline: serverNow() + 30, wolf: pack({ [ME]: 'p3', [ALLY]: 'p3' }, { confirming_until: serverNow() + 3 }) })],
  done: ['已確認', () => ({ deadline: serverNow() + 20, wolf: pack({ [ME]: 'p3', [ALLY]: 'p3' }, { decided: true, decided_target: 'p3' }) })],
  warn: ['剩 10 秒', () => ({ deadline: serverNow() + 10.9, wolf: pack({ [ALLY]: 'p3' }) })],
  paused: ['暫停', () => ({ deadline: serverNow() + 30, paused: true, wolf: pack({}) })],
};

function setState(name) {
  state = name;
  clearTimeout(confirmTimer);
  const { deadline, paused = false, wolf } = STATES[name][1]();
  store.server = {
    phase: 'game',
    step: 'WOLF',
    round_no: 1,
    players,
    roster: players,
    deadline,
    opens_at: null,
    paused,
    me: { id: ME, alive: true, role: 'WOLF', is_actor: true, eligible_targets: players.map((p) => p.id), wolf_pack: wolf },
  };
  // 一致之後 3 秒自動確認，跟真的一樣
  if (name === 'agree') confirmTimer = setTimeout(() => setState('done'), 3000);
  changed();
}

// 點格子：只改假資料（真的畫面會送給伺服器，這裡沒有伺服器）
document.addEventListener('click', (e) => {
  const cell = e.target.closest?.('[data-testid^="pick-cell-"]');
  const wolf = store.server?.me.wolf_pack;
  if (!cell || !wolf || wolf.decided) return;
  const value = cell.dataset.testid.slice('pick-cell-'.length);
  const target = value === 'none' ? null : value;
  const picks = { ...wolf.picks };
  if (ME in picks && picks[ME] === target) delete picks[ME];
  else picks[ME] = target;
  const agreed = ME in picks && ALLY in picks && picks[ME] === picks[ALLY];
  store.server.me.wolf_pack = pack(picks, agreed ? { confirming_until: serverNow() + 3 } : {});
  clearTimeout(confirmTimer);
  if (agreed) {
    confirmTimer = setTimeout(() => {
      store.server.me.wolf_pack = pack(picks, { decided: true, decided_target: picks[ME] });
      changed();
    }, 3000);
  }
  changed();
}, true);

function bar() {
  return h('div', { class: 'preview-bar' },
    Object.entries(STATES).map(([name, [label]]) => h('button', {
      'data-on': state === name,
      onclick: () => setState(name),
    }, label)),
    h('button', {
      onclick: () => {
        const waitMs = wolfHowl();
        if (waitMs) setTimeout(() => speak(WOLF_OPEN), waitMs);
        else speak(WOLF_OPEN);
      },
    }, '🐺 狼嚎＋旁白'));
}

function draw() {
  render(document.getElementById('app'), bar(), h('div', { class: 'main' }, s8(store.server)));
}

function frame(ms) {
  watchFrames(ms);
  tickClocks(serverNow());
  requestAnimationFrame(frame);
}

subscribe(draw);
setState('picking');
requestAnimationFrame(frame);
