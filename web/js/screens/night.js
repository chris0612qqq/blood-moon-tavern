// S6 發牌、S7 夜晚旁觀、S8 狼人、S9 預言家、S10 女巫、S19 千面狼面板。
import { h, s } from '../dom.js';
import { send } from '../net.js';
import { store, changed } from '../store.js';
import { errorText, roleAbility, roleName, roleStory, stepName, t } from '../strings.js';
import { clawSlash, d20Crest, roleEmblem, seerOrb, witchBrew } from '../ui/art.js';
import {
  actionButton, avatar, countdownRing, markOf, nameOf, pickGrid, selection, toast,
} from '../ui/common.js';

/** 角色卡：長按才顯示，放開蓋回；秘密只在顯示時才進 DOM（CODING_RULES V18、V19）。 */
export function roleCard(server) {
  const me = server.me;
  const release = () => { store.ui.cardHeld = false; changed(); };
  const held = store.ui.cardHeld;
  return h('div', {
    class: 'card',
    testid: 'role-card',
    onpointerdown: (e) => {
      e.preventDefault();
      store.ui.cardHeld = true;
      store.ui.cardSeen = true;
      changed();
    },
    onpointerup: release,
    onpointercancel: release,
    onpointerleave: release,
    oncontextmenu: (e) => e.preventDefault(),
  }, held
    // 只翻裡面的內容：卡片外框若跟著轉到側面會變成 0 寬，手指就像「離開」了卡片而立刻蓋回
    ? h('div', { class: 'card__face' },
      roleEmblem(me.role, 72),
      h('div', { class: 'big', testid: 'role-name' }, roleName(me.role)),
      h('p', { class: 'hint', testid: 'role-faction' }, t(me.wolf_pack ? 's6.factionWolf' : 's6.factionGood')),
      h('p', { testid: 'role-ability' }, roleAbility(me.role)),
      h('p', { class: 'hint', testid: 'role-story' }, roleStory(me.role)),
      roleSecrets(server))
    // 骰子擲出來只演第一次；看過角色後放開就不再滾（ART 11.2 發牌）
    : [d20Crest(store.ui.cardSeen ? '' : 'crest--roll'), t('s6.hold')]);
}

/** 只有本人知道的資訊，一律放在卡片裡，放開就離開 DOM（CODING_RULES V19）。 */
function roleSecrets(server) {
  const me = server.me;
  const pack = me.wolf_pack?.pack;
  const names = pack?.filter((id) => id !== me.id).map((id) => nameOf(server, id)).join('、');
  const potion = (used) => t(used ? 's10.used' : 's10.left');
  return [
    pack ? h('p', { testid: 'role-pack' }, t('s6.pack', { names })) : null,
    me.disguise_info?.target
      ? h('p', { testid: 'role-disguise' }, t('s19.panel', {
        name: nameOf(server, me.disguise_info.target),
        n: me.disguise_info.rounds_left,
      }))
      : null,
    me.witch_info
      ? h('p', { testid: 'role-potions' }, t('s10.potions', {
        antidote: potion(me.witch_info.antidote_used),
        poison: potion(me.witch_info.poison_used),
      }))
      : null,
    (me.seer_info?.checks ?? []).map((c) => h('p', { key: `check${c.round_no}`, testid: `role-check-${c.round_no}` },
      t('role.seerRow', {
        n: c.round_no,
        name: nameOf(server, c.target),
        result: t(c.is_wolf ? 'role.wolfResult' : 'role.goodResult'),
      }))),
  ];
}

export function s6(server) {
  const me = server.me;
  const { done = 0, total = 0 } = server.progress ?? {};
  return [
    h('h1', { testid: 'screen-s6' }, t('s6.title')),
    countdownRing(server, t('s6.timeout')),
    roleCard(server),
    h('p', { class: 'center', testid: 'deal-progress' }, t('s6.progress', { done, total })),
    me.done
      ? h('p', { class: 'center' }, t('pending'))
      : actionButton({ id: 'btn-seen', label: t('s6.seen'), run: () => send('deal.ack') }),
  ];
}

export function s7(server) {
  const plan = server.night_plan ?? [];
  const current = plan.includes(server.step) ? stepName(server.step) : null;
  return h('div', { class: 'center' },
    h('h1', { testid: 'screen-s7' }, t('s7.title')),
    current ? h('p', { testid: 'night-current' }, t('s7.current', { step: current })) : null,
    h('p', { class: 'hint' }, plan.map(stepName).join(' → ')));
}

function wolfStatus(server, info) {
  const me = server.me;
  const picks = info.picks ?? {};
  if (info.decided) {
    return info.decided_target
      ? t('s8.confirmed', { target: nameOf(server, info.decided_target) })
      : t('s8.confirmedEmpty');
  }
  if (info.confirming_until) {
    const target = picks[me.id];
    return t('s8.confirming', { target: target ? nameOf(server, target) : t('s8.empty') });
  }
  const parts = Object.entries(picks).map(([wolf, target]) => t('s8.picked', {
    who: nameOf(server, wolf),
    target: target ? nameOf(server, target) : t('s8.empty'),
  }));
  return parts.length ? t('s8.disagree', { detail: parts.join('、') }) : t('s8.title');
}

/** 血月：月面漸層＋坑洞＋右下暗面，外圈光暈慢慢呼吸，一條夜霧從月前飄過。動畫在 s8.css。 */
function bloodMoon() {
  return s('svg', { class: 's8__moon', viewBox: '0 0 120 120', 'aria-hidden': 'true' },
    s('defs', {},
      s('radialGradient', { id: 's8-moon-face', cx: '38%', cy: '34%', r: '70%' },
        s('stop', { offset: '0%', 'stop-color': '#e2614c' }),
        s('stop', { offset: '55%', 'stop-color': '#8e1b1b' }),
        s('stop', { offset: '100%', 'stop-color': '#3a0909' })),
      s('radialGradient', { id: 's8-moon-halo' },
        s('stop', { offset: '45%', 'stop-color': '#c8322a', 'stop-opacity': '.55' }),
        s('stop', { offset: '100%', 'stop-color': '#c8322a', 'stop-opacity': '0' })),
      // 右下暗面：從亮面柔和地暗下去，讓月亮有立體感
      s('radialGradient', { id: 's8-moon-shade', cx: '32%', cy: '30%', r: '85%' },
        s('stop', { offset: '45%', 'stop-color': '#140303', 'stop-opacity': '0' }),
        s('stop', { offset: '100%', 'stop-color': '#140303', 'stop-opacity': '.75' })),
      // 霧帶兩頭淡掉，不會看起來像一片灰盤子
      s('linearGradient', { id: 's8-mist' },
        s('stop', { offset: '0%', 'stop-color': '#8b93a0', 'stop-opacity': '0' }),
        s('stop', { offset: '50%', 'stop-color': '#8b93a0', 'stop-opacity': '.3' }),
        s('stop', { offset: '100%', 'stop-color': '#8b93a0', 'stop-opacity': '0' }))),
    s('circle', { class: 's8__halo', cx: 60, cy: 60, r: 58, fill: 'url(#s8-moon-halo)' }),
    s('circle', { cx: 60, cy: 60, r: 30, fill: 'url(#s8-moon-face)' }),
    s('g', { fill: '#4a0d0d' },
      s('circle', { cx: 50, cy: 50, r: 5, opacity: '.5' }),
      s('circle', { cx: 68, cy: 66, r: 7, opacity: '.4' }),
      s('circle', { cx: 63, cy: 44, r: 3, opacity: '.45' }),
      s('circle', { cx: 46, cy: 70, r: 3.5, opacity: '.35' })),
    s('circle', { cx: 60, cy: 60, r: 30, fill: 'url(#s8-moon-shade)' }),
    s('g', { class: 's8__mist', fill: 'url(#s8-mist)' },
      s('ellipse', { cx: 44, cy: 76, rx: 50, ry: 4 }),
      s('ellipse', { cx: 82, cy: 85, rx: 36, ry: 3, opacity: '.7' })));
}

export function s8(server) {
  const me = server.me;
  const info = me.wolf_pack;
  const picks = info.picks ?? {};
  const allies = info.pack.filter((id) => id !== me.id).map((id) => nameOf(server, id)).join('、');
  const marks = {};
  for (const [wolf, target] of Object.entries(picks)) {
    if (wolf === me.id) continue;
    const key = target ?? 'none';
    marks[key] = [marks[key], markOf(server, wolf)].filter(Boolean).join(' ');
  }
  const mine = me.id in picks ? (picks[me.id] ?? 'none') : undefined;
  // 狼人例外：不用按確認，全員一致滿 3 秒自動確認（SPEC C8.1）
  const pick = (value) => {
    if (info.decided) return;
    const fields = value === mine ? { clear: true } : { target: value === 'none' ? null : value };
    // 狼人沒有送出鈕，失敗要另外告訴他，否則會以為沒按到（UI_RULES F6）
    send('wolf.pick', fields).then((result) => {
      if (!result.ok) toast('error.raw', { text: errorText(result.code) });
    });
  };
  // 美術垂直切片（DEV_PLAN P8）：血月、爪痕暗角、倒數環、木牌格子；畫面樣式在 css/s8.css
  const moon = bloodMoon();
  if (info.decided) {
    const victim = info.decided_target;
    return h('div', { class: 's8 s8--done center' },
      moon,
      h('h1', { class: 's8__title', testid: 'screen-s8-done' }, t('s7.title')),
      h('div', { class: `victim ${victim ? '' : 'victim--none'}`, testid: 'wolf-victim' },
        victim ? avatar(server, victim) : null,
        h('div', { class: 'victim__name' }, victim ? nameOf(server, victim) : t('s8.empty')),
        victim ? clawSlash('wolf-pick') : null),
      h('div', { class: 'panel s8__status', testid: 'wolf-status' }, wolfStatus(server, info)));
  }
  const agreed = info.confirming_until ? (picks[me.id] ?? 'none') : undefined;
  return h('div', { class: 's8' },
    moon,
    h('h1', { class: 's8__title', testid: 'screen-s8' }, t('s8.title')),
    countdownRing(server, t('s8.timeout')),
    h('p', { class: 'center s8__rule', testid: 'wolf-one-kill' }, t('s8.oneKill')),
    allies ? h('p', { class: 'center s8__allies' }, t('s8.allies', { names: allies })) : null,
    pickGrid({
      ids: me.eligible_targets ?? [],
      server,
      selected: mine,
      marks,
      onPick: pick,
      extra: [{ value: 'none', label: t('s8.empty') }],
      look: 'grid--wolf',
      stateOf: (value) => (value === agreed ? 'cell--confirming' : ''),
    }),
    h('div', { class: 'panel s8__status', testid: 'wolf-status' }, wolfStatus(server, info)));
}

export function s9(server) {
  const me = server.me;
  const checks = me.seer_info.checks;
  const today = checks.find((c) => c.round_no === server.round_no);
  if (today) {
    const key = today.is_wolf ? 's9.wolf' : 's9.good';
    return [
      seerOrb(today.is_wolf ? 'wolf' : 'good'),
      h('h1', { class: 'center', testid: 'seer-result' }, t(key, { name: nameOf(server, today.target) })),
      me.done
        ? h('p', { class: 'center' }, t('pending'))
        : actionButton({ id: 'btn-seer-ok', label: t('s9.ok'), run: () => send('seer.ok') }),
    ];
  }
  const sel = selection('seer');
  return [
    seerOrb(),
    h('h1', { testid: 'screen-s9' }, t('s9.title')),
    countdownRing(server, t('s9.timeout')),
    pickGrid({ ids: me.eligible_targets ?? [], server, selected: sel.value, onPick: sel.set }),
    sel.value
      ? actionButton({
        id: 'btn-seer-check',
        label: t('s9.check', { name: nameOf(server, sel.value) }),
        run: () => send('seer.check', { target: sel.value }),
      })
      : null,
  ];
}

export function s10(server) {
  const me = server.me;
  const info = me.witch_info;
  const potionState = (used) => t(used ? 's10.used' : 's10.left');
  // 這一步剛用的藥：倒進小鍋的演出（ART 11.2）
  const pouring = info.acted || me.done ? store.ui.picks[`witchUsed@${server.step_seq}`] : null;
  const head = [
    witchBrew(info.antidote_used, info.poison_used, pouring),
    h('h1', { testid: 'screen-s10' }, stepName(server.step)),
    countdownRing(server, t('s10.timeout')),
    h('p', { class: 'center' }, t('s10.potions', {
      antidote: potionState(info.antidote_used),
      poison: potionState(info.poison_used),
    })),
  ];
  if (info.acted || me.done) return [...head, h('p', { class: 'center', testid: 'witch-acted' }, t('s10.acted'))];
  if (info.antidote_used && info.poison_used) {
    return [...head, h('p', { class: 'big center', testid: 'witch-none' }, t('s10.none'))];
  }
  const stageKey = `stage@${server.step_seq}`;
  const stage = store.ui.witchStage[stageKey] ?? (info.antidote_used ? 'poison' : 'save');
  if (stage === 'save') return [...head, witchSave(server, info, stageKey)];
  return [...head, witchPoison(server, me, info)];
}

function witchSave(server, info, stageKey) {
  const toPoison = () => { store.ui.witchStage[stageKey] = 'poison'; changed(); };
  const skip = () => (info.can_poison
    ? (toPoison(), Promise.resolve({ ok: true }))
    : send('witch.act', {}));
  if (!info.attacked) {
    return [
      h('p', { class: 'big center', testid: 'witch-safe' }, t('s10.safe')),
      actionButton({ id: 'btn-witch-next', label: t('s10.next'), run: skip }),
    ];
  }
  const name = nameOf(server, info.attacked);
  return [
    h('p', { class: 'big center', testid: 'witch-attacked' }, t('s10.attacked', { name })),
    info.can_save
      ? actionButton({
        id: 'btn-witch-save',
        label: t('s10.save', { name }),
        run: () => {
          store.ui.picks[`witchUsed@${server.step_seq}`] = 'save';
          return send('witch.act', { save: true });
        },
      })
      : h('p', { class: 'center hint' }, t('s10.noSelf')),
    actionButton({ id: 'btn-witch-nosave', label: t('s10.noSave'), kind: 'secondary', run: skip }),
  ];
}

function witchPoison(server, me, info) {
  if (!info.can_poison) {
    return actionButton({ id: 'btn-witch-done', label: t('s10.next'), run: () => send('witch.act', {}) });
  }
  const sel = selection('poison');
  return [
    h('p', { class: 'center' }, t('s10.poisonTitle')),
    pickGrid({ ids: me.eligible_targets ?? [], server, selected: sel.value, onPick: sel.set }),
    sel.value
      ? actionButton({
        id: 'btn-witch-poison',
        label: t('s10.poison', { name: nameOf(server, sel.value) }),
        kind: 'danger',
        run: () => {
          store.ui.picks[`witchUsed@${server.step_seq}`] = 'poison';
          return send('witch.act', { poison: sel.value });
        },
      })
      : null,
    actionButton({ id: 'btn-witch-nopoison', label: t('s10.noPoison'), kind: 'secondary', run: () => send('witch.act', {}) }),
  ];
}

/** S19 千面狼面板：遊戲分頁頂端小卡。狼人步驟不顯示，避免被旁邊的狼瞄到（SPEC C8.3）。 */
export function s19(server) {
  const info = server.me?.disguise_info;
  // 發牌時對象只在按住卡片時顯示；狼人步驟隱藏，避免被旁邊的狼瞄到（SPEC C8.3）
  if (!info || !server.me.alive || server.step === 'WOLF' || server.step === 'DEAL') return null;
  const text = info.target
    ? t('s19.panel', { name: nameOf(server, info.target), n: info.rounds_left })
    : t('s19.none');
  // 換了假扮對象：白天才演面具碎裂重組（ART 11.2）；app.js 偵測到換臉時設定演出時間
  const swapping = (store.ui.disguiseSwapUntil ?? 0) > performance.now();
  return h('div', { class: `panel disguise ${swapping ? 'disguise--swap' : ''}`, testid: 'disguise-panel' },
    roleEmblem('faceless', 28), h('span', { class: 'disguise__text' }, text));
}

