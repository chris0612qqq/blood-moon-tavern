// 管理員的「廣播」分頁（SPEC C4）：選玩家，按字卡或打字，只送到被選的手機。
import { h } from '../dom.js';
import { send } from '../net.js';
import { LIMITS } from '../protocol.js';
import { changed, store } from '../store.js';
import { t } from '../strings.js';
import { cardGrid, cardText } from '../ui/cards.js';
import { actionButton, button, field } from '../ui/common.js';
import { NIGHT_STEPS } from './tabs.js';

function everyone(server) {
  return (server.players ?? server.roster ?? [])
    .filter((p) => !p.is_spectator)
    .sort((a, b) => a.seat - b.seat);
}

function targetCell(player, chosen) {
  return h('button', {
    class: `cell ${chosen.includes(player.id) ? 'cell--on' : ''}`,
    key: player.id,
    testid: `broadcast-target-${player.id}`,
    onclick: () => {
      store.ui.broadcastTargets = chosen.includes(player.id)
        ? chosen.filter((id) => id !== player.id)
        : [...chosen, player.id];
      changed();
    },
  }, `#${player.seat} ${player.name}`);
}

/** 按下就發，可以一直按，所以不用會鎖住的 actionButton。 */
async function sendCard(card, targets) {
  const text = cardText(card);
  const result = await send('admin.broadcast', { targets, text, speak: true, sound: card.sound });
  store.ui.toast = result.ok
    ? { key: 'broadcast.sent', params: { n: targets.length, text } }
    : { key: 'broadcast.failed' };
  changed();
}

export function broadcastTab(server) {
  const form = store.ui.form;
  const players = everyone(server);
  const ids = players.map((p) => p.id);
  // 只留現在還在名單上的；依座位送，一支接一支時順序才看得懂
  const chosen = store.ui.broadcastTargets.filter((id) => ids.includes(id));
  const ordered = ids.filter((id) => chosen.includes(id));
  const text = (form.broadcast_text ?? '').trim();
  const allChosen = chosen.length === ids.length && ids.length > 0;
  const partlyAtNight = NIGHT_STEPS.has(server.step) && chosen.length > 0 && !allChosen;
  return [
    h('h1', { testid: 'view-broadcast' }, t('tab.broadcast')),
    h('p', { class: 'hint' }, t('broadcast.hint')),
    button(allChosen ? t('broadcast.none') : t('broadcast.all'), () => {
      store.ui.broadcastTargets = allChosen ? [] : ids;
      changed();
    }, { testid: 'broadcast-all' }),
    h('div', { class: 'grid' }, players.map((p) => targetCell(p, chosen))),
    partlyAtNight ? h('p', { class: 'error-text', testid: 'broadcast-night-warn' }, t('broadcast.nightWarn')) : null,
    h('h2', {}, t('broadcast.cards')),
    cardGrid((card) => sendCard(card, ordered), !chosen.length || store.conn !== 'online'),
    h('h2', {}, t('broadcast.free')),
    field('broadcast_text', t('broadcast.text'), { maxlength: LIMITS.CHAT_MAX_CHARS }),
    button(store.ui.broadcastSpeak ? t('broadcast.speakOn') : t('broadcast.speakOff'), () => {
      store.ui.broadcastSpeak = !store.ui.broadcastSpeak;
      changed();
    }, { testid: 'broadcast-speak' }),
    field('broadcast_gap', t('broadcast.gap', { max: LIMITS.BROADCAST_MAX_INTERVAL }), { inputmode: 'numeric', maxlength: 2 }),
    actionButton({
      id: 'btn-broadcast-send',
      label: t('broadcast.send', { n: chosen.length }),
      disabled: !text || !chosen.length ? ' ' : null,
      run: () => send('admin.broadcast', {
        targets: ordered,
        text,
        speak: store.ui.broadcastSpeak,
        interval_s: Math.min(Number(form.broadcast_gap) || 0, LIMITS.BROADCAST_MAX_INTERVAL),
      }),
    }),
  ];
}
