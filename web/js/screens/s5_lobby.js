// S5 大廳（SPEC A4、C4）。灰盒用上移／下移代替拖曳排座位，拖曳在 P5 做。
import { h } from '../dom.js';
import { api, send } from '../net.js';
import { unlockAudio } from '../narrator.js';
import { LIMITS, NO_HUNTER_PLAYER_COUNT, ROLE_TABLE } from '../protocol.js';
import { loadTokens } from '../session.js';
import { changed, store } from '../store.js';
import { t } from '../strings.js';
import { actionButton, avatar, button } from '../ui/common.js';

function seated(server) {
  return (server.roster ?? []).filter((r) => !r.is_spectator).sort((a, b) => a.seat - b.seat);
}

function move(server, id, delta) {
  const order = seated(server).map((r) => r.id);
  const index = order.indexOf(id);
  const target = index + delta;
  if (target < 0 || target >= order.length) return;
  [order[index], order[target]] = [order[target], order[index]];
  send('admin.seat', { order });
}

function row(server, player, isAdmin) {
  const narrator = (server.room?.narrator_id ?? server.narrator_id) === player.id;
  return h('div', { class: 'list-row', key: player.id, testid: `lobby-row-${player.id}` },
    h('span', {}, `#${player.seat}`),
    avatar(server, player.id),
    h('span', { class: 'grow' }, player.name),
    player.is_admin ? h('span', { class: 'badge' }, t('s5.adminTag')) : null,
    narrator ? h('span', { class: 'badge' }, t('s5.narratorTag')) : null,
    player.offline ? h('span', { class: 'badge' }, t('s5.offlineTag')) : null,
    isAdmin ? button('⋯', () => {
      store.ui.dialog = { kind: 'lobby-player', playerId: player.id };
      changed();
    }, { small: true, testid: `lobby-menu-${player.id}` }) : null);
}

export function lobbyMenu(server, playerId) {
  const player = (server.roster ?? []).find((r) => r.id === playerId);
  if (!player) return [];
  const close = () => { store.ui.dialog = null; changed(); };
  return [
    h('h2', {}, player.name),
    button(t('s5.up'), () => { move(server, playerId, -1); }, {}),
    button(t('s5.down'), () => { move(server, playerId, 1); }, {}),
    server.room?.mode === 'auto'
      ? button(t('s5.setNarrator'), () => { send('admin.narrator', { player: playerId }); close(); }, { testid: 'btn-set-narrator' })
      : null,
    button(t('s5.resetPin'), () => { send('admin.reset_pin', { player: playerId }); close(); }),
    button(t('s5.kick'), () => {
      store.ui.dialog = {
        text: t('s5.kickConfirm', { name: player.name }),
        confirmLabel: t('s5.kick'),
        onConfirm: () => send('admin.kick', { player: playerId }),
      };
      changed();
    }, { kind: 'danger', testid: 'btn-kick' }),
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
    button(store.audioUnlocked ? t('s5.soundOn') : t('s5.sound'), () => {
      unlockAudio(t('s5.soundTest'));
      changed();
    }, { testid: 'btn-sound' }),
    // 無管理員模式的管理員要先加入才能開始，否則自己會變旁觀者、也沒有旁白主機
    isAdmin && !server.me && server.room?.mode === 'auto'
      ? h('p', { class: 'hint center', testid: 'lobby-need-join' }, t('s5.joinFirst'))
      : null,
    isAdmin && (server.me || server.room?.mode !== 'auto') ? lobbyAdmin(server, players, need) : null,
    // 名單放最後：20 人時按鈕才不會被擠到要滑很遠
    h('div', {}, players.map((p) => row(server, p, isAdmin))),
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
