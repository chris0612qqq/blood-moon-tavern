// S11 天亮、S12 獵人、S13 發言、S14 投票、S15 揭曉、S16 暫停、S17 死亡、S22 遺言、S27 押注。
import { h } from '../dom.js';
import { send } from '../net.js';
import { changed, store } from '../store.js';
import { causePlain, pauseReason, roleName, t } from '../strings.js';
import { actionButton, avatar, button, countdown, nameOf, pickGrid, selection } from '../ui/common.js';

export function s11(server) {
  const row = (server.history ?? []).find((h_) => h_.round_no === server.round_no);
  const deaths = row?.deaths ?? [];
  return [
    h('h1', { class: 'center', testid: 'screen-s11' }, t('s11.title')),
    deaths.length
      ? [
        h('p', { class: 'center' }, t('s11.deaths')),
        deaths.map((id) => deadRow(server, id)),
      ]
      : (row?.saved ? null : h('p', { class: 'big center', testid: 'peaceful' }, t('s11.peaceful'))),
    row?.saved ? h('p', { class: 'center', testid: 'dawn-saved' }, t('s11.saved', { name: nameOf(server, row.saved) })) : null,
    betEntry(server),
  ];
}

function deadRow(server, id) {
  const player = server.players.find((p) => p.id === id);
  return h('div', { class: 'list-row', key: id },
    avatar(server, id),
    h('span', { class: 'grow' }, player?.name ?? ''),
    player?.death_cause ? h('span', { class: 'hint' }, causePlain(player.death_cause)) : null,
    player?.public_role ?? player?.role
      ? h('span', { class: 'badge' }, roleName(player?.public_role ?? player?.role))
      : null);
}

export function s12(server) {
  const me = server.me;
  const hunter = server.public_actors?.[0];
  if (!me?.is_actor) {
    return [
      h('h1', { class: 'center', testid: 'screen-s12' }, t('s12.others', { name: nameOf(server, hunter) })),
      countdown(server, t('s12.timeout')),
      betEntry(server),
    ];
  }
  if (me.done) return h('p', { class: 'center' }, t('done'));
  const sel = selection('hunter');
  return [
    h('h1', { testid: 'screen-s12-mine' }, t('s12.mine')),
    countdown(server, t('s12.timeout')),
    pickGrid({ ids: me.eligible_targets ?? [], server, selected: sel.value, onPick: sel.set }),
    sel.value
      ? actionButton({
        id: 'btn-hunter-shoot',
        label: t('s12.shoot', { name: nameOf(server, sel.value) }),
        kind: 'danger',
        confirm: t('s12.shootConfirm', { name: nameOf(server, sel.value) }),
        run: () => send('hunter.shoot', { target: sel.value }),
      })
      : null,
    actionButton({
      id: 'btn-hunter-holster',
      label: t('s12.holster'),
      kind: 'secondary',
      run: () => send('hunter.shoot', { target: null }),
    }),
  ];
}

function speakOrder(server) {
  const queue = server.speak_queue ?? [];
  return h('p', { class: 'hint', testid: 'speak-order' }, queue.length
    ? `${t('s13.next')}：${queue.map((id) => nameOf(server, id)).join(' → ')}`
    : '');
}

export function s13(server) {
  const me = server.me;
  const speaker = server.speaker;
  const mine = me?.is_actor && speaker === me.id;
  return [
    h('h1', { class: 'center', testid: mine ? 'screen-s13-mine' : 'screen-s13' },
      mine ? t('s13.mine') : t('s13.others', { name: nameOf(server, speaker) })),
    h('div', { class: 'center' }, speaker ? avatar(server, speaker) : null),
    countdown(server),
    speakOrder(server),
    mine && !me.done
      ? actionButton({ id: 'btn-speak-end', label: t('s13.end'), run: () => send('speak.end') })
      : null,
    betEntry(server),
  ];
}

export function s14(server) {
  const me = server.me;
  const { done = 0, total = 0 } = server.progress ?? {};
  const progress = h('p', { class: 'center', testid: 'vote-progress' }, t('s14.progress', { done, total }));
  if (!me?.is_actor) {
    return [
      h('h1', { class: 'center', testid: 'screen-s14-watch' }, t('s14.watch')),
      countdown(server),
      progress,
      betEntry(server),
    ];
  }
  const vote = me.my_vote;
  const changing = store.ui.picks[`change@${server.step_seq}`];
  if (vote && !changing) return votedView(server, vote, progress);
  const sel = selection('vote');
  const abstain = sel.value === 'abstain';
  return [
    h('h1', { testid: 'screen-s14' }, t('s14.title')),
    countdown(server, t('s14.timeout')),
    pickGrid({
      ids: me.eligible_targets ?? [],
      server,
      selected: sel.value,
      onPick: sel.set,
      extra: [{ value: 'abstain', label: t('s14.abstain') }],
    }),
    progress,
    sel.value
      ? actionButton({
        id: 'btn-vote',
        label: abstain ? t('s14.voteAbstain') : t('s14.vote', { name: nameOf(server, sel.value) }),
        run: async () => {
          const result = await send('vote.cast', { target: abstain ? null : sel.value });
          if (result.ok) delete store.ui.picks[`change@${server.step_seq}`];
          return result;
        },
      })
      : null,
  ];
}

function votedView(server, vote, progress) {
  return [
    h('h1', { class: 'center', testid: 'vote-done' }, vote.target
      ? t('s14.mine', { name: nameOf(server, vote.target) })
      : t('s14.mineAbstain')),
    countdown(server),
    progress,
    vote.can_change
      ? button(t('s14.change'), () => {
        store.ui.picks[`change@${server.step_seq}`] = true;
        changed();
      }, { testid: 'btn-vote-change' })
      : h('p', { class: 'center hint' }, t('s14.changed')),
  ];
}

export function s15(server) {
  const reveal = store.lastReveal ?? {};
  const ballots = Object.entries(reveal.ballots ?? {});
  return [
    h('h1', { class: 'center', testid: 'screen-s15' }, t('s15.title')),
    h('p', { class: 'big center', testid: 'reveal-result' }, reveal.exiled
      ? t('s15.exiled', { name: nameOf(server, reveal.exiled) })
      : t('s15.tie')),
    reveal.exiled ? deadRow(server, reveal.exiled) : null,
    ballots.map(([from, to]) => h('div', { class: 'list-row', key: from },
      t('s15.ballot', { from: nameOf(server, from), to: to ? nameOf(server, to) : t('s14.abstain') }))),
    betEntry(server),
  ];
}

/** 暫停卷軸（UI_RULES F7）：蓋住遊戲分頁，聊天照常。 */
export function s16(server) {
  const paused = server.paused;
  return h('div', { class: 'pause-cover' },
    h('h1', { testid: 'screen-s16' }, t('s16.title')),
    h('p', {}, pauseReason(paused.reason)),
    paused.resume_at
      ? h('div', { class: 'count', 'data-deadline': paused.resume_at }, '')
      : null,
    server.is_admin && !paused.resume_at
      ? actionButton({ id: 'btn-resume', label: t('s16.resume'), run: () => send('admin.resume') })
      : null);
}

export function s17(server) {
  return [
    h('h1', { class: 'center', testid: 'screen-s17' }, t('s17.title')),
    h('p', { class: 'center hint' }, t('s7.title')),
    betEntry(server),
  ];
}

export function s22(server) {
  const me = server.me;
  const speaker = server.speaker;
  const mine = me?.is_actor && speaker === me.id;
  const draftKey = `lastwords@${server.step_seq}`;
  const draft = store.ui.drafts[draftKey] ?? '';
  return [
    h('h1', { class: 'center', testid: mine ? 'screen-s22-mine' : 'screen-s22' },
      mine ? t('s22.mine') : t('s22.others', { name: nameOf(server, speaker) })),
    speaker ? deadRow(server, speaker) : null,
    countdown(server),
    mine && !me.done
      ? [
        store.ui.drafts[`${draftKey}:sent`]
          ? null
          : [
            h('textarea', {
              testid: 'input-last-words',
              placeholder: t('s22.text'),
              value: draft,
              maxlength: 500,
              oninput: (e) => { store.ui.drafts[draftKey] = e.target.value; changed(); },
            }),
            actionButton({
              id: 'btn-last-words-send',
              label: t('s22.send'),
              kind: 'secondary',
              disabled: draft.trim() ? null : ' ',
              run: async () => {
                const result = await send('chat.send', { channel: 'public', kind: 'text', content: draft });
                if (result.ok) store.ui.drafts[`${draftKey}:sent`] = true;
                return result;
              },
            }),
          ],
        actionButton({ id: 'btn-last-words-end', label: t('s22.end'), run: () => send('speak.end') }),
      ]
      : null,
  ];
}

/** 好人陣營的死者才有押注入口（SPEC A13、S17）。 */
function betEntry(server) {
  if (!server.me?.can_bet) return null;
  return button(t('s17.bet'), () => { store.ui.overlay = 'S27'; changed(); }, { testid: 'btn-bet' });
}

export function s27() {
  const server = store.server;
  const close = () => { store.ui.overlay = null; changed(); };
  if (!server?.me?.can_bet) {
    return [h('h1', {}, t('s27.title')), button(t('common.close'), close)];
  }
  const me = server.me;
  const limit = wolfTotal(server);
  const others = server.players.filter((p) => p.id !== me.id).map((p) => p.id);
  const form = store.ui.form;
  const wolves = form.bet_wolves ?? me.my_bet?.wolves ?? [];
  const faceless = form.bet_faceless !== undefined ? form.bet_faceless : (me.my_bet?.faceless_guess ?? null);
  const toggle = (id) => {
    const list = form.bet_wolves ?? [...wolves];
    const index = list.indexOf(id);
    if (index >= 0) list.splice(index, 1);
    else if (list.length < limit) list.push(id);
    else store.ui.toast = { key: 's27.limit', params: { n: limit } };
    form.bet_wolves = list;
    changed();
  };
  const grid = (prefix, active, onPick) => h('div', { class: 'grid' }, others.map((id) => h('button', {
    class: `cell ${active(id) ? 'cell--on' : ''}`,
    key: `${prefix}-${id}`,
    testid: `${prefix}-${id}`,
    onclick: () => onPick(id),
  }, nameOf(server, id))));
  return [
    h('h1', { testid: 'screen-s27' }, t('s27.title')),
    h('p', { class: 'hint' }, t('s27.limit', { n: limit })),
    grid('bet-wolf', (id) => wolves.includes(id), toggle),
    h('p', {}, t('s27.faceless')),
    grid('bet-faceless', (id) => faceless === id, (id) => {
      form.bet_faceless = faceless === id ? null : id;
      changed();
    }),
    actionButton({
      id: 'btn-bet-submit',
      label: t('s27.submit'),
      run: () => send('bet.set', { wolves, faceless }),
    }),
    button(t('common.close'), close, { testid: 'btn-bet-close' }),
  ];
}

// 狼人總數公開（SPEC S26 規則速查有本局配置），由配角色表查，不靠秘密資料
function wolfTotal(server) {
  return store.wolfCount?.(server.players.length) ?? 1;
}

