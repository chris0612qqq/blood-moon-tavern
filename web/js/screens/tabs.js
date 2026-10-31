// 非遊戲分頁與共用畫面：聊天、狼人頻道、我的角色、玩家、S18 結算、S21 設定、S26 規則速查。
import { h } from '../dom.js';
import { api, send } from '../net.js';
import { speak } from '../narrator.js';
import { loadTokens, clearPlayerToken } from '../session.js';
import { changed, store } from '../store.js';
import { roleName, t } from '../strings.js';
import { actionButton, avatar, button, nameOf } from '../ui/common.js';
import { roleCard } from './night.js';

const NIGHT_STEPS = new Set(['NIGHT_START', 'WOLF', 'WOLF_END', 'SEER', 'SEER_END', 'WITCH', 'WITCH_END']);

function displayName(server, msg) {
  if (msg.is_host_msg) return t('chat.host');
  return nameOf(server, msg.display_player_id);
}

function bubble(server, msg) {
  const mine = msg.mine && !msg.disguised_by_me;
  const classes = ['bubble', mine ? 'bubble--mine' : '', msg.is_host_msg ? 'bubble--host' : ''];
  return h('div', { class: classes.join(' '), key: `m${msg.id}`, testid: `chat-${msg.id}` },
    h('div', { class: 'bubble__who' }, displayName(server, msg),
      msg.disguised_by_me ? ` ${t('chat.fakeMark', { name: displayName(server, msg) })}` : '',
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

export function chatTab(server, channel) {
  const messages = (server.chat ?? []).filter((m) => m.channel === channel);
  const block = postBlock(server, channel);
  const draftKey = `chat-${channel}`;
  const draft = store.ui.drafts[draftKey] ?? '';
  const canFake = channel === 'public' && server.me?.can_disguise;
  const fake = canFake && store.ui.chatAs === 'fake';
  const target = server.me?.disguise_info?.target;
  return h('div', { class: 'chat' },
    h('div', { class: 'chat__list', testid: `chat-list-${channel}` },
      messages.length ? messages.map((m) => bubble(server, m)) : h('p', { class: 'hint center' }, t('chat.empty'))),
    canFake ? h('div', { class: 'row' },
      button(t('chat.asSelf'), () => { store.ui.chatAs = 'self'; changed(); }, { small: true, kind: fake ? 'secondary' : 'suggest', testid: 'chat-as-self' }),
      button(t('chat.asFake', { name: nameOf(server, target) }), () => { store.ui.chatAs = 'fake'; changed(); }, { small: true, kind: fake ? 'suggest' : 'secondary', testid: 'chat-as-fake' })) : null,
    block ? h('p', { class: 'hint center', testid: 'chat-blocked' }, block) : h('div', { class: 'chat__input' },
      h('textarea', {
        testid: 'chat-input',
        placeholder: t('chat.placeholder'),
        maxlength: 500,
        value: draft,
        oninput: (e) => { store.ui.drafts[draftKey] = e.target.value; changed(); },
      }),
      h('div', { style: 'width:110px' }, actionButton({
        id: `chat-send-${channel}-${(server.chat ?? []).length}`,
        small: true,
        label: fake ? t('chat.sendAs', { name: nameOf(server, target) }) : t('chat.send'),
        disabled: draft.trim() ? null : ' ',
        run: async () => {
          const fields = { channel, kind: 'text', content: draft };
          if (fake) fields.as = 'disguise';
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
  const checks = me.seer_info?.checks ?? [];
  return [
    h('h1', { testid: 'tab-role' }, t('tab.role')),
    roleCard(server, me.wolf_pack ? h('p', {}, t('s6.pack', {
      names: me.wolf_pack.pack.filter((id) => id !== me.id).map((id) => nameOf(server, id)).join('、'),
    })) : null),
    checks.length ? h('h2', {}, t('role.seerLog')) : null,
    checks.map((c) => h('p', { key: `check${c.round_no}` }, t('role.seerRow', {
      n: c.round_no,
      name: nameOf(server, c.target),
      result: t(c.is_wolf ? 'role.wolfResult' : 'role.goodResult'),
    }))),
  ];
}

export function playersTab(server) {
  const list = server.players ?? server.roster ?? [];
  const offline = new Set((server.roster ?? []).filter((r) => r.offline).map((r) => r.id));
  const canPause = server.is_admin && !server.host && !server.paused && server.phase === 'game' && !NIGHT_STEPS.has(server.step) && server.step !== 'END';
  return [
    h('h1', { testid: 'tab-players' }, t('players.title')),
    [...list].sort((a, b) => a.seat - b.seat).map((p) => h('div', { class: 'list-row', key: p.id },
      h('span', {}, `#${p.seat}`),
      avatar(server, p.id),
      h('span', { class: 'grow' }, p.name),
      offline.has(p.id) ? h('span', { class: 'badge' }, t('s5.offlineTag')) : null,
      p.alive === false ? h('span', { class: 'badge' }, `☠ ${roleName(p.public_role ?? p.role)}`) : null,
      server.is_admin && !server.host && p.alive !== false && server.phase === 'game' && server.step !== 'END'
        ? actionButton({
          id: `kick-${p.id}`,
          small: true,
          kind: 'danger',
          label: t('s5.kick'),
          confirm: t('s5.kickConfirm', { name: p.name }),
          run: () => send('admin.kick', { player: p.id }),
        })
        : null)),
    canPause ? actionButton({ id: 'btn-pause', label: t('s16.pause'), kind: 'secondary', run: () => send('admin.pause') }) : null,
    server.is_admin && !server.host && server.phase === 'game' && server.step !== 'END'
      ? actionButton({
        id: 'btn-admin-end',
        label: t('s20.end'),
        kind: 'danger',
        confirm: t('s20.endConfirm'),
        run: () => send('admin.end'),
      })
      : null,
    (server.history ?? []).length ? h('h2', {}, t('players.log')) : null,
    (server.history ?? []).map((row) => h('div', { class: 'panel', key: `round${row.round_no}` },
      h('b', {}, t('players.round', { n: row.round_no })),
      h('div', {}, t('players.deaths', {
        names: row.deaths.length ? row.deaths.map((id) => nameOf(server, id)).join('、') : t('players.nobody'),
      })),
      row.ballots ? Object.entries(row.ballots).map(([from, to]) => h('div', { class: 'hint', key: from },
        t('s15.ballot', { from: nameOf(server, from), to: to ? nameOf(server, to) : t('s14.abstain') }))) : null)),
  ];
}

export function s18(server) {
  const truth = server.truth ?? {};
  const name = (id) => (id ? nameOf(server, id) : t('s20.nobody'));
  const title = { village: 's18.village', wolf: 's18.wolf', none: 's18.none' }[server.winner] ?? 's18.none';
  const periods = truth.disguise?.periods ?? [];
  return [
    h('h1', { class: 'center', testid: 'screen-s18' }, t(title)),
    store.closesAt ? h('p', { class: 'center hint' }, t('s18.closing'),
      h('div', { class: 'count', 'data-deadline': store.closesAt, 'data-clock': 'mmss' }, '')) : null,
    h('h2', {}, t('s18.roles')),
    [...server.players].sort((a, b) => a.seat - b.seat).map((p) => h('div', { class: 'list-row', key: p.id },
      avatar(server, p.id),
      h('span', { class: 'grow' }, p.name),
      // 夜晚死因結算才公開（SPEC A2）
      truth.death_causes?.[p.id]
        ? h('span', { class: 'hint', testid: `end-cause-${p.id}` }, t(`s18.cause.${truth.death_causes[p.id]}`))
        : null,
      h('span', { class: 'badge', testid: `end-role-${p.id}` }, roleName(p.role)))),
    h('h2', {}, t('s18.truth')),
    h('h2', {}, t('s18.disguise')),
    periods.map((period, i) => h('p', { key: `p${i}` }, t('s18.period', { from: period.from_round, name: name(period.target_id) }))),
    (truth.disguised_messages ?? []).map((m) => h('p', { key: `f${m.id}` }, t('s18.fakeMsg', {
      id: m.id,
      real: name(m.real_author),
      shown: name(m.display),
    }))),
    h('h2', {}, t('s18.nights')),
    (truth.nights ?? []).map((n) => h('p', { key: `n${n.round_no}` }, t('s18.night', {
      n: n.round_no,
      wolf: name(n.wolf_target),
      seer: name(n.seer_target),
      saved: n.witch_saved ? '✔' : t('s20.nobody'),
      poison: name(n.witch_poison),
    }))),
    h('h2', {}, t('s18.votes')),
    (truth.votes ?? []).filter((v) => v.revealed).map((v) => h('div', { class: 'panel', key: `v${v.round_no}` },
      h('b', {}, t('players.round', { n: v.round_no })),
      Object.entries(v.ballots).map(([from, to]) => h('div', { class: 'hint', key: from },
        t('s15.ballot', { from: name(from), to: to ? name(to) : t('s14.abstain') }))))),
    (truth.bets ?? []).length ? h('h2', {}, t('s18.bets')) : null,
    // SPEC A13：名次、分數、每人押了誰
    (truth.bets ?? []).map((b) => h('div', { class: 'panel', key: `b${b.player_id}`, testid: `end-bet-${b.player_id}` },
      h('div', {}, t('s18.betRow', { rank: b.rank, name: name(b.player_id), score: b.score })),
      h('div', { class: 'hint' }, t('s18.betPicks', {
        wolves: b.wolves.length ? b.wolves.map(name).join('、') : t('players.nobody'),
        faceless: name(b.faceless),
      })))),
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
    button(t('s21.test'), () => speak(t('s5.soundTest')), { testid: 'btn-test-voice' }),
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
    h('p', {}, t('s26.witch')),
    h('p', {}, t('s26.hunter')),
    h('p', {}, t('s26.terms')),
    button(t('common.close'), close, { testid: 'btn-rules-close' }),
  ];
}
