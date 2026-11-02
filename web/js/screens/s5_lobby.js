// S5 大廳（SPEC A4、C4）。
import { h } from '../dom.js';
import { api, send } from '../net.js';
import { LIMITS, NO_HUNTER_PLAYER_COUNT, ROLE_TABLE } from '../protocol.js';
import { loadTokens } from '../session.js';
import { changed, store } from '../store.js';
import { t } from '../strings.js';
import { actionButton, avatar, button, toast } from '../ui/common.js';

const DRAG_EDGE = 48;
const DRAG_SCROLL = 24;
const DRAG_TICK_MS = 60;

export function seated(server) {
  return (server.roster ?? []).filter((r) => !r.is_spectator).sort((a, b) => a.seat - b.seat);
}

/** 拖曳中先照手指的順序畫（外觀而已），放手才送伺服器。 */
function dragOrder(players) {
  const order = store.ui.seatDrag?.order;
  if (!order) return players;
  const byId = new Map(players.map((p) => [p.id, p]));
  const kept = order.filter((id) => byId.has(id));
  const joined = players.map((p) => p.id).filter((id) => !kept.includes(id));
  return [...kept, ...joined].map((id, i) => ({ ...byId.get(id), seat: i + 1 }));
}

function dragTo(id, y) {
  const drag = store.ui.seatDrag;
  if (!drag) return;
  const rows = [...document.querySelectorAll('.seat-row')];
  const below = rows.findIndex((r) => y < r.getBoundingClientRect().bottom);
  const target = Math.min(below < 0 ? rows.length - 1 : below, drag.order.length - 1);
  const from = drag.order.indexOf(id);
  if (target !== from) {
    drag.order.splice(from, 1);
    drag.order.splice(target, 0, id);
    changed();
  }
}

// 20 人一頁放不下：手指停在邊緣也要繼續捲，所以用計時器，不靠 pointermove
function edgeScroll(id, y) {
  const main = document.querySelector('.main');
  if (!main) return;
  const box = main.getBoundingClientRect();
  if (y < box.top + DRAG_EDGE) main.scrollBy(0, -DRAG_SCROLL);
  else if (y > box.bottom - DRAG_EDGE) main.scrollBy(0, DRAG_SCROLL);
  else return;
  dragTo(id, y);
}

function startDrag(event, players, id) {
  event.preventDefault();
  if (store.ui.seatDrag) return; // 第二根手指，或上一次還在等伺服器回覆
  const finger = event.pointerId;
  const before = players.map((p) => p.id);
  store.ui.seatDrag = { id, order: [...before] };
  changed();
  let y = event.clientY;
  const onMove = (e) => {
    if (e.pointerId !== finger) return;
    y = e.clientY;
    dragTo(id, y);
  };
  const timer = setInterval(() => edgeScroll(id, y), DRAG_TICK_MS);
  const onEnd = async (e) => {
    if (e.pointerId !== finger) return;
    clearInterval(timer);
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onEnd);
    document.removeEventListener('pointercancel', onEnd);
    const moved = store.ui.seatDrag.order.join() !== before.join();
    // 用現在的名單：拖曳途中可能有人加入，少了他伺服器會拒絕整份座位表
    const order = store.server ? dragOrder(seated(store.server)).map((p) => p.id) : null;
    // 等伺服器回覆才收起來，名單才不會先跳回舊順序
    if (e.type === 'pointerup' && moved && order) {
      const result = await send('admin.seat', { order });
      if (!result.ok) toast('toast.seatFailed');
    }
    store.ui.seatDrag = null;
    changed();
  };
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onEnd);
  document.addEventListener('pointercancel', onEnd);
}

function row(server, player, isAdmin, players) {
  const narrator = (server.room?.narrator_id ?? server.narrator_id) === player.id;
  const dragging = store.ui.seatDrag?.id === player.id;
  return h('div', { class: `list-row seat-row ${dragging ? 'seat-row--drag' : ''}`, key: player.id, testid: `lobby-row-${player.id}` },
    isAdmin ? h('span', {
      class: 'seat-handle',
      testid: `seat-handle-${player.id}`,
      'aria-label': t('s5.dragHint'),
      onpointerdown: (e) => startDrag(e, players, player.id),
    }, '≡') : null,
    h('span', {}, `#${player.seat}`),
    avatar(server, player.id),
    // 標籤放名字下面：管理員同時是旁白又離線時，右邊的按鈕才不會被擠出去
    h('div', { class: 'grow seat-row__who' },
      h('div', { class: 'nowrap' }, player.name),
      player.is_admin || narrator || player.offline ? h('div', { class: 'seat-row__tags' },
        player.is_admin ? h('span', { class: 'badge' }, t('s5.adminTag')) : null,
        narrator ? h('span', { class: 'badge' }, t('s5.narratorTag')) : null,
        player.offline ? h('span', { class: 'badge' }, t('s5.offlineTag')) : null) : null),
    isAdmin ? button('⋯', () => {
      store.ui.dialog = { kind: 'lobby-player', playerId: player.id };
      changed();
    }, { small: true, testid: `lobby-menu-${player.id}` }) : null);
}

/** 旁白手機念不出來要早點知道（CODING_RULES E11）。測試鈕只在進房前，這個警告不是按鈕，要留著。 */
export function voiceWarning(isNarrator) {
  return isNarrator && !store.voice.supported
    ? h('p', { class: 'error-text', testid: 'sound-unsupported' }, t('voice.unsupported'))
    : null;
}

/** 這支手機沒辦法自動保持螢幕亮著時，請玩家手動設定。 */
export function wakeHint() {
  return store.wake.supported && !store.wake.failed
    ? null
    : h('p', { class: 'hint', testid: 'wake-hint' }, t('wake.manual'));
}

/** 大廳名單，玩家畫面和上帝控制台共用。 */
export function lobbyList(server, players, isAdmin) {
  const shown = dragOrder(players);
  return [
    isAdmin && players.length > 1 ? h('p', { class: 'hint', testid: 'seat-hint' }, t('s5.dragHint')) : null,
    shown.map((p) => row(server, p, isAdmin, players)),
  ];
}

export function lobbyMenu(server, playerId) {
  const player = (server.roster ?? []).find((r) => r.id === playerId);
  if (!player) return [];
  const close = () => { store.ui.dialog = null; changed(); };
  // 成功才關選單；失敗要留著，按鈕才看得到原因
  const closeAfter = async (sending, doneToast) => {
    const result = await sending;
    if (result.ok) {
      close();
      if (doneToast) toast(doneToast);
    }
    return result;
  };
  return [
    h('h2', {}, player.name),
    server.room?.mode === 'auto'
      ? actionButton({ id: 'btn-set-narrator', label: t('s5.setNarrator'), run: () => closeAfter(send('admin.narrator', { player: playerId })) })
      : null,
    actionButton({
      id: `btn-reset-pin-${playerId}`,
      label: t('s5.resetPin'),
      kind: 'secondary',
      run: () => closeAfter(send('admin.reset_pin', { player: playerId }), 'toast.pinReset'),
    }),
    button(t('common.close'), close),
  ];
}

function startConfirm(players) {
  const n = players.length;
  const [wolves, villagers] = ROLE_TABLE[n];
  const hunter = n === NO_HUNTER_PLAYER_COUNT.value ? '' : t('s5.hunter');
  const offline = players.filter((p) => p.offline).map((p) => p.name).join('、');
  const summary = t('s5.startConfirm', { n, wolves, hunter, villagers });
  return offline ? `${summary}\n${t('s5.offlineWarn', { names: offline })}` : summary;
}

export function s5(server) {
  const players = seated(server);
  const isAdmin = server.is_admin;
  const need = LIMITS.MIN_PLAYERS - players.length;
  const mine = players.find((p) => p.id === server.me?.id);
  return [
    h('h1', { testid: 'screen-s5' }, server.room?.name ?? t('s5.title')),
    h('div', { class: 'row' },
      h('span', { class: 'grow', testid: 'lobby-count' },
        t('s5.count', { n: players.length, cap: server.room?.capacity ?? LIMITS.MAX_PLAYERS })),
      mine ? h('b', { testid: 'my-seat' }, t('s5.you', { seat: mine.seat })) : null),
    voiceWarning(Boolean(mine) && (server.room?.narrator_id ?? server.narrator_id) === mine.id),
    wakeHint(),
    // 無管理員模式的管理員要先加入才能開始，否則自己會變旁觀者、也沒有旁白主機
    isAdmin && !server.me && server.room?.mode === 'auto'
      ? h('p', { class: 'hint center', testid: 'lobby-need-join' }, t('s5.joinFirst'))
      : null,
    isAdmin && (server.me || server.room?.mode !== 'auto') ? lobbyAdmin(server, players, need) : null,
    // 名單放最後：20 人時按鈕才不會被擠到要滑很遠
    h('div', {}, lobbyList(server, players, isAdmin)),
  ];
}

export function lobbyAdmin(server, players, need) {
  return [
    actionButton({
      id: 'btn-start',
      label: t('s5.start'),
      disabled: need > 0 ? t('s5.needMore', { n: need }) : null,
      confirm: need > 0 ? null : startConfirm(players),
      run: () => send('admin.start'),
    }),
    store.health?.dev ? button(t('s5.addBots'), () => {
      api(`/dev/bots?count=${Math.max(need, 1)}`, { method: 'POST', auth: loadTokens().admin });
    }, { testid: 'btn-add-bots' }) : null,
  ];
}
