// 非遊戲分頁與共用畫面：聊天、狼人頻道、我的角色、玩家、S18 結算、S21 設定、S26 規則速查。
import { h } from '../dom.js';
import { api, send } from '../net.js';
import { loadTokens, clearPlayerToken } from '../session.js';
import { changed, store } from '../store.js';
import { causeJoke, causePlain, deathLabel, roleName, t } from '../strings.js';
import { actionButton, avatar, button, field, nameOf, pauseToggle } from '../ui/common.js';
import { ROLE } from '../protocol.js';
import { roleCard } from './night.js';
import { speak, VOICE_STYLE } from '../narrator.js';
import { photoBubble, sendPhoto } from '../ui/media.js';

const DAY_STEPS = new Set(['DAWN', 'HUNTER', 'LAST_WORDS', 'DAY_SPEAK', 'SUSPECT_VOTE', 'DEFENSE', 'VOTE', 'REVEAL']);
const CHAT_MAX = 500;
const CHAT_WARN = 50;
const FIRST_CHAT_ID = 1;
export const NIGHT_STEPS = new Set(['NIGHT_START', 'WOLF', 'WOLF_END', 'SEER', 'SEER_END', 'WITCH', 'WITCH_END']);

function displayName(server, msg) {
  if (msg.kind === 'system') return t('chat.system');
  if (msg.is_host_msg) return t('chat.host');
  if (msg.is_wolf_mask) return t('chat.wolfName');
  return nameOf(server, msg.display_player_id);
}

function bubble(server, msg) {
  // 假扮和匿名訊息不放到右邊：旁人瞄到畫面也不會立刻看出是他發的
  const mine = msg.mine && !msg.disguised_by_me && !msg.masked_by_me;
  const classes = ['bubble', mine ? 'bubble--mine' : '', msg.is_host_msg ? 'bubble--host' : '',
    msg.is_wolf_mask ? 'bubble--wolf' : '', msg.kind === 'system' ? 'bubble--system' : ''];
  return h('div', { class: classes.join(' '), key: `m${msg.id}`, testid: `chat-${msg.id}` },
    h('div', { class: 'bubble__who' }, displayName(server, msg),
      msg.disguised_by_me ? ` ${t('chat.fakeMark', { name: displayName(server, msg) })}` : '',
      msg.masked_by_me ? ` ${t('chat.wolfMark')}` : '',
      msg.real_author ? ` ← ${nameOf(server, msg.real_author)}` : ''),
    messageBody(server, msg));
}

function messageBody(server, msg) {
  if (msg.kind === 'photo') return photoBubble(msg);
  if (msg.kind === 'system') return t(msg.content);
  if (msg.kind === 'tts') {
    // 點一下才念：白天大家講話時，收到就念會很吵（使用者決定）。
    // 只能用聽的：發的人、上帝主持人、結算後才看得到原文（SPEC v4.25）
    const showText = msg.mine || server.host || server.step === 'END';
    return h('button', {
      class: 'tts',
      testid: `chat-tts-${msg.id}`,
      onclick: () => speak(msg.content, msg.is_wolf_mask ? VOICE_STYLE.wolf : VOICE_STYLE.normal),
    }, showText ? `🔊 ${msg.content}` : t('chat.ttsHidden'));
  }
  return msg.content;
}

function clockText(due) {
  return new Date(due * 1000).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false });
}

/** 狼人定時電子音（SPEC v4.24）：只有自己看得到，最多兩則，時間到伺服器用「狼人」身分發。 */
function schedulePanel(server) {
  const me = server.me;
  if (!me?.wolf_pack || !me.alive || server.phase !== 'game' || server.step === 'END') return null;
  if (!store.ui.scheduleOpen) {
    return button(t('sched.open'), () => { store.ui.scheduleOpen = true; changed(); }, { small: true, kind: 'secondary', testid: 'sched-open' });
  }
  const form = store.ui.form;
  const saved = new Map((me.wolf_schedules ?? []).map((s) => [s.slot, s]));
  return h('div', { class: 'panel', testid: 'sched-panel' },
    h('p', { class: 'hint' }, t('sched.hint')),
    [0, 1].map((slot) => {
      const item = saved.get(slot);
      if (item) {
        return h('div', { class: 'row', key: `s${slot}`, testid: `sched-saved-${slot}` },
          h('span', { class: 'grow' }, t('sched.row', { time: clockText(item.due), text: item.text })),
          actionButton({ id: `sched-del-${slot}`, small: true, kind: 'secondary', label: t('sched.delete'),
            run: () => send('wolf.unschedule', { slot }) }));
      }
      const time = form[`sched_time_${slot}`] ?? '';
      const text = (form[`sched_text_${slot}`] ?? '').trim();
      return h('div', { key: `s${slot}` },
        h('div', { class: 'row' },
          field(`sched_time_${slot}`, t('sched.time'), { type: 'time' }),
          field(`sched_text_${slot}`, t('sched.text'), { maxlength: CHAT_MAX })),
        actionButton({ id: `sched-save-${slot}`, small: true, label: t('sched.save'),
          disabled: time && text ? null : ' ',
          run: async () => {
            const result = await send('wolf.schedule', { slot, time, text });
            if (result.ok) { form[`sched_time_${slot}`] = ''; form[`sched_text_${slot}`] = ''; }
            return result;
          } }));
    }),
    button(t('common.close'), () => { store.ui.scheduleOpen = false; changed(); }, { small: true, kind: 'secondary', testid: 'sched-close' }));
}

function postBlock(server, channel) {
  const me = server.me;
  if (server.host) return null;  // 上帝主持人兩個頻道都能發言（SPEC v4.25）
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
  // 狼頻道的第一則一定是開局系統訊息（SPEC v4.25），看到它就沒有更舊的了
  if (channel === 'wolf' && messages[0].kind === 'system') return null;
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

function canSeeWolfChannel(server) {
  return Boolean(server.me?.wolf_pack || server.host || (server.step === 'END' && server.phase === 'game'));
}

function channelButton(label, channel, active, testid, unread) {
  return button(unread ? `${label} (${unread})` : label, () => {
    store.ui.chatChannel = channel;
    store.ui.unread = { ...store.ui.unread, [channel]: 0 };
    store.ui.chatStick = true;
    changed();
  }, { small: true, kind: active ? 'suggest' : 'secondary', testid });
}

export function chatTab(server) {
  const canSwitch = canSeeWolfChannel(server);
  const channel = canSwitch ? store.ui.chatChannel : 'public';
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
    canSwitch ? h('div', { class: 'row' },
      channelButton(t('chat.public'), 'public', channel === 'public', 'chat-channel-public', 0),
      channelButton(t('tab.wolf'), 'wolf', channel === 'wolf', 'tab-wolf', store.ui.unread.wolf)) : null,
    h('div', { class: 'chat__list', testid: `chat-list-${channel}` },
      olderButton(channel, messages),
      messages.length ? messages.map((m) => bubble(server, m)) : h('p', { class: 'hint center' }, t('chat.empty'))),
    canFake || canMask ? h('div', { class: 'row' },
      asButton(t('chat.asSelf'), 'self', !fake && !masked),
      canMask ? asButton(t('chat.asWolf'), 'wolf', masked) : null,
      canFake ? asButton(t('chat.asFake', { name: nameOf(server, target) }), 'fake', fake) : null) : null,
    channel === 'public' ? schedulePanel(server) : null,
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
      h('div', { style: 'width:64px' }, actionButton({
        id: `chat-send-${channel}-${(server.chat ?? []).length}`,
        small: true,
        label: sendLabel(fake, masked, nameOf(server, target)),
        disabled: draft.trim() ? null : ' ',
        run: () => sendDraft('text'),
      })),
      // 電子音：同一段文字改成點一下會念出來的訊息（SPEC v4.24）
      h('div', { style: 'width:44px' }, actionButton({
        id: `chat-tts-send-${channel}-${(server.chat ?? []).length}`,
        small: true,
        label: t('chat.ttsSend'),
        disabled: draft.trim() ? null : ' ',
        run: () => sendDraft('tts'),
      })),
      channel === 'public'
        ? h('label', { class: 'btn btn--secondary btn--small chat__photo', testid: 'chat-photo-btn' }, t('chat.photo'),
          h('input', {
            type: 'file',
            accept: 'image/*',
            testid: 'chat-photo-input',
            onchange: (e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (file) sendPhoto(file, identity());
            },
          }))
        : null));

  function identity() {
    const fields = { channel };
    if (fake) fields.as = 'disguise';
    if (masked) fields.as = 'wolf';
    return fields;
  }

  async function sendDraft(kind) {
    const result = await send('chat.send', { ...identity(), kind, content: draft });
    if (result.ok) {
      store.ui.drafts[draftKey] = '';
      changed();
    }
    return result;
  }
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
  if (!server.is_admin || server.host || (!server.paused && !DAY_STEPS.has(server.step))) return null;
  return h('div', { class: 'pause-row' }, pauseToggle(server));
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

export function actRow(kind, label, ...content) {
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
