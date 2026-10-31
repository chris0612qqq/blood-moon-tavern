// S20 上帝控制台（SPEC C4）：大廳、遊戲中、結算三種狀態。結算共用 S18。
import { h } from '../dom.js';
import { send, serverNow } from '../net.js';
import { LIMITS } from '../protocol.js';
import { unlockAudio } from '../narrator.js';
import { changed, store } from '../store.js';
import { deathLabel, LINE_ORDER, lineLabel, roleName, stepName, t } from '../strings.js';
import { actionButton, avatar, button, countdown, nameOf } from '../ui/common.js';
import { lobbyAdmin, lobbyMenu } from './s5_lobby.js';

export { lobbyMenu };

export function s20(server) {
  if (server.phase === 'lobby') return hostLobby(server);
  return hostGame(server);
}

/** 上帝手機就是旁白主機，一定要有測試聲音的入口（SPEC S24 的精簡版，完整版在 P6）。 */
function soundPanel() {
  const voice = store.voice;
  if (!voice.supported) return h('p', { class: 'error-text', testid: 'sound-unsupported' }, t('voice.unsupported'));
  return [
    button(t('s20.soundTest'), () => {
      unlockAudio(t('s5.soundTest'));
      changed();
    }, { testid: 'btn-sound-test' }),
    h('p', { class: 'hint center' }, t('s20.soundHint')),
    h('p', { class: 'hint center', testid: 'voice-status' }, t('voice.status', {
      status: voice.last || t('voice.never'),
      name: voice.name || t('voice.none'),
      count: voice.voices,
    })),
  ];
}

function hostLobby(server) {
  const players = (server.roster ?? []).filter((r) => !r.is_spectator).sort((a, b) => a.seat - b.seat);
  const need = LIMITS.MIN_PLAYERS - players.length;
  return [
    h('h1', { testid: 'screen-s20' }, t('s20.title')),
    h('p', { testid: 'lobby-count' }, t('s5.count', { n: players.length, cap: server.room?.capacity })),
    soundPanel(),
    lobbyAdmin(server, players, need),
    // 名單放最後：20 人時按鈕才不會被擠到要滑很遠
    players.map((p) => h('div', { class: 'list-row', key: p.id },
      h('span', {}, `#${p.seat}`),
      avatar(server, p.id),
      h('span', { class: 'grow' }, p.name),
      p.offline ? h('span', { class: 'badge' }, t('s5.offlineTag')) : null,
      button('⋯', () => {
        store.ui.dialog = { kind: 'lobby-player', playerId: p.id };
        changed();
      }, { small: true }))),
  ];
}

function nightSummary(server) {
  const night = server.host.nights?.at(-1);
  if (!night || server.step === 'DEAL') return null;
  const name = (id) => (id ? nameOf(server, id) : t('s20.nobody'));
  return h('p', { class: 'hint', testid: 'host-night' }, t('s20.night', {
    wolf: night.wolf_decided ? name(night.wolf_target) : '…',
    seer: name(night.seer_target),
    saved: night.witch_saved ? '✔' : t('s20.nobody'),
    poison: name(night.witch_poison),
  }));
}

function playerStatus(server, id) {
  const host = server.host;
  if (!host.actors.includes(id)) return '—';
  return host.done.includes(id) ? '✔' : '…';
}

function playerRow(server, row) {
  const disguise = server.host.disguise;
  const isFaceless = disguise?.faceless_id === row.id;
  const player = server.players.find((p) => p.id === row.id);
  return h('div', { class: 'list-row', key: row.id, testid: `host-row-${row.id}` },
    h('span', {}, `#${player.seat}`),
    avatar(server, row.id),
    h('span', { class: 'grow' }, player.name),
    h('span', { class: 'badge', testid: `host-role-${row.id}` }, roleName(row.role)),
    isFaceless && disguise.target_id ? h('span', { class: 'badge' }, nameOf(server, disguise.target_id)) : null,
    h('span', { class: 'hint' }, row.alive ? playerStatus(server, row.id) : '☠'));
}

/** 女巫沒事可做時還要裝作在等，回傳建議等到的時間；不用等就回 null。 */
export function witchWaitUntil(server, now) {
  const host = server.host;
  if (server.step !== 'WITCH') return null;
  const nothingToDo = !host.actors.length || (host.witch.antidote_used && host.witch.poison_used);
  const until = host.timers?.min_until;
  return nothingToDo && until && now < until ? until : null;
}

/** 下一句要等目前這句念完、該做的人都做完才高亮，免得金框一按就跳走（使用者試玩回饋）。 */
function nextIsReady(server) {
  const host = server.host;
  const opened = !server.opens_at || serverNow() >= server.opens_at;
  const done = host.timed_out || host.actors.every((id) => host.done.includes(id));
  return opened && done && !witchWaitUntil(server, serverNow());
}

function witchWaitHint(server) {
  const until = witchWaitUntil(server, serverNow());
  if (!until) return null;
  return h('p', { class: 'hint center', testid: 'witch-wait' },
    t('s20.witchWait'), ' ',
    h('span', { 'data-deadline': until }, String(Math.ceil(until - serverNow()))),
    ' ', t('s20.witchWaitUnit'));
}

function voiceControls(server) {
  const line = server.line_id;
  const nextLine = server.host.next_line;
  const speak = store.ui.speakAloud;
  const label = LINE_ORDER.includes(line) ? t('s20.again', { line: lineLabel(line) }) : t('s20.againPlain');
  return [
    line ? actionButton({
      id: 'line-current',
      label,
      kind: 'secondary',
      run: () => send('host.line', { line_id: line, speak }),
    }) : null,
    nextLine
      ? actionButton({
        id: 'btn-host-next',
        label: t('s20.nextLine', { line: lineLabel(nextLine) }),
        kind: nextIsReady(server) ? 'suggest' : 'secondary',
        confirm: unfinishedWarning(server),
        run: () => send('host.line', { line_id: nextLine, speak }),
      })
      : actionButton({
        id: 'btn-host-skip',
        label: t('s20.next'),
        kind: 'secondary',
        run: () => send('host.next'),
      }),
  ];
}

function lineButtons(server) {
  const suggested = nextIsReady(server) ? server.host.next_line : null;
  const speak = store.ui.speakAloud;
  return [
    button(speak ? t('s20.speakPhone') : t('s20.speakSelf'), () => {
      store.ui.speakAloud = !speak;
      changed();
    }, { testid: 'btn-speak-toggle' }),
    h('div', { class: 'grid', style: 'grid-template-columns:1fr 1fr' }, LINE_ORDER.map((line) => {
      const isNext = line === suggested;
      return h('div', { key: line },
        actionButton({
          id: `line-${line}`,
          label: lineLabel(line),
          kind: isNext ? 'suggest' : 'secondary',
          confirm: line === server.host.next_line ? unfinishedWarning(server) : null,
          run: () => send('host.line', { line_id: line, speak }),
        }));
    })),
  ];
}

function unfinishedWarning(server) {
  const host = server.host;
  const left = host.actors.filter((id) => !host.done.includes(id)).length;
  return left && !host.timed_out ? t('s20.unfinished', { n: left }) : null;
}

function overdue(server) {
  return server.deadline && serverNow() > server.deadline && server.host.next_line;
}

function moreMenu(server) {
  if (!store.ui.hostMoreOpen) {
    return button(t('s20.more'), () => { store.ui.hostMoreOpen = true; changed(); }, { testid: 'btn-host-more' });
  }
  const players = server.players;
  return h('div', { class: 'panel danger-zone' },
    players.map((p) => h('div', { class: 'row', key: p.id },
      h('span', { class: 'grow' }, p.name),
      actionButton({
        id: `host-alive-${p.id}`,
        small: true,
        kind: 'secondary',
        label: p.alive ? t('s20.kill') : t('s20.revive'),
        confirm: t('s20.setAliveConfirm', { name: p.name }),
        run: () => send('host.set_alive', { player: p.id, alive: !p.alive }),
      }),
      actionButton({
        id: `host-reshow-${p.id}`,
        small: true,
        kind: 'secondary',
        label: t('s20.reshow'),
        run: () => send('host.reshow_card', { player: p.id }),
      }),
      p.alive ? actionButton({
        id: `host-kick-${p.id}`,
        small: true,
        kind: 'danger',
        label: t('s5.kick'),
        confirm: t('s5.kickConfirm', { name: p.name }),
        run: () => send('admin.kick', { player: p.id }),
      }) : null)),
    actionButton({
      id: 'btn-rollback',
      label: t('s20.rollback'),
      kind: 'danger',
      confirm: t('s20.rollbackConfirm'),
      run: () => send('host.rollback'),
    }),
    actionButton({
      id: 'btn-host-end',
      label: t('s20.end'),
      kind: 'danger',
      confirm: t('s20.endConfirm'),
      run: () => send('admin.end'),
    }),
    button(t('common.close'), () => { store.ui.hostMoreOpen = false; changed(); }));
}

function revealTab(server) {
  const row = (server.history ?? []).find((r) => r.round_no === server.round_no);
  const shots = server.host.hunter_shots ?? [];
  const name = (id) => nameOf(server, id);
  return [
    h('h2', { testid: 'host-view-reveal' }, t('s20.round', { n: server.round_no })),
    h('p', { testid: 'host-deaths' }, row?.deaths?.length
      ? t('s20.deathsNow', { names: row.deaths.map((id) => deathLabel(name(id), row.causes?.[id])).join('、') })
      : t('s20.deathsNone')),
    shots.filter((s) => s.round_no === server.round_no).map((s) => h('p', { key: `shot${s.hunter}` },
      t(s.target ? 's20.shot' : 's20.holster', { who: name(s.hunter), target: s.target ? name(s.target) : '' }))),
    h('h2', {}, t('s20.ballots')),
    row?.ballots
      ? [
        h('p', { testid: 'host-exile' }, row.exiled ? t('s20.exiled', { name: name(row.exiled) }) : t('s20.tie')),
        Object.entries(row.ballots).map(([from, to]) => h('div', { class: 'list-row', key: from },
          t('s15.ballot', { from: name(from), to: to ? name(to) : t('s14.abstain') }))),
      ]
      : h('p', { class: 'hint' }, t('s20.noBallots')),
  ];
}

function statusTab(server) {
  const speaking = server.step === 'DAY_SPEAK' || server.step === 'LAST_WORDS';
  return [
    h('h2', { testid: 'host-view-status' }, t('s20.status')),
    nightSummary(server),
    server.host.players.map((row) => playerRow(server, row)),
    speaking
      ? [
        actionButton({ id: 'btn-skip-speaker', label: t('s20.skipSpeaker'), kind: 'secondary', run: () => send('host.skip_speaker') }),
        actionButton({ id: 'btn-extend', label: t('s20.extend'), kind: 'secondary', run: () => send('host.extend', { s: 30 }) }),
      ]
      : null,
    moreMenu(server),
  ];
}

function voiceTab(server) {
  return [
    h('p', { class: 'hint', testid: 'host-view-voice' }, t('s20.againHint')),
    lineButtons(server),
    soundPanel(),
  ];
}

const HOST_TABS = [
  ['reveal', 's20.tabReveal', revealTab],
  ['status', 's20.tabStatus', statusTab],
  ['voice', 's20.tabVoice', voiceTab],
];

function hostGame(server) {
  const current = store.ui.hostTab ?? 'voice';
  const view = HOST_TABS.find(([id]) => id === current)[2];
  return h('div', { class: 'host-screen' },
    // 常用操作固定在上方，切到哪個標籤都按得到
    h('div', { class: 'host-pinned' },
      h('div', { class: 'row' },
        h('h1', { class: 'grow', testid: 'screen-s20-game' }, stepName(server.step)),
        // 天黑、閉眼這類步驟沒有人要行動，不顯示倒數，免得看起來像逾時
        server.host.actors.length ? countdown(server, overdue(server) ? t('s20.overdue') : null) : null,
        server.paused
          ? null
          : actionButton({ id: 'btn-pause', label: t('s16.pause'), kind: 'secondary', small: true, run: () => send('admin.pause') })),
      witchWaitHint(server),
      voiceControls(server),
      server.paused
        ? actionButton({
          id: 'btn-resume',
          label: t('s16.resume'),
          disabled: server.paused.resume_at ? t('s16.resuming') : null,
          run: () => send('admin.resume'),
        })
        : null),
    h('div', { class: 'host-layout' },
      h('div', { class: 'host-rail' }, HOST_TABS.map(([id, label]) => h('button', {
        class: `host-tab ${current === id ? 'host-tab--on' : ''}`,
        key: id,
        testid: `host-tab-${id}`,
        onclick: () => { store.ui.hostTab = id; changed(); },
      // 兩個字一行（使用者試玩回饋）
      }, t(label).match(/.{1,2}/gu).map((part) => h('span', { class: 'host-tab__line' }, part))))),
      h('div', { class: 'host-content' }, view(server))));
}
