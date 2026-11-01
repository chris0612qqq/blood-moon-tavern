// S20 上帝控制台（SPEC C4）：大廳、遊戲中、結算三種狀態。結算共用 S18。
import { h } from '../dom.js';
import { send, serverNow } from '../net.js';
import { LIMITS, ROLE } from '../protocol.js';
import { changed, store } from '../store.js';
import { causePlain, deathLabel, LINE_ORDER, lineLabel, roleName, stepName, t } from '../strings.js';
import { actionButton, avatar, button, countdown, nameOf, pauseToggle } from '../ui/common.js';
import { suspectBoard, voteProgress } from './day.js';
import { actRow } from './tabs.js';
import { lobbyAdmin, lobbyList, lobbyMenu, seated, voiceWarning } from './s5_lobby.js';

export { lobbyMenu };

export function s20(server) {
  if (server.phase === 'lobby') return hostLobby(server);
  return hostGame(server);
}

function hostLobby(server) {
  const players = seated(server);
  const need = LIMITS.MIN_PLAYERS - players.length;
  return [
    h('h1', { testid: 'screen-s20' }, t('s20.title')),
    h('p', { testid: 'lobby-count' }, t('s5.count', { n: players.length, cap: server.room?.capacity })),
    voiceWarning(true),
    lobbyAdmin(server, players, need),
    // 名單放最後：20 人時按鈕才不會被擠到要滑很遠
    h('div', {}, lobbyList(server, players, true)),
  ];
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
      }))),
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
    button(t('common.close'), () => { store.ui.hostMoreOpen = false; changed(); }, { testid: 'btn-host-more-close' }));
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

// 簡報牆的順序；白天的步驟都算過了夜晚
const NIGHT_ORDER = ['NIGHT_START', 'WOLF', 'WOLF_END', 'SEER', 'SEER_END', 'WITCH', 'WITCH_END', 'DAWN'];

function reached(server, step) {
  const at = NIGHT_ORDER.indexOf(server.step);
  return at === -1 || at >= NIGHT_ORDER.indexOf(step);
}

function wallWolf(night, name) {
  const picks = Object.entries(night.wolf_picks ?? {})
    .map(([wolf, target]) => t('s18.wolfPick', { who: name(wolf), target: target ? name(target) : t('s8.empty') }));
  const result = night.wolf_target ? t('s18.wolfKill', { target: name(night.wolf_target) }) : t('s18.wolfEmpty');
  return actRow('wolf', t('s18.actWolf'),
    picks.join('、') || t('s20.wallPicking'), night.wolf_decided ? ` ${result}` : '');
}

/** 這個角色這回合有沒有上場：活著，或是今晚才死的。 */
function holderOf(server, role, row) {
  const holder = server.host.players.find((p) => p.role === role);
  return holder && (holder.alive || row?.deaths?.includes(holder.id)) ? holder.id : null;
}

function wallSeer(server, night, row, name) {
  const seer = holderOf(server, ROLE.SEER, row);
  if (!seer || !reached(server, 'SEER')) return null;
  if (night.seer_target) {
    return actRow('seer', t('s18.actSeer'), t('s18.seerAct', {
      who: name(seer),
      target: name(night.seer_target),
      result: t(night.seer_is_wolf ? 'role.wolfResult' : 'role.goodResult'),
    }));
  }
  return actRow('seer', t('s18.actSeer'), server.step === 'SEER' ? t('s20.wallPicking') : t('s18.seerNone', { who: name(seer) }));
}

function wallWitch(server, night, row, name) {
  const witch = holderOf(server, ROLE.WITCH, row);
  if (!witch || !reached(server, 'WITCH')) return null;
  let text = t('s18.witchNone', { who: name(witch) });
  if (night.witch_saved) text = t('s18.witchSave', { who: name(witch), target: name(night.wolf_target) });
  else if (night.witch_poison) text = t('s18.witchPoison', { who: name(witch), target: name(night.witch_poison) });
  else if (server.step === 'WITCH') text = t('s20.wallPicking');
  return actRow('witch', t('s18.actWitch'), text);
}

function wallDawn(server, night, row, name) {
  if (!reached(server, 'DAWN') || (server.step === 'DAWN' && !server.announced)) return null;
  const dead = (row?.deaths ?? []).filter((id) => ['bite', 'poison'].includes(row.causes?.[id]));
  return actRow('death', t('s18.actDeath'),
    dead.length
      ? dead.map((id) => t('s18.deathRow', { name: name(id), cause: causePlain(row.causes[id]) })).join('、')
      : (night.witch_saved ? '' : t('s18.peaceful')),
    night.witch_saved ? h('div', {}, t('s18.saved', { name: name(night.wolf_target) })) : null);
}

/** 第一輪：投票中看誰選誰，投完看票數和誰進第二輪。誰投誰不留（SPEC A5.4）。 */
function wallFirstRound(server, round, name) {
  const label = t('s20.firstRound');
  if (server.step === 'SUSPECT_VOTE') return actRow('vote', label, voteProgress(server), suspectBoard(server));
  if (!round?.nominees) return null;
  const counts = Object.entries(round.suspect_counts).sort(([, a], [, b]) => b - a)
    .map(([id, n]) => t('s14.nominee', { name: name(id), n }));
  return actRow('vote', label,
    h('div', { class: 'keep-words', testid: 'host-nominees' }, counts.length
      ? t('s14.nominees', { list: counts.join('、') })
      : t('s15.noNominee')),
    counts.length && round.direct && round.revealed
      ? h('div', { testid: 'wall-direct' }, round.exiled ? t('s18.exiled', { name: name(round.exiled) }) : t('s18.tie'))
      : null);
}

/** 第二輪：主持人投票中就看得到誰投誰，揭曉後多一行結果。 */
function wallSecondRound(server, round, name) {
  const ballots = Object.entries(round?.ballots ?? {});
  if (round?.direct || (server.step !== 'VOTE' && !round?.revealed)) return null;
  const counts = {};
  for (const [, to] of ballots) if (to) counts[to] = (counts[to] ?? 0) + 1;
  const tally = Object.entries(counts).sort(([, a], [, b]) => b - a)
    .map(([id, n]) => t('s14.nominee', { name: name(id), n }));
  return actRow('vote', t('s20.secondRound'),
    h('div', { testid: 'wall-second-round' },
      round?.revealed
        ? h('div', {}, round.exiled ? t('s18.exiled', { name: name(round.exiled) }) : t('s18.tie'))
        : voteProgress(server),
      tally.length ? h('div', { class: 'keep-words' }, tally.join('、')) : null,
      ballots.map(([from, to]) => h('div', { class: 'hint', key: from },
        t('s15.ballot', { from: name(from), to: to ? name(to) : t('s14.abstain') })))));
}

/** 行動狀態的簡報牆（使用者要求）：這回合所有選擇和投票，發生一件報一件。 */
function briefingWall(server) {
  const n = server.round_no;
  const night = server.host.nights?.find((x) => x.round_no === n);
  if (!night || server.step === 'DEAL') return null;
  const row = (server.history ?? []).find((r) => r.round_no === n);
  const round = server.host.votes?.find((v) => v.round_no === n);
  const name = (id) => nameOf(server, id);
  return h('div', { testid: 'host-wall' },
    h('h2', {}, t('s20.wallTitle', { n })),
    wallWolf(night, name),
    wallSeer(server, night, row, name),
    wallWitch(server, night, row, name),
    wallDawn(server, night, row, name),
    (server.host.hunter_shots ?? []).filter((s) => s.round_no === n).map((s) => actRow('hunter', t('s18.actHunter'),
      t(s.target ? 's18.hunterShot' : 's18.hunterHolster', { who: name(s.hunter), target: s.target ? name(s.target) : '' }))),
    wallFirstRound(server, round, name),
    wallSecondRound(server, round, name));
}

function statusTab(server) {
  const speaking = ['DAY_SPEAK', 'LAST_WORDS', 'DEFENSE'].includes(server.step);
  return [
    h('h2', { testid: 'host-view-status' }, t('s20.status')),
    briefingWall(server),
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
        pauseToggle(server)),
      witchWaitHint(server),
      voiceControls(server)),
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
