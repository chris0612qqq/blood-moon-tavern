// 非遊戲分頁與共用畫面：聊天、狼人頻道、我的角色、玩家、S18 結算、S21 設定、S26 規則速查。
import { h } from '../dom.js';
import { api, send } from '../net.js';
import { loadTokens, clearPlayerToken } from '../session.js';
import { changed, store } from '../store.js';
import { causeJoke, causePlain, deathLabel, roleName, t } from '../strings.js';
import { actionButton, avatar, button, nameOf } from '../ui/common.js';
import { ROLE } from '../protocol.js';
import { roleCard } from './night.js';

const DAY_STEPS = new Set(['DAWN', 'HUNTER', 'LAST_WORDS', 'DAY_SPEAK', 'VOTE', 'REVEAL']);
const CHAT_MAX = 500;
const CHAT_WARN = 50;
const FIRST_CHAT_ID = 1;
export const NIGHT_STEPS = new Set(['NIGHT_START', 'WOLF', 'WOLF_END', 'SEER', 'SEER_END', 'WITCH', 'WITCH_END']);

function displayName(server, msg) {
  if (msg.is_host_msg) return t('chat.host');
  if (msg.is_wolf_mask) return t('chat.wolfName');
  return nameOf(server, msg.display_player_id);
}

function bubble(server, msg) {
  // 假扮和匿名訊息不放到右邊：旁人瞄到畫面也不會立刻看出是他發的
  const mine = msg.mine && !msg.disguised_by_me && !msg.masked_by_me;
  const classes = ['bubble', mine ? 'bubble--mine' : '', msg.is_host_msg ? 'bubble--host' : '',
    msg.is_wolf_mask ? 'bubble--wolf' : ''];
  return h('div', { class: classes.join(' '), key: `m${msg.id}`, testid: `chat-${msg.id}` },
    h('div', { class: 'bubble__who' }, displayName(server, msg),
      msg.disguised_by_me ? ` ${t('chat.fakeMark', { name: displayName(server, msg) })}` : '',
      msg.masked_by_me ? ` ${t('chat.wolfMark')}` : '',
      msg.real_author ? ` ← ${nameOf(server, msg.real_author)}` : ''),
    msg.content);
}

function postBlock(server, channel) {
  const me = server.me;
  if (server.host) return channel === 'wolf' ? t('chat.wolfDead') : null;
  if (server.phase === 'lobby' || server.step === 'END') return null;
  if (!me) return t('chat.spectator');
  if (channel === 'wolf') return me.alive ? null : t('chat.wolfDead');
  if (NIGHT_STEPS.has(server.step)) return t('chat.night');
  return me.alive ? null : t('chat.dead');
}

function asButton(label, value, active) {
  return button(label, () => { store.ui.chatAs = value; changed(); }, {
    small: true,
    kind: active ? 'suggest' : 'secondary',
    testid: `chat-as-${value}`,
  });
}

// 送出鈕寫出身分，避免切了之後忘記（SPEC C9.2 #7）
function sendLabel(fake, masked, targetName) {
  if (fake) return t('chat.sendAs', { name: targetName });
  if (masked) return t('chat.sendAs', { name: t('chat.wolfName') });
  return t('chat.send');
}

// 一開始只帶最近一頁（CODING_RULES P6）。訊息 id 全房從 1 連號，不能用則數判斷：
// 看不到的狼人訊息和 64 KB 裁切都會讓則數變少。最舊的不是 1 號就可能還有更舊的
function olderButton(channel, messages) {
  if (!messages.length || messages[0].id <= FIRST_CHAT_ID || store.ui.chatEnd[channel]) return null;
  return actionButton({
    id: 'chat-older',
    small: true,
    kind: 'secondary',
    label: t('chat.older'),
    run: () => {
      // 記下高度：舊訊息插到上面時，畫面要停在原本看的地方（iPhone 不會自己維持）
      store.ui.chatHeight = document.querySelector('.chat__list')?.scrollHeight ?? null;
      return send('chat.history', { channel, before_id: messages[0].id });
    },
  });
}

export function chatTab(server, channel) {
  const messages = (server.chat ?? []).filter((m) => m.channel === channel);
  const block = postBlock(server, channel);
  const draftKey = `chat-${channel}`;
  const draft = store.ui.drafts[draftKey] ?? '';
  const canFake = channel === 'public' && server.me?.can_disguise;
  const canMask = channel === 'public' && server.me?.can_wolf_mask;
  // 選過的身分現在不能用（例如天黑、死亡）就回到本人，不會誤用舊身分送出
  const fake = canFake && store.ui.chatAs === 'fake';
  const masked = canMask && store.ui.chatAs === 'wolf';
  const target = server.me?.disguise_info?.target;
  return h('div', { class: 'chat' },
    h('div', { class: 'chat__list', testid: `chat-list-${channel}` },
      olderButton(channel, messages),
      messages.length ? messages.map((m) => bubble(server, m)) : h('p', { class: 'hint center' }, t('chat.empty'))),
    canFake || canMask ? h('div', { class: 'row' },
      asButton(t('chat.asSelf'), 'self', !fake && !masked),
      canMask ? asButton(t('chat.asWolf'), 'wolf', masked) : null,
      canFake ? asButton(t('chat.asFake', { name: nameOf(server, target) }), 'fake', fake) : null) : null,
    !block && CHAT_MAX - draft.length <= CHAT_WARN
      ? h('p', { class: 'hint', testid: 'chat-left' }, t('chat.left', { n: CHAT_MAX - draft.length }))
      : null,
    block ? h('p', { class: 'hint center', testid: 'chat-blocked' }, block) : h('div', { class: 'chat__input' },
      h('textarea', {
        testid: 'chat-input',
        placeholder: t('chat.placeholder'),
        maxlength: CHAT_MAX,
        value: draft,
        oninput: (e) => { store.ui.drafts[draftKey] = e.target.value; changed(); },
      }),
      h('div', { style: 'width:110px' }, actionButton({
        id: `chat-send-${channel}-${(server.chat ?? []).length}`,
        small: true,
        label: sendLabel(fake, masked, nameOf(server, target)),
        disabled: draft.trim() ? null : ' ',
        run: async () => {
          const fields = { channel, kind: 'text', content: draft };
          if (fake) fields.as = 'disguise';
          if (masked) fields.as = 'wolf';
          const result = await send('chat.send', fields);
          if (result.ok) {
            store.ui.drafts[draftKey] = '';
            changed();
          }
          return result;
        },
      }))));
}

export function roleTab(server) {
  const me = server.me;
  if (!me?.role) return h('p', { class: 'hint center' }, t('chat.spectator'));
  return [
    h('h1', { testid: 'view-role' }, t('tab.role')),
    roleCard(server),
  ];
}

/** 無管理員模式的管理員：白天在遊戲畫面就按得到暫停（SPEC A3）。上帝控制台有自己的暫停鈕。 */
export function pauseButton(server) {
  if (!server.is_admin || server.host || server.paused || !DAY_STEPS.has(server.step)) return null;
  return h('div', { class: 'pause-row' },
    actionButton({ id: 'btn-pause', small: true, kind: 'secondary', label: t('s16.pause'), run: () => send('admin.pause') }));
}

export function playersTab(server) {
  const list = server.players ?? server.roster ?? [];
  const offline = new Set((server.roster ?? []).filter((r) => r.offline).map((r) => r.id));
  const canEnd = server.is_admin && !server.host && server.phase === 'game' && server.step !== 'END';
  return [
    h('h1', { testid: 'view-players' }, t('players.title')),
    [...list].sort((a, b) => a.seat - b.seat).map((p) => h('div', { class: 'list-row', key: p.id },
      h('span', {}, `#${p.seat}`),
      avatar(server, p.id),
      h('span', { class: 'grow' }, p.name),
      offline.has(p.id) ? h('span', { class: 'badge' }, t('s5.offlineTag')) : null,
      p.alive === false ? h('span', { class: 'hint', testid: `player-cause-${p.id}` }, causePlain(p.death_cause)) : null,
      p.alive === false ? h('span', { class: 'badge' }, `☠ ${roleName(p.public_role ?? p.role)}`.trim()) : null)),
    (server.history ?? []).length ? h('h2', {}, t('players.log')) : null,
    (server.history ?? []).map((row) => h('div', { class: 'panel', key: `round${row.round_no}` },
      h('b', {}, t('players.round', { n: row.round_no })),
      h('div', {}, t('players.deaths', {
        names: row.deaths.length
          ? row.deaths.map((id) => deathLabel(nameOf(server, id), row.causes?.[id])).join('、')
          : t('players.nobody'),
      })),
      row.saved ? h('div', { testid: `log-saved-${row.round_no}` }, t('players.saved', { name: nameOf(server, row.saved) })) : null,
      row.ballots ? Object.entries(row.ballots).map(([from, to]) => h('div', { class: 'hint', key: from },
        t('s15.ballot', { from: nameOf(server, from), to: to ? nameOf(server, to) : t('s14.abstain') }))) : null)),
    canEnd
      ? h('div', { class: 'far-apart' }, actionButton({
        id: 'btn-admin-end',
        label: t('s20.end'),
        kind: 'danger',
        confirm: t('s20.endConfirm'),
        run: () => send('admin.end'),
      }))
      : null,
  ];
}

function roleHolder(server, truth, role) {
  // 千面狼與狼人各自分開；女巫、預言家、獵人每局最多一人
  return Object.entries(truth.roles ?? {}).find(([, r]) => r === role)?.[0] ?? null;
}

function actRow(kind, label, ...content) {
  return h('div', { class: `act act--${kind}`, testid: `act-${kind}` },
    h('b', { class: 'act__label' }, label),
    h('div', {}, content));
}

function wolfRow(server, night, name) {
  const picks = Object.entries(night.wolf_picks ?? {});
  const detail = picks.map(([wolf, target]) => t('s18.wolfPick', {
    who: name(wolf),
    target: target ? name(target) : t('s8.empty'),
  })).join('、');
  const result = night.wolf_target ? t('s18.wolfKill', { target: name(night.wolf_target) }) : t('s18.wolfEmpty');
  return actRow('wolf', t('s18.actWolf'), detail || t('s18.wolfNone'), ' ', result);
}

function outBefore(truth, playerId, n) {
  const died = truth.death_rounds?.[playerId];
  return died !== undefined && died < n;
}

function seerRow(server, truth, night, name) {
  const seer = roleHolder(server, truth, ROLE.SEER);
  if (!seer) return actRow('seer', t('s18.actSeer'), t('s18.noRole'));
  if (outBefore(truth, seer, night.round_no)) return actRow('seer', t('s18.actSeer'), t('s18.outAlready', { who: name(seer) }));
  if (!night.seer_target) return actRow('seer', t('s18.actSeer'), t('s18.seerNone', { who: name(seer) }));
  return actRow('seer', t('s18.actSeer'), t('s18.seerAct', {
    who: name(seer),
    target: name(night.seer_target),
    result: t(night.seer_is_wolf ? 'role.wolfResult' : 'role.goodResult'),
  }));
}

function witchRow(server, truth, night, name) {
  const witch = roleHolder(server, truth, ROLE.WITCH);
  if (!witch) return actRow('witch', t('s18.actWitch'), t('s18.noRole'));
  if (outBefore(truth, witch, night.round_no)) return actRow('witch', t('s18.actWitch'), t('s18.outAlready', { who: name(witch) }));
  if (night.witch_saved) return actRow('witch', t('s18.actWitch'), t('s18.witchSave', { who: name(witch), target: name(night.wolf_target) }));
  if (night.witch_poison) return actRow('witch', t('s18.actWitch'), t('s18.witchPoison', { who: name(witch), target: name(night.witch_poison) }));
  return actRow('witch', t('s18.actWitch'), t('s18.witchNone', { who: name(witch) }));
}

function nightPanel(server, truth, night, name) {
  const n = night.round_no;
  const dead = (causes) => Object.entries(truth.death_causes ?? {})
    .filter(([id, cause]) => truth.death_rounds?.[id] === n && causes.includes(cause));
  const dawn = dead(['bite', 'poison']);
  const dayOut = dead(['vote', 'hunter', 'manual']);
  const label = ([id, cause]) => t('s18.deathRow', { name: name(id), cause: causePlain(cause) });
  const shots = (truth.hunter_shots ?? []).filter((shot) => shot.round_no === n);
  const votes = (truth.votes ?? []).find((v) => v.round_no === n);
  return h('div', { testid: `truth-night-${n}` },
    wolfRow(server, night, name),
    seerRow(server, truth, night, name),
    witchRow(server, truth, night, name),
    actRow('death', t('s18.actDeath'), [
      dawn.length ? dawn.map(label).join('、') : (night.witch_saved ? '' : t('s18.peaceful')),
      night.witch_saved ? h('div', {}, t('s18.saved', { name: name(night.wolf_target) })) : null,
    ]),
    shots.map((shot) => actRow('hunter', t('s18.actHunter'), t(shot.target ? 's18.hunterShot' : 's18.hunterHolster', {
      who: name(shot.hunter),
      target: shot.target ? name(shot.target) : '',
    }))),
    actRow('vote', t('s18.actVote'), votes?.revealed
      ? [
        h('div', {}, votes.exiled ? t('s18.exiled', { name: name(votes.exiled) }) : t('s18.tie')),
        Object.entries(votes.ballots).map(([from, to]) => h('div', { class: 'hint', key: from },
          t('s15.ballot', { from: name(from), to: to ? name(to) : t('s14.abstain') }))),
      ]
      : t('s18.noVote')),
    dayOut.length ? h('p', { class: 'hint' }, t('s18.dayDeath', { names: dayOut.map(label).join('、') })) : null);
}

function truthSummary(server, truth, name) {
  const periods = truth.disguise?.periods ?? [];
  return [
    h('h2', {}, t('s18.roles')),
    [...server.players].sort((a, b) => a.seat - b.seat).map((p) => h('div', { class: 'list-row', key: p.id },
      avatar(server, p.id),
      h('span', { class: 'nowrap' }, p.name),
      // 夜晚死因結算才公開（SPEC A2）
      truth.death_causes?.[p.id]
        ? h('span', { class: 'hint end-cause', testid: `end-cause-${p.id}` }, causeJoke(truth.death_causes[p.id], p.role))
        : null,
      h('span', { class: 'badge', testid: `end-role-${p.id}` }, roleName(p.role)))),
    h('h2', {}, t('s18.disguise')),
    periods.map((period, i) => h('p', { key: `p${i}` }, t('s18.period', { from: period.from_round, name: name(period.target_id) }))),
    (truth.disguised_messages ?? []).map((m) => h('p', { key: `f${m.id}` }, t('s18.fakeMsg', {
      id: m.id,
      real: name(m.real_author),
      shown: m.display ? name(m.display) : t('chat.wolfName'),
    }))),
    (truth.bets ?? []).length ? h('h2', {}, t('s18.bets')) : null,
    // SPEC A13：名次、分數、每人押了誰
    (truth.bets ?? []).map((b) => h('div', { class: 'panel', key: `b${b.player_id}`, testid: `end-bet-${b.player_id}` },
      h('div', {}, t('s18.betRow', { rank: b.rank, name: name(b.player_id), score: b.score })),
      h('div', { class: 'hint' }, t('s18.betPicks', {
        wolves: b.wolves.length ? b.wolves.map(name).join('、') : t('players.nobody'),
        faceless: name(b.faceless),
      })))),
  ];
}

export function s18(server) {
  const truth = server.truth ?? {};
  const name = (id) => (id ? nameOf(server, id) : t('s20.nobody'));
  const title = { village: 's18.village', wolf: 's18.wolf', none: 's18.none' }[server.winner] ?? 's18.none';
  const nights = truth.nights ?? [];
  const current = store.ui.truthTab ?? 'summary';
  const tab = (id, label) => h('button', {
    class: `tab tab--small ${current === id ? 'tab--on' : ''}`,
    key: `truth-${id}`,
    testid: `truth-tab-${id}`,
    onclick: () => { store.ui.truthTab = id; changed(); },
  }, label);
  const night = nights.find((n) => String(n.round_no) === current);
  return [
    h('h1', { class: 'center', testid: 'screen-s18' }, t(title)),
    store.closesAt ? h('p', { class: 'center hint' }, t('s18.closing'),
      h('div', { class: 'count', 'data-deadline': store.closesAt, 'data-clock': 'mmss' }, '')) : null,
    h('h2', {}, t('s18.truth')),
    h('div', { class: 'truth-tabs', testid: 'truth-tabs' },
      tab('summary', t('s18.tabSummary')),
      nights.map((n) => tab(String(n.round_no), t('s18.tabNight', { n: n.round_no })))),
    truth.nights_hidden ? h('p', { class: 'hint center', testid: 'truth-hidden' }, t('s18.hidden', { n: truth.max_nights })) : null,
    night ? nightPanel(server, truth, night, name) : truthSummary(server, truth, name),
    server.is_admin ? actionButton({
      id: 'btn-end-close',
      label: t('s18.closeNow'),
      kind: 'danger',
      confirm: t('s2.closeConfirm'),
      run: () => api('/api/admin/room', { method: 'DELETE', auth: loadTokens().admin }),
    }) : null,
  ];
}

export function s21() {
  const server = store.server;
  const close = () => { store.ui.overlay = null; changed(); };
  return [
    h('h1', { testid: 'screen-s21' }, t('s21.title')),
    server?.me && server.room?.mode === 'auto'
      ? actionButton({ id: 'btn-takeover', label: t('s21.takeover'), run: () => send('narrator.takeover') })
      : null,
    h('p', { class: 'hint center', testid: 'voice-status' }, t('voice.status', {
      status: store.voice.last || t('voice.never'),
      name: store.voice.name || t('voice.none'),
      count: store.voice.voices,
    })),
    button(t('s21.export'), () => {
      const text = JSON.stringify(store.errorLog ?? [], null, 1);
      store.ui.dialog = { kind: 'text', text };
      changed();
    }),
    button(t('s21.leave'), () => {
      clearPlayerToken();
      location.reload();
    }),
    button(t('common.close'), close, { testid: 'btn-settings-close' }),
    h('p', { class: 'hint center' }, t('s21.version', { v: store.health?.version ?? '' })),
  ];
}

export function s26() {
  const close = () => { store.ui.overlay = null; changed(); };
  return [
    h('h1', { testid: 'screen-s26' }, t('s26.title')),
    h('p', {}, t('s26.goal')),
    h('p', {}, t('s26.night')),
    h('p', {}, t('s26.mask')),
    h('p', {}, t('s26.witch')),
    h('p', {}, t('s26.hunter')),
    h('p', {}, t('s26.terms')),
    button(t('common.close'), close, { testid: 'btn-rules-close' }),
  ];
}
