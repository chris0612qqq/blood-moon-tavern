// S11 天亮、S12 獵人、S13 發言、S14 投票、S15 揭曉、S16 暫停、S17 死亡、S22 遺言。
import { h } from '../dom.js';
import { send } from '../net.js';
import { changed, store } from '../store.js';
import { causePlain, pauseReason, roleName, t } from '../strings.js';
import { coin, dawnRise, hunterBow, roleEmblem, snuffedCandle } from '../ui/art.js';
import { actionButton, avatar, button, countdownRing, nameOf, pickGrid, selection } from '../ui/common.js';

export function s11(server) {
  const row = (server.history ?? []).find((h_) => h_.round_no === server.round_no);
  const deaths = row?.deaths ?? [];
  // 旁白還在念「天亮請睜眼」，結果還沒公布，不能先顯示平安夜
  if (!server.announced) {
    return [dawnRise(), h('h1', { class: 'center', testid: 'screen-s11' }, t('s11.title'))];
  }
  const peaceful = !deaths.length && !row?.saved && !server.dawn_count;
  return [
    dawnRise(peaceful),
    h('h1', { class: 'center', testid: 'screen-s11' }, t('s11.title')),
    deaths.length
      ? [
        h('p', { class: 'center' }, t('s11.deaths')),
        // 死者一張張翻開（ART 11.2 天亮公布）
        deaths.map((id, i) => deadRow(server, id, i)),
      ]
      // 公布和死者是兩則訊息，中間可能畫一次：有人要死就不能先說平安夜
      : (row?.saved || server.dawn_count ? null : h('p', { class: 'big center', testid: 'peaceful' }, t('s11.peaceful'))),
    row?.saved ? h('p', { class: 'center', testid: 'dawn-saved' }, t('s11.saved', { name: nameOf(server, row.saved) })) : null,
  ];
}

function deadRow(server, id, order = null) {
  const player = server.players.find((p) => p.id === id);
  const reveal = order === null ? {} : { class: 'list-row dead-reveal', style: `--i:${order}` };
  return h('div', { class: 'list-row', key: id, ...reveal },
    avatar(server, id),
    h('span', { class: 'grow' }, player?.name ?? ''),
    player?.death_cause ? h('span', { class: 'hint' }, causePlain(player.death_cause)) : null,
    player?.public_role ?? player?.role
      ? h('span', { class: 'badge' }, roleEmblem(player?.public_role ?? player?.role), roleName(player?.public_role ?? player?.role))
      : null);
}

export function s12(server) {
  const me = server.me;
  const hunter = server.public_actors?.[0];
  if (!me?.is_actor) {
    return [
      hunterBow(),
      h('h1', { class: 'center', testid: 'screen-s12' }, t('s12.others', { name: nameOf(server, hunter) })),
      countdownRing(server, t('s12.timeout')),
    ];
  }
  if (me.done) return h('p', { class: 'center' }, t('done'));
  const sel = selection('hunter');
  return [
    hunterBow(),
    h('h1', { testid: 'screen-s12-mine' }, t('s12.mine')),
    countdownRing(server, t('s12.timeout')),
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
  return h('p', { class: 'hint keep-words', testid: 'speak-order' }, queue.length
    ? `${t('s13.next')}：${queue.map((id) => nameOf(server, id)).join(' → ')}`
    : '');
}

/** 第一輪的結果：被提名者和票數（SPEC A5.4）。誰投誰不公開。 */
function nomineeLine(server) {
  const counts = server.suspect_counts ?? {};
  const names = Object.entries(counts).map(([id, n]) => t('s14.nominee', { name: nameOf(server, id), n }));
  return names.length ? h('p', { class: 'center keep-words', testid: 'nominees' }, t('s14.nominees', { list: names.join('、') })) : null;
}

/** 第一輪投票當下誰選誰，和狼人選刀一樣看得到（使用者要求，SPEC A5.4）。第二輪不公開。 */
export function suspectBoard(server) {
  if (server.step !== 'SUSPECT_VOTE') return null;
  const groups = {};
  for (const [voter, target] of Object.entries(server.suspect_picks ?? {})) {
    (groups[target ?? 'abstain'] ??= []).push(nameOf(server, voter));
  }
  const rows = Object.entries(groups).sort(([, a], [, b]) => b.length - a.length);
  return h('div', { class: 'panel', testid: 'suspect-picks' }, rows.length
    ? rows.map(([target, voters]) => h('div', { key: target }, target === 'abstain'
      ? t('s14.boardAbstain', { who: voters.join('、') })
      : t('s14.boardRow', { target: nameOf(server, target), n: voters.length, who: voters.join('、') })))
    : t('s14.boardEmpty'));
}

function suspectMarks(server) {
  if (server.step !== 'SUSPECT_VOTE') return null;
  const marks = {};
  for (const [voter, target] of Object.entries(server.suspect_picks ?? {})) {
    if (voter === server.me?.id) continue;
    const key = target ?? 'abstain';
    marks[key] = [marks[key], nameOf(server, voter)].filter(Boolean).join(' ');
  }
  return marks;
}

export function voteProgress(server) {
  const { done = 0, total = 0 } = server.progress ?? {};
  return h('p', { class: 'center', testid: 'vote-progress' }, t('s14.progress', { done, total }));
}

export function s13(server) {
  const me = server.me;
  const speaker = server.speaker;
  const mine = me?.is_actor && speaker === me.id;
  const defending = server.step === 'DEFENSE';
  return [
    h('h1', { class: 'center', testid: mine ? 'screen-s13-mine' : 'screen-s13' },
      mine
        ? t(defending ? 's13.mineDefense' : 's13.mine')
        : t(defending ? 's13.othersDefense' : 's13.others', { name: nameOf(server, speaker) })),
    defending ? nomineeLine(server) : null,
    h('div', { class: 'center' }, speaker ? avatar(server, speaker) : null),
    countdownRing(server),
    speakOrder(server),
    mine && !me.done
      ? actionButton({ id: 'btn-speak-end', label: t('s13.end'), run: () => send('speak.end') })
      : null,
  ];
}

export function s14(server) {
  const me = server.me;
  const progress = voteProgress(server);
  if (!me?.is_actor) {
    return [
      h('h1', { class: 'center', testid: 'screen-s14-watch' }, t('s14.watch')),
      server.step === 'VOTE' ? nomineeLine(server) : null,
      countdownRing(server),
      progress,
      suspectBoard(server),
    ];
  }
  const vote = me.my_vote;
  const changing = store.ui.picks[`change@${server.step_seq}`];
  if (vote && !changing) return votedView(server, vote, progress);
  const sel = selection('vote');
  const abstain = sel.value === 'abstain';
  return [
    h('h1', { testid: 'screen-s14' }, t(server.step === 'SUSPECT_VOTE' ? 's14.titleSuspect' : 's14.title')),
    server.step === 'VOTE' ? nomineeLine(server) : null,
    countdownRing(server, t('s14.timeout')),
    pickGrid({
      ids: me.eligible_targets ?? [],
      server,
      selected: sel.value,
      onPick: sel.set,
      marks: suspectMarks(server),
      extra: [{ value: 'abstain', label: t('s14.abstain') }],
    }),
    progress,
    suspectBoard(server),
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
    countdownRing(server),
    progress,
    suspectBoard(server),
    vote.can_change
      ? button(t('s14.change'), () => {
        store.ui.picks[`change@${server.step_seq}`] = true;
        changed();
      }, { testid: 'btn-vote-change' })
      : h('p', { class: 'center hint' }, t('s14.changed')),
  ];
}

/** 每人幾票，高票在前（SPEC A5.4）。棄票不算。第一輪就決定時只有票數，沒有誰投誰。 */
function tallyLine(server, ballots) {
  const counts = { ...server.suspect_counts };
  for (const [, to] of ballots) if (to) counts[to] = (counts[to] ?? 0) + 1;
  const names = Object.entries(counts)
    .sort(([, a], [, b]) => b - a)
    .map(([id, n]) => t('s14.nominee', { name: nameOf(server, id), n }));
  return names.length ? h('p', { class: 'center keep-words', testid: 'reveal-tally' }, names.join('、')) : null;
}

/** 被放逐者拿到的票，一票一枚銅幣依序落下（ART 11.2）。 */
function coinsFor(server, ballots, exiled) {
  const n = (server.suspect_counts?.[exiled] ?? 0) + ballots.filter(([, to]) => to === exiled).length;
  return n ? h('div', { class: 'coins', testid: 'reveal-coins' }, Array.from({ length: n }, (_, i) => coin(i))) : null;
}

export function s15(server) {
  const reveal = store.lastReveal ?? {};
  const ballots = Object.entries(reveal.ballots ?? {});
  return [
    h('h1', { class: 'center', testid: 'screen-s15' }, t('s15.title')),
    h('p', { class: 'big center', testid: 'reveal-result' }, reveal.exiled
      ? t('s15.exiled', { name: nameOf(server, reveal.exiled) })
      : t(server.line_id === 'no_nominee' ? 's15.noNominee' : 's15.tie')),
    reveal.exiled ? deadRow(server, reveal.exiled) : null,
    reveal.exiled ? coinsFor(server, ballots, reveal.exiled) : null,
    tallyLine(server, ballots),
    ballots.map(([from, to]) => h('div', { class: 'list-row', key: from },
      t('s15.ballot', { from: nameOf(server, from), to: to ? nameOf(server, to) : t('s14.abstain') }))),
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
      : null);
}

export function s17(server) {
  return [
    snuffedCandle(),
    h('h1', { class: 'center', testid: 'screen-s17' }, t('s17.title')),
    h('p', { class: 'center hint' }, t('s7.title')),
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
    countdownRing(server),
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

